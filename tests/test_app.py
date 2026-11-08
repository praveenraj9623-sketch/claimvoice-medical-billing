import sys
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_launch_and_review(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    at = AppTest.from_file(APP).run()
    assert not at.exception
    button(at, "Start / reset session").click().run()
    assert not at.exception
    button(at, "Use scenario example").click().run()
    button(at, "Send reply").click().run()
    assert not at.exception
    state = at.session_state.cv
    assert state.draft and not state.saved
    at.run()
    assert len(at.session_state.cv.turns) == 3
    at.checkbox[0].check().run()
    button(at, "Save reviewed follow-up").click().run()
    assert len(at.session_state.cv.saved) == 1
    button(at, "Start / reset session").click().run()
    assert at.session_state.cv.draft is None
    assert 'livekit' not in sys.modules


def test_browser_sessions_isolated():
    a = AppTest.from_file(APP).run()
    b = AppTest.from_file(APP).run()
    button(a, "Start / reset session").click().run()
    button(b, "Start / reset session").click().run()
    assert a.session_state.cv.session_id != b.session_state.cv.session_id


def test_audio_requires_explicit_action_and_deduplicates(monkeypatch):
    from claimvoice.groq_client import GroqClient
    monkeypatch.setenv("GROQ_API_KEY", "fake-offline-key")
    calls = []
    def transcribe(self, audio):
        calls.append(audio)
        return "Editable fictional insurer statement"
    monkeypatch.setattr(GroqClient, "transcribe", transcribe)
    at = AppTest.from_file(APP).run()
    at.selectbox[0].select("Live Groq").run()
    button(at, "Start / reset session").click().run()
    at.audio_input[0].upload("recording.wav", b"mock-wav").run()
    assert not calls
    button(at, "Transcribe recording with Groq").click().run()
    assert len(calls) == 1
    assert at.text_area[0].value == "Editable fictional insurer statement"
    assert len(at.session_state.cv.turns) == 1
    at.run()
    button(at, "Transcribe recording with Groq").click().run()
    assert len(calls) == 1


def test_live_failure_explicit_retry_without_duplicate_user(monkeypatch):
    from claimvoice.groq_client import GroqClient, ServiceError
    monkeypatch.setenv("GROQ_API_KEY", "fake-offline-key")
    attempts = []
    def reply(self, state):
        attempts.append(len(state.turns))
        if len(attempts) == 1:
            raise ServiceError("Groq timed out. Conversation preserved; retry explicitly.")
        return "What is the reference number?"
    monkeypatch.setattr(GroqClient, "reply", reply)
    at = AppTest.from_file(APP).run()
    at.selectbox[0].select("Live Groq").run()
    button(at, "Start / reset session").click().run()
    at.text_area[0].input("Pending processing")
    button(at, "Send reply").click().run()
    assert len(at.session_state.cv.turns) == 2 and len(attempts) == 1
    at.run()
    assert len(attempts) == 1
    button(at, "Retry assistant explicitly").click().run()
    assert len(attempts) == 2 and len(at.session_state.cv.turns) == 3
    assert not at.exception
