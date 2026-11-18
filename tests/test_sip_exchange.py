import pytest

from claimcall.audio_probe import CASES
from claimcall.sip_exchange import evaluate


def test_capture_only_sees_the_received_reply():
    reply = "Daniel here. The claim is pending."
    inputs = []

    def capture(text):
        inputs.append(text)
        return CASES["pending"][1]

    result = evaluate("Calling from billing. What is the status?", reply, capture)
    assert inputs == [reply]
    assert result["mismatches"] == []
    assert result["captured"]["reference"] is None


def test_missing_outbound_speech_and_invented_payment_fail():
    def capture(text):
        return CASES["pending"][1].model_copy(update={"reference": "8841"})

    result = evaluate("", "The claim is pending.", capture)
    assert set(result["mismatches"]) == {"reference", "caller question"}


def test_missing_reply_stops_before_extraction():
    with pytest.raises(ValueError, match="No insurer reply"):
        evaluate("billing status", " ", lambda _: pytest.fail("Unexpected model call"))
