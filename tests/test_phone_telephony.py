from dataclasses import replace
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

pytest.importorskip("twilio")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from claimvoice.phone.simulator import MENU_PROMPTS, PENDING
from claimvoice.phone.storage import DialBlocked, Store
from claimvoice.phone.telephony import Settings, create_app, dial

SID = "CA" + "b" * 32


@pytest.fixture
def settings():
    return Settings("AC" + "a" * 32, "test", "https://test.example", "+12025550100", "+12025550101",
                    Decimal("0.10"), Decimal("0.30"), dialing_enabled=True)


def test_outbound_dial_is_bounded_and_does_not_record(settings, tmp_path):
    store = Store(str(tmp_path / "phone.sqlite3"))
    calls = []
    def place_call(**values):
        calls.append(values)
        return SimpleNamespace(sid=SID)

    client = SimpleNamespace(calls=SimpleNamespace(create=place_call))
    identifier = dial(settings, store, client, "request-1")
    assert dial(settings, store, client, "request-1") == identifier
    sent, = calls
    assert sent["to"] == settings.test_number and sent["time_limit"] == settings.max_seconds
    assert sent["record"] is False
    assert "<ConversationRelay" in sent["twiml"] and identifier in sent["twiml"]
    assert settings.estimated_cost(61) == 0.20


def test_cost_ceiling_blocks_dial_at_configuration(monkeypatch, settings):
    entries = {
        "TWILIO_ACCOUNT_SID": settings.account_sid, "TWILIO_AUTH_TOKEN": settings.auth_token,
        "CLAIMVOICE_PUBLIC_URL": settings.public_url, "TWILIO_FROM_NUMBER": settings.source_number,
        "CLAIMVOICE_TEST_NUMBER": settings.test_number, "CLAIMVOICE_ESTIMATED_USD_PER_MIN": "0.40",
        "CLAIMVOICE_MAX_ESTIMATED_USD": "0.50", "CLAIMVOICE_MAX_CALL_SECONDS": "120",
    }
    for key, value in entries.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="exceeds"):
        Settings.load()


def test_signed_relay_writes_dtmf_transcript_and_provider_result(settings, tmp_path):
    store = Store(str(tmp_path / "phone.sqlite3"))
    attempt = "0" * 32
    assert store.reserve_dial(attempt, "request-1", 170, 200_000, 1_000_000) == (attempt, True)
    assert store.bind_provider(attempt, SID)
    validator = RequestValidator(settings.auth_token)
    headers = {"X-Twilio-Signature": validator.compute_signature(settings.relay_url, {})}
    with TestClient(create_app(settings, store)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/relay"):
                pass
        setup = {"type": "setup", "accountSid": settings.account_sid, "callSid": SID,
                 "from": settings.source_number, "to": settings.test_number,
                 "customParameters": {"attemptId": attempt}}
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/relay", headers=headers) as wrong_call:
                wrong_call.send_json(dict(setup, callSid="CA" + "c" * 32))
                wrong_call.receive_json()
        with client.websocket_connect("/relay", headers=headers) as socket:
            socket.send_json(setup)
            for prompt, digits in zip(MENU_PROMPTS[:2], ("2", "1")):
                socket.send_json({"type": "prompt", "last": True, "voicePrompt": prompt})
                assert socket.receive_json() == {"type": "sendDigits", "digits": digits}
            socket.send_json({"type": "prompt", "last": True, "voicePrompt": MENU_PROMPTS[2]})
            assert "TEST-48213" in socket.receive_json()["token"]
            for answer in PENDING[:-1]:
                socket.send_json({"type": "prompt", "last": True, "voicePrompt": answer})
                assert socket.receive_json()["type"] == "text"
            socket.send_json({"type": "prompt", "last": True, "voicePrompt": PENDING[-1]})
            assert socket.receive_json() == {"type": "end"}
        route = f"/status?attempt={attempt}"
        form = {"AccountSid": settings.account_sid, "CallSid": SID, "CallStatus": "completed", "CallDuration": "61"}
        assert client.post(route, data=form).status_code == 403
        signature = validator.compute_signature(settings.public_url + route, form)
        assert client.post(route, data=form, headers={"X-Twilio-Signature": signature}).status_code == 204
        assert client.post(route, data=form, headers={"X-Twilio-Signature": signature}).status_code == 204
        assert client.get("/ready").json() == {"status": "ready"}
        store.ready = lambda: False
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
    record = store.reports(settings.estimated_cost)[0]
    assert record["fields"]["status"] == "pending"
    assert record["review_status"] == "evidence_matched" and record["estimated_cost_usd"] == 0.20


def test_provider_timeout_never_duplicates_a_retry(settings, tmp_path):
    store = Store(str(tmp_path / "phone.sqlite3"))
    attempts = []

    def unconfirmed(**values):
        attempts.append(values)
        raise TimeoutError

    client = SimpleNamespace(calls=SimpleNamespace(create=unconfirmed))
    with pytest.raises(RuntimeError, match="was not confirmed"):
        dial(settings, store, client, "same-request")
    first = store.reports(settings.estimated_cost)[0]
    assert first["provider_status"] == "dial_unconfirmed"
    assert dial(settings, store, client, "same-request") == first["call_id"]
    with pytest.raises(DialBlocked, match="awaiting provider"):
        dial(settings, store, client, "new-request")
    assert len(attempts) == 1


def test_daily_budget_is_reserved_and_the_kill_switch_blocks_dial(settings, tmp_path):
    store = Store(str(tmp_path / "phone.sqlite3"))
    client = SimpleNamespace(calls=SimpleNamespace(create=lambda **values: SimpleNamespace(sid=SID)))
    with pytest.raises(RuntimeError, match="disabled"):
        dial(replace(settings, dialing_enabled=False), store, client, "disabled")
    settings = replace(settings, daily_limit_usd=Decimal("0.20"))
    call = dial(settings, store, client, "first")
    assert store.update_provider(call, SID, "completed", 1)
    with pytest.raises(DialBlocked, match="daily estimated"):
        dial(settings, store, client, "second")


def test_reservations_serialize_two_concurrent_operators(tmp_path):
    store = Store(str(tmp_path / "phone.sqlite3"))
    barrier = Barrier(2)

    def reserve(index):
        barrier.wait(timeout=5)
        try:
            return store.reserve_dial(str(index), str(index), 170, 200_000, 1_000_000)[1]
        except DialBlocked:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reserve, (1, 2))) == [False, True]


def test_ai_findings_flag_the_existing_record_without_overwriting_capture(settings, tmp_path):
    store = Store(str(tmp_path / "phone.sqlite3"))
    attempt = "1" * 32
    store.reserve_dial(attempt, "ai-review", 170, 200_000, 1_000_000)
    report = {
        "call_id": attempt, "checks": [], "fields": {"status": "pending"}, "review_status": "evidence_matched",
    }
    store.finish(attempt, report)
    assert store.begin_ai_review(attempt)
    pending, = store.reports(settings.estimated_cost, call_id=attempt)
    assert pending["ai_review_status"] == "unconfirmed"
    assert pending["review_status"] == "needs_review"
    store.finish_ai_review(attempt, ["ai:ambiguous:status"])
    assert not store.begin_ai_review(attempt)
    store.finish_ai_review(attempt, [])
    saved, = store.reports(settings.estimated_cost, call_id=attempt)
    assert saved["fields"] == {"status": "pending"}
    assert saved["checks"] == ["ai:ambiguous:status"]
    assert saved["review_status"] == "needs_review"


def test_hosted_mode_rejects_local_storage(monkeypatch, settings):
    for key, value in {
        "CLAIMVOICE_ENV": "hosted", "CLAIMVOICE_PHONE_STORAGE": "phone.sqlite3",
        "TWILIO_ACCOUNT_SID": settings.account_sid, "TWILIO_AUTH_TOKEN": settings.auth_token,
        "CLAIMVOICE_PUBLIC_URL": settings.public_url, "TWILIO_FROM_NUMBER": settings.source_number,
        "CLAIMVOICE_TEST_NUMBER": settings.test_number, "CLAIMVOICE_ESTIMATED_USD_PER_MIN": "0.10",
        "CLAIMVOICE_MAX_ESTIMATED_USD": "0.50", "CLAIMVOICE_DAILY_ESTIMATED_USD": "1.00",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="verify-full"):
        Settings.load()
