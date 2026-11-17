"""Host an outbound ConversationRelay service for an authorized synthetic test line."""

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
import logging
from math import ceil
import os
import re
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4
from xml.etree import ElementTree as XML

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from twilio.http.http_client import TwilioHttpClient
from twilio.request_validator import RequestValidator
from twilio.rest import Client

from claimvoice.config import load_config
from claimvoice.groq_client import GroqClient, ServiceError

from .ai_review import check_ai
from .engine import Call
from .review import build_report, metrics
from .storage import Store

LOGGER = logging.getLogger("claimvoice.phone")
CALL_SID = re.compile(r"CA[a-fA-F0-9]{32}")
ATTEMPT_ID = re.compile(r"[a-f0-9]{32}")
REQUEST_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}")
TERMINAL = {"completed", "busy", "no-answer", "failed", "canceled"}


def decimal_setting(name):
    try:
        value = Decimal(os.environ[name])
    except (KeyError, InvalidOperation) as exc:
        raise ValueError(f"Set {name} to a nonnegative USD amount.") from exc
    if not value.is_finite() or not 0 <= value <= 100 or value != value.quantize(Decimal("0.000001")):
        raise ValueError(f"Set {name} to a USD amount between 0 and 100 with up to six decimal places.")
    return value


@dataclass(frozen=True)
class Settings:
    account_sid: str
    auth_token: str = field(repr=False)
    public_url: str
    source_number: str = field(repr=False)
    test_number: str = field(repr=False)
    rate_usd: Decimal
    call_limit_usd: Decimal
    max_seconds: int = 120
    storage: str = field(default="claimvoice-phone.sqlite3", repr=False)

    daily_limit_usd: Decimal = Decimal("1.00")
    dialing_enabled: bool = False

    @classmethod
    def load(cls):
        load_dotenv()
        sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_AUTH_TOKEN", "")
        public_url = os.getenv("CLAIMVOICE_PUBLIC_URL", "").rstrip("/")
        source = os.getenv("TWILIO_FROM_NUMBER", "")
        target = os.getenv("CLAIMVOICE_TEST_NUMBER", "")
        parsed = urlsplit(public_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Set CLAIMVOICE_PUBLIC_URL to a public HTTPS origin.")
        if not re.fullmatch(r"AC[a-fA-F0-9]{32}", sid) or not token:
            raise ValueError("Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
        if source == target or any(not re.fullmatch(r"\+[1-9]\d{7,14}", number) for number in (source, target)):
            raise ValueError("Configure separate E.164 source and authorized TEST numbers.")
        maximum = int(os.getenv("CLAIMVOICE_MAX_CALL_SECONDS", "120"))
        if not 45 <= maximum <= 180:
            raise ValueError("CLAIMVOICE_MAX_CALL_SECONDS must be between 45 and 180.")
        rate, budget = decimal_setting("CLAIMVOICE_ESTIMATED_USD_PER_MIN"), decimal_setting("CLAIMVOICE_MAX_ESTIMATED_USD")
        if rate <= 0 or rate * ceil(maximum / 60) > budget:
            raise ValueError("The estimated cost at the duration cap exceeds the configured budget, or the rate is zero.")
        storage = os.getenv("CLAIMVOICE_PHONE_STORAGE", "claimvoice-phone.sqlite3")
        if os.getenv("CLAIMVOICE_ENV", "local") == "hosted":
            from psycopg.conninfo import conninfo_to_dict

            connection = conninfo_to_dict(storage) if storage.startswith(("postgresql://", "postgres://")) else {}
            if connection.get("sslmode") != "verify-full":
                raise ValueError("Hosted mode requires a PostgreSQL DSN with sslmode=verify-full.")
        elif os.getenv("CLAIMVOICE_ENV", "local") != "local":
            raise ValueError("CLAIMVOICE_ENV must be local or hosted.")
        daily = decimal_setting("CLAIMVOICE_DAILY_ESTIMATED_USD")
        if daily < rate * ceil(maximum / 60):
            raise ValueError("The daily estimated budget must cover at least one full test call.")
        enabled = os.getenv("CLAIMVOICE_DIALING_ENABLED", "false")
        if enabled not in {"true", "false"}:
            raise ValueError("CLAIMVOICE_DIALING_ENABLED must be true or false.")
        return cls(sid, token, public_url, source, target, rate, budget, maximum, storage, daily, enabled == "true")

    @property
    def reserved_micros(self):
        return int(self.rate_usd * ceil(self.max_seconds / 60) * 1_000_000)

    def estimated_cost(self, seconds):
        return float(self.rate_usd * ceil(seconds / 60))

    @property
    def relay_url(self):
        return "wss://" + self.public_url.removeprefix("https://") + "/relay"


def relay_xml(settings, attempt_id):
    root = XML.Element("Response")
    connect = XML.SubElement(root, "Connect")
    relay = XML.SubElement(connect, "ConversationRelay", url=settings.relay_url,
                           ttsProvider="Amazon", voice="Joanna", language="en-US",
                           interruptible="none")
    XML.SubElement(relay, "Parameter", name="attemptId", value=attempt_id)
    XML.SubElement(root, "Hangup")
    return XML.tostring(root, encoding="unicode")


def dial(settings, store, client, request_id):
    if not settings.dialing_enabled:
        raise RuntimeError("Outbound dialing is disabled in the operator environment.")
    if not REQUEST_ID.fullmatch(request_id):
        raise ValueError("Use a 1–80 character request ID with letters, digits, dots, hyphens or underscores.")
    attempt_id, created = store.reserve_dial(
        uuid4().hex, request_id, settings.max_seconds + 50, settings.reserved_micros,
        int(settings.daily_limit_usd * 1_000_000),
    )
    if not created:
        return attempt_id
    try:
        call = client.calls.create(
            from_=settings.source_number, to=settings.test_number,
            twiml=relay_xml(settings, attempt_id),
            timeout=25, time_limit=settings.max_seconds, record=False,
            status_callback=f"{settings.public_url}/status?attempt={attempt_id}",
            status_callback_event=["completed"], status_callback_method="POST",
        )
        if not isinstance(call.sid, str) or not CALL_SID.fullmatch(call.sid) or not store.bind_provider(attempt_id, call.sid):
            raise ValueError("Provider call identifier could not be recorded.")
    except Exception:
        store.note_unconfirmed_dial(attempt_id)
        raise RuntimeError(f"Dial {attempt_id} was not confirmed. Check the provider console before retrying.") from None
    return attempt_id


async def send_actions(socket, actions):
    for action in actions:
        if action.kind == "digits":
            await socket.send_json({"type": "sendDigits", "digits": action.value})
        elif action.kind == "speak":
            await socket.send_json({"type": "text", "token": action.value, "last": True})
        elif action.kind == "end":
            await socket.send_json({"type": "end"})


async def bounded_form(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        raise ValueError("Unsupported callback content type")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192:
            raise ValueError("Callback too large")
        body.extend(chunk)
    return FormData(parse_qsl(body.decode("utf-8"), keep_blank_values=True, max_num_fields=64))


def create_app(settings, store):
    @asynccontextmanager
    async def lifespan(app):
        if not await run_in_threadpool(store.ready):
            raise RuntimeError("Call storage is unavailable.")
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    validator = RequestValidator(settings.auth_token)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        try:
            if await run_in_threadpool(store.ready):
                return {"status": "ready"}
        except Exception:
            LOGGER.error("call_storage_unavailable")
        return Response(status_code=503)

    @app.post("/status")
    async def status(request: Request):
        try:
            form = await asyncio.wait_for(bounded_form(request), timeout=5)
        except (ValueError, TimeoutError):
            return Response(status_code=400)
        url = f"{settings.public_url}/status"
        if request.url.query:
            url += f"?{request.url.query}"
        if not validator.validate(url, form, request.headers.get("X-Twilio-Signature", "")):
            return Response(status_code=403)
        attempt_id = request.query_params.get("attempt", "")
        sid = form.get("CallSid", "")
        value = form.get("CallStatus")
        duration = form.get("CallDuration", "")
        if (form.get("AccountSid") != settings.account_sid or not ATTEMPT_ID.fullmatch(attempt_id)
                or not CALL_SID.fullmatch(sid) or value not in TERMINAL):
            return Response(status_code=400)
        seconds = int(duration) if isinstance(duration, str) and re.fullmatch(r"\d{1,8}", duration) else None
        if value != "completed" and seconds is None:
            seconds = 0
        accepted = await run_in_threadpool(store.update_provider, attempt_id, sid, value, seconds)
        return Response(status_code=204 if accepted else 409)

    @app.websocket("/relay")
    async def relay(socket: WebSocket):
        signature = socket.headers.get("X-Twilio-Signature", "")
        if not validator.validate(settings.relay_url, {}, signature):
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            setup = await asyncio.wait_for(socket.receive_json(), timeout=5)
            attempt_id = setup["customParameters"]["attemptId"]
            sid = setup["callSid"]
            if (setup["type"] != "setup" or setup["accountSid"] != settings.account_sid
                    or setup["from"] != settings.source_number or setup["to"] != settings.test_number
                    or not ATTEMPT_ID.fullmatch(attempt_id) or not CALL_SID.fullmatch(sid)):
                raise ValueError("Invalid setup")
        except WebSocketDisconnect:
            return
        except (TimeoutError, ValueError, TypeError, KeyError):
            await socket.close(code=1008)
            return
        if not await run_in_threadpool(store.bind_provider, attempt_id, sid) or not await run_in_threadpool(
            store.claim_relay, attempt_id, sid
        ):
            await socket.close(code=1008)
            return

        call = Call(max_seconds=settings.max_seconds, call_id=attempt_id)
        try:
            while call.outcome == "in_progress":
                try:
                    event = await asyncio.wait_for(socket.receive_json(), timeout=call.seconds_remaining())
                except TimeoutError:
                    await send_actions(socket, call.timeout())
                    break
                if event.get("type") == "error":
                    await send_actions(socket, call.finish("provider_error"))
                    break
                if event.get("type") == "prompt" and event.get("last") is True:
                    prompt = event.get("voicePrompt")
                    if not isinstance(prompt, str):
                        raise ValueError("Invalid prompt")
                    await send_actions(socket, call.prompt(prompt))
        except WebSocketDisconnect:
            call.finish("disconnected")
        except (ValueError, AttributeError):
            await send_actions(socket, call.finish("invalid_provider_message"))
        finally:
            if call.outcome == "in_progress":
                call.finish("connection_error")
            report = build_report(call, transport="twilio")
            await run_in_threadpool(store.finish, attempt_id, report)
            LOGGER.info("relay_finished attempt=%s outcome=%s review=%s", attempt_id, call.outcome, report["review_status"])

    return app


def app_factory():
    settings = Settings.load()
    return create_app(settings, Store(settings.storage))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    report_cmd = sub.add_parser("report", help="Show recent outcomes and metrics, or look up an attempt")
    report_cmd.add_argument("--call-id")
    review_cmd = sub.add_parser("review-ai", help="Get a separate AI opinion for one synthetic transcript")
    review_cmd.add_argument("call_id")
    dial_cmd = sub.add_parser("dial", help="Dial the configured synthetic test destination once")
    dial_cmd.add_argument("--request-id", required=True, help="Reuse this ID to check the same dial request safely")
    dial_cmd.add_argument("--confirm-test-call", action="store_true", required=True)
    args = parser.parse_args()
    try:
        settings = Settings.load()
        store = Store(settings.storage)
        if args.command == "dial":
            client = Client(settings.account_sid, settings.auth_token, http_client=TwilioHttpClient(timeout=10))
            print(dial(settings, store, client, args.request_id))
        elif args.command == "report":
            reports = store.reports(settings.estimated_cost, call_id=args.call_id)
            print(json.dumps({"metrics": metrics(reports), "calls": reports}, indent=2))
        else:
            reports = store.reports(settings.estimated_cost, call_id=args.call_id)
            if not reports or not reports[0]["transcript"]:
                raise ValueError("No saved transcript found for this attempt.")
            candidate = reports[0]
            config = load_config()
            if candidate["ai_review_status"] == "not_run" and not config.api_key:
                raise ValueError("Set a Groq key to run the optional synthetic transcript review.")
            if store.begin_ai_review(args.call_id):
                try:
                    findings = check_ai(GroqClient(config), candidate)
                except ServiceError:
                    findings = ["ai_checker_unavailable"]
                store.finish_ai_review(args.call_id, findings)
            record = store.reports(settings.estimated_cost, call_id=args.call_id)[0]
            print(json.dumps({
                "call_id": args.call_id, "issues": record["checks"],
                "needs_review": record["review_status"] == "needs_review",
                "ai_review_status": record["ai_review_status"],
            }, indent=2))
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
