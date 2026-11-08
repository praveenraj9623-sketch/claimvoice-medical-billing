import csv
import io
import json
import pytest
from claimvoice.claims import SCENARIOS
from claimvoice.workflow import start, submit
from claimvoice.tools import execute, FIELDS
from claimvoice.storage import save_reviewed, export_json, export_csv
from claimvoice.config import load_config
from claimvoice.speech import speech_html, validate_wav


def test_config_precedence(tmp_path):
    path = tmp_path / ".env"
    path.write_text("GROQ_API_KEY=file\nGROQ_MODEL=file-model\n")
    cfg = load_config({"GROQ_API_KEY": "secret", "GROQ_MODEL": "secret-model"}, {"GROQ_API_KEY": "env"}, path)
    assert cfg.api_key == "env" and cfg.model == "secret-model"
    assert "env" not in repr(cfg)
    assert load_config({}, {}, path).api_key == "file"


@pytest.mark.parametrize("example", SCENARIOS.values())
def test_scripted_save_and_exports(example):
    state = start("SYN-AMB-1001", "Scripted walkthrough")
    assert submit(state, example, "r1")
    assert state.draft["supporting_transcript_turns"][0]["content"] == example
    with pytest.raises(ValueError):
        save_reviewed(state, False)
    saved = save_reviewed(state, True)
    assert save_reviewed(state, True) == saved and len(state.saved) == 1
    assert json.loads(export_json(state.saved))[0]["reviewed"]
    assert list(csv.DictReader(io.StringIO(export_csv(state.saved))))[0]["claim_id"] == state.claim_id
    state.draft["reported_status"] = "changed"
    assert saved["reported_status"] != "changed"


def test_isolation_and_duplicates():
    a = start("SYN-AMB-1001", "Scripted walkthrough")
    b = start("SYN-AMB-1002", "Scripted walkthrough")
    submit(a, "Status: pending", "same")
    assert not submit(a, "Status: pending", "same")
    assert len(a.turns) == 3 and len(b.turns) == 1
    assert b.draft is None and b.saved == [] and a.session_id != b.session_id
    with pytest.raises(ValueError):
        submit(a, " ", "empty")
    with pytest.raises(ValueError):
        start("UNKNOWN", "Scripted walkthrough")


def test_tools_and_evidence_validation():
    s = start("SYN-AMB-1001", "Scripted walkthrough")
    assert not execute(s, "lookup_claim", {"claim_id": "SYN-AMB-1002"})["ok"]
    assert not execute(s, "dial", {})["ok"]
    assert not execute(s, "lookup_claim", {"claim_id": s.claim_id, "extra": True})["ok"]
    t = s.add("user", "pending, REF-12, 2026-11-23")
    args = {**{f: None for f in FIELDS}, "reported_status": "pending", "supporting_turn_ids": [t["id"]]}
    assert execute(s, "record_draft", args)["ok"]
    previous = s.draft.copy()
    for change in ({"reference_number": "invented"}, {"follow_up_date": "tomorrow"}, {"supporting_turn_ids": [True]}, {"reported_status": 12}):
        assert not execute(s, "record_draft", {**args, **change})["ok"]
        assert s.draft == previous
    assert not execute(s, "flag_handoff", {"reason": "invented", "supporting_turn_id": t['id']})["ok"]
    submit(s, "human handoff", "h")
    assert s.handoff
    submit(s, "end session", "e")
    assert s.ended
    with pytest.raises(ValueError):
        submit(s, "hello", "x")


def test_unknown_and_csv_injection():
    s = start("SYN-AMB-1001", "Scripted walkthrough")
    submit(s, "Status: pending; Reference: =CMD()", "r")
    assert s.draft["follow_up_date"] is None and s.draft["requested_documents"] is None
    save_reviewed(s, True)
    assert "'=CMD()" in export_csv(s.saved)


def test_speech_escaping_and_empty_audio():
    html = speech_html('</script><img src=x onerror=alert(1)>')
    assert '</script><img' not in html and '\\u003c/script' in html
    for audio in (b"", b"bad wav", b"a" * (20 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError):
            validate_wav(audio)
