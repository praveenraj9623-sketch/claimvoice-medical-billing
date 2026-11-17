import json

import httpx
import pytest

from claimvoice.config import Config
from claimvoice.groq_client import GroqClient, ServiceError
from claimvoice.phone.ai_review import check_ai
from claimvoice.phone.engine import Call
from claimvoice.phone.review import check_transcript, metrics
from claimvoice.phone.simulator import FIXTURES, benchmark, simulate
from claimvoice.phone.storage import Store
from claimvoice.workflow import start, submit


@pytest.mark.parametrize("case", FIXTURES)
def test_phone_fixtures(case):
    report = simulate(case)
    assert report["outcome"] == FIXTURES[case].expected_outcome
    if FIXTURES[case].gold is not None:
        assert report["fields"] == FIXTURES[case].gold
    if case == "Paid after hold":
        agent = [item["text"] for item in report["transcript"] if item["speaker"] == "agent"]
        assert agent[:2] == ["DTMF 2", "DTMF 1"]
        assert "Of course. I will wait." in agent
        assert any("The claim number is TEST-48213." in turn for turn in agent)
    if case == "Missing payment amount":
        assert report["checks"] == ["missing:paid_amount"]


def test_no_guessing_when_route_changes():
    call = Call()
    assert call.prompt("For claims press 3. For benefits press 2.") == []
    assert call.prompt("For claims press 3.")[-1].value == "ivr_mismatch"
    assert call.menu_step == 0


def test_benchmark_separates_completion_from_ivr_and_field_matching():
    result = metrics(benchmark())
    assert (result["attempts"], result["ivr_passed"], result["complete"], result["needs_review"]) == (6, 5, 3, 3)
    assert result["fixture_matching_fields"] == result["fixture_checked_fields"] == 28
    assert result["estimated_cost_per_completed_call"] == 0


def test_checker_flags_changed_field_and_missing_quote():
    report = simulate("Paid after hold")
    report["fields"]["paid_amount"] = "999.99"
    del report["evidence"]["reference_number"]
    issues = check_transcript(report["fields"], report["evidence"], report["transcript"])
    assert set(issues) == {"unsupported:paid_amount", "unsupported:reference_number"}


def test_ai_checker_one_request_and_no_field_mutation():
    report = simulate("Paid after hold")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        result = {"issues": [{"field": "paid_amount", "reason": "ambiguous"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})

    client = GroqClient(Config("test"), httpx.MockTransport(handler))
    assert check_ai(client, report) == ["ai:ambiguous:paid_amount"]
    assert len(requests) == 1 and "tools" not in requests[0]
    assert report["fields"]["paid_amount"] == "125.50"
    bad = GroqClient(Config("test"), httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": '{"issues":[{}]}'}}]}),
    ))
    with pytest.raises(ServiceError, match="invalid findings"):
        check_ai(bad, report)


def test_successful_end_tool_stops_llm_loop():
    requests = []

    def handler(request):
        requests.append(request)
        action = {"id": "end1", "type": "function",
                  "function": {"name": "end_session", "arguments": '{"supporting_turn_id":2}'}}
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [action]}}]})

    state = start("SYN-AMB-1001", "Live Groq")
    assert submit(state, "Please end the session.", "close", GroqClient(Config("test"), httpx.MockTransport(handler)))
    assert state.ended and len(requests) == 1 and state.error == ""


def test_sqlite_persists_report_and_late_provider_callback(tmp_path):
    path = str(tmp_path / "phone.sqlite3")
    store = Store(path)
    report = simulate("Denied with a code")
    identifier = report["call_id"]
    sid = "CA" + "a" * 32
    assert store.reserve_dial(identifier, "request-1", 170, 200_000, 1_000_000) == (identifier, True)
    assert store.bind_provider(identifier, sid)
    assert store.claim_relay(identifier, sid)
    assert not Store(path).claim_relay(identifier, sid)
    store.finish(identifier, report)
    store.finish(identifier, {"outcome": "duplicate"})
    store.update_provider(identifier, sid, "completed", 62)
    saved = Store(path).reports(lambda seconds: seconds * 0.01)[0]
    assert saved["fields"]["denial_code"] == "CO-16"
    assert saved["provider_seconds"] == 62 and saved["estimated_cost_usd"] == 0.62
