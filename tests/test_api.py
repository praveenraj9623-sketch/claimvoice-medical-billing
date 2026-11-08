import io
import json
import wave
import httpx
import pytest
from claimvoice.config import Config
from claimvoice.groq_client import GroqClient, ServiceError
from claimvoice.workflow import start, submit


def client(handler):
    return GroqClient(Config("DO-NOT-EXPOSE"), httpx.MockTransport(handler))


@pytest.mark.parametrize("status,phrase", [(401, "authentication"), (403, "authentication"), (429, "rate limit"), (500, "unavailable")])
def test_http_errors_preserve_conversation(status, phrase):
    c = client(lambda req: httpx.Response(status, text="DO-NOT-EXPOSE"))
    s = start("SYN-AMB-1001", "Live Groq")
    assert not submit(s, "pending", "r", c)
    assert len(s.turns) == 2 and s.turns[-1]["content"] == "pending"
    assert phrase in s.error and "DO-NOT-EXPOSE" not in s.error
    assert not submit(s, "pending", "r", c) and len(s.turns) == 2


def test_timeout_and_malformed():
    def timeout(req):
        raise httpx.ReadTimeout("DO-NOT-EXPOSE")
    with pytest.raises(ServiceError, match="timed out"):
        client(timeout).post("chat/completions")
    for body in ({}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}, [], {"choices": [{"message": None}]}):
        s = start("SYN-AMB-1001", "Live Groq")
        assert not submit(s, "pending", "r", client(lambda req: httpx.Response(200, json=body)))
        assert "malformed" in s.error


def test_tool_result_roundtrip_and_bound():
    bodies = []
    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if len(bodies) == 1:
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "lookup_claim", "arguments": '{"claim_id":"SYN-AMB-1001"}'}}]}
        else:
            tool = body["messages"][-1]
            assert tool["role"] == "tool" and tool["tool_call_id"] == "call1"
            assert json.loads(tool["content"])["ok"]
            msg = {"content": "Could you confirm the reference?"}
        return httpx.Response(200, json={"choices": [{"message": msg, "finish_reason": "stop"}]})
    s = start("SYN-AMB-1001", "Live Groq")
    assert submit(s, "pending", "r", client(handler))
    assert len(bodies) == 2
    count = []
    def loop(req):
        count.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [{"id": "bad", "type": "function", "function": {"name": "bad_tool", "arguments": "INVALID JSON"}}]}}]})
    s = start("SYN-AMB-1001", "Live Groq")
    assert not submit(s, "pending", "r", client(loop))
    assert len(count) == 4 and "limit" in s.error
    assert all(not a["ok"] for a in s.activity[1:])


def test_stt_multipart_and_empty():
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 1600)
    def handler(req):
        assert req.url.path.endswith('/audio/transcriptions')
        assert b'whisper-large-v3-turbo' in req.content and b'recording.wav' in req.content
        return httpx.Response(200, json={"text": "Pending processing"})
    assert client(handler).transcribe(out.getvalue()) == "Pending processing"
    with pytest.raises(ServiceError):
        client(lambda req: httpx.Response(200, json={"text": ""})).transcribe(out.getvalue())


def test_live_draft_tool_and_invalid_arguments_returned_to_model():
    seen = []
    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        if len(seen) < 3:
            args = {"reported_status": "pending", "reference_number": None,
                    "requested_documents": None, "next_action": None,
                    "follow_up_date": None, "supporting_turn_ids": [2]}
            if len(seen) == 1:
                args["reference_number"] = "made-up"
            msg = {"content": None, "tool_calls": [{"id": f"c{len(seen)}", "type": "function", "function": {"name": "record_draft", "arguments": json.dumps(args)}}]}
        else:
            msg = {"content": "Draft ready for human review."}
        return httpx.Response(200, json={"choices": [{"message": msg, "finish_reason": "stop"}]})
    s = start("SYN-AMB-1001", "Live Groq")
    assert submit(s, "pending", "r", client(handler))
    assert not json.loads(seen[1]["messages"][-1]["content"])["ok"]
    assert json.loads(seen[2]["messages"][-1]["content"])["ok"]
    assert s.draft["reported_status"] == "pending" and s.draft["reference_number"] is None
    assert s.saved == []
