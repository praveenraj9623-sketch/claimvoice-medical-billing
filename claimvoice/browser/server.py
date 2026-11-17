"""FastAPI service for a bounded, synthetic ClaimVoice browser demo."""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from hmac import compare_digest
import logging
import os
from pathlib import Path
import re
import secrets
from time import monotonic
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from pipecat.transports.smallwebrtc.connection import IceServer
from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest, SmallWebRTCRequestHandler
from loguru import logger

from claimvoice.config import load_config
from claimvoice.groq_client import GroqClient

from .pipeline import run_pipeline
from .records import BrowserRecords
from .session import BrowserSession
from .tickets import valid_ticket

STATIC = Path(__file__).with_name("static")
ID = re.compile(r"[a-f0-9]{32}")
LOG = logging.getLogger(__name__)


class Offer(BaseModel):
    sdp: str = Field(min_length=20, max_length=16_384)
    ticket: str = Field(min_length=1, max_length=144)


def create_app(client, records, secret, parent_origin, ice_urls=()):
    handler = SmallWebRTCRequestHandler(ice_servers=[IceServer(urls=url) for url in ice_urls])
    sessions = {}
    starts = deque()
    used_tickets = {}

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            for session, _ in sessions.values():
                await session.finish("service_stopped")
                if session.worker is not None:
                    session.worker.cancel()
            await handler.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'none'; "
            f"frame-ancestors 'self' {parent_origin}"
        )
        return response

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/ready")
    def readiness():
        try:
            return {"status": "ready"} if records.ready() else Response(status_code=503)
        except Exception:
            return Response(status_code=503)

    @app.post("/api/offer")
    async def offer(request: Request):
        payload = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(payload) + len(chunk) > 24_576:
                        raise HTTPException(413, "The audio connection offer is too large.")
                    payload.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "The audio connection offer timed out.") from None
        try:
            body = Offer.model_validate_json(payload)
        except ValidationError:
            raise HTTPException(400, "Invalid audio connection offer.") from None
        now = monotonic()
        if not valid_ticket(secret, body.ticket) or body.ticket in used_tickets:
            raise HTTPException(403, "Launch a new session from ClaimVoice.")
        while starts and now - starts[0] >= 60:
            starts.popleft()
        for call_id, (session, _) in tuple(sessions.items()):
            if session.report is not None and now - session.updated > 900:
                del sessions[call_id]
        for ticket, created in tuple(used_tickets.items()):
            if now - created > 600:
                del used_tickets[ticket]
        if len(starts) >= 6 or sum(s.report is None for s, _ in sessions.values()) >= 3:
            raise HTTPException(429, "The demo is busy. Please retry shortly.")
        if (not body.sdp.startswith("v=0") or len(re.findall(r"(?m)^m=audio ", body.sdp)) != 1
                or re.search(r"(?m)^m=(?:video|application) ", body.sdp)):
            raise HTTPException(400, "Expected an audio-only microphone offer.")
        session = BrowserSession(client, records)
        starts.append(now)
        used_tickets[body.ticket] = now
        call_id = session.call.call_id
        read_key = secrets.token_urlsafe(32)
        sessions[call_id] = session, read_key

        async def start(peer):
            session.peer = peer
            session.worker = asyncio.create_task(run_pipeline(peer, client, session))
            session.worker.add_done_callback(pipeline_stopped)

        def pipeline_stopped(task):
            if not task.cancelled() and task.exception() is not None:
                LOG.error("Browser voice pipeline failed for call %s (%s)", call_id, type(task.exception()).__name__)
                asyncio.create_task(session.finish("connection_error"))

        try:
            answer = await handler.handle_web_request(SmallWebRTCRequest(sdp=body.sdp, type="offer"), start)
            if answer is None:
                raise ValueError("No answer")
        except Exception:
            await session.finish("connection_error")
            raise HTTPException(502, "The voice service could not connect.") from None
        return {"sdp": answer["sdp"], "type": answer["type"], "id": call_id, "key": read_key}

    def authorized(call_id, authorization):
        if not ID.fullmatch(call_id) or call_id not in sessions:
            raise HTTPException(404)
        session, key = sessions[call_id]
        if not compare_digest(authorization.encode(), f"Bearer {key}".encode()):
            raise HTTPException(404)
        return session

    @app.get("/api/sessions/{call_id}")
    async def snapshot(call_id: str, authorization: str = Header(default="")):
        return authorized(call_id, authorization).snapshot()

    @app.post("/api/sessions/{call_id}/end")
    async def end(call_id: str, authorization: str = Header(default="")):
        session = authorized(call_id, authorization)
        await session.finish("ended_by_operator")
        return session.snapshot()

    @app.get("/api/ice")
    async def ice():
        return [{"urls": url} for url in ice_urls]

    return app


def app_factory():
    load_dotenv()
    config = load_config()
    secret = os.getenv("CLAIMVOICE_BROWSER_SECRET", "")
    parent = os.getenv("CLAIMVOICE_STREAMLIT_ORIGIN", "http://localhost:8501").rstrip("/")
    parsed = urlsplit(parent)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.path
            or parsed.query or parsed.fragment or parsed.username is not None
            or any(char.isspace() or char in ";," for char in parent)):
        raise ValueError("Set CLAIMVOICE_STREAMLIT_ORIGIN to the Streamlit app origin.")
    if len(secret) < 32 or not config.api_key:
        raise ValueError("Set a 32-character CLAIMVOICE_BROWSER_SECRET and GROQ_API_KEY.")
    ice = tuple(url.strip() for url in os.getenv("CLAIMVOICE_STUN_URLS", "").split(",") if url.strip())
    if any(not url.startswith("stun:") for url in ice):
        raise ValueError("CLAIMVOICE_STUN_URLS accepts comma-separated STUN endpoints.")
    # Pipecat may log transcripts, SDP or provider responses in debug messages.
    logger.disable("pipecat")
    records = BrowserRecords(os.getenv("CLAIMVOICE_BROWSER_STORAGE", "claimvoice-browser.sqlite3"))
    return create_app(GroqClient(config, timeout=5), records, secret, parent, ice)
