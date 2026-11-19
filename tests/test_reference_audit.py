import json

import pytest

from claimcall.reference_audit import audit_files


TURNS = ["First digit is 8, second digit is 8, third digit is 4, fourth digit is 1",
         "Position 1 is 8, position 2 is 8, position 3 is 4, position 4 is 1."]


def write_inputs(directory, saved, turns):
    record = directory / "result.json"
    transcript = directory / "transcripts.json"
    record.write_text(json.dumps({"captured": {"reference": saved}, "mismatches": [],
                                 "reference_needs_review": False, "initial_capture": {"reference": "841"}}))
    transcript.write_text(json.dumps({"reference_readings": turns}))
    return record, transcript


def test_saved_call_and_corrupted_copy(tmp_path):
    original, transcript = write_inputs(tmp_path, "8841", TURNS)
    source = (original.read_bytes(), transcript.read_bytes())
    assert audit_files(original, transcript)["decision"] == "verified"

    changed = json.loads(original.read_text())
    changed["captured"]["reference"] = "841"
    copy = tmp_path / "changed.json"
    copy.write_text(json.dumps(changed))
    audit = audit_files(copy, transcript)
    assert audit["decision"] == "review_required"
    assert audit["saved_value"] == "841"
    assert audit["confirmed_value"] == "8841"
    assert [item["quote"] for item in audit["evidence"]] == TURNS
    assert [item["turn"] for item in audit["evidence"]] == [1, 2]
    assert (original.read_bytes(), transcript.read_bytes()) == source


@pytest.mark.parametrize("saved,turns", [
    ("8841", []), ("8841", TURNS[:1]), ("8841", [*TURNS, TURNS[1]]),
    ("8841", [TURNS[0], "unclear"]), ("8841", [TURNS[0], "Position 1 is 3."]),
    (None, TURNS), ("1", ["First digit is zero. Second digit is one."] * 2),
])
def test_insufficient_conflicting_or_missing_reference_requires_review(tmp_path, saved, turns):
    audit = audit_files(*write_inputs(tmp_path, saved, turns))
    assert audit["decision"] == "review_required"
    assert audit["review_required"]


def test_unreadable_evidence_fails_closed(tmp_path):
    record, transcript = write_inputs(tmp_path, "8841", TURNS)
    for content in ("{", "null", "{}", '{"reference_readings": "8841"}'):
        transcript.write_text(content)
        result = audit_files(record, transcript)
        assert result["decision"] == "audit_failed"
        assert result["review_required"]
    transcript.unlink()
    assert audit_files(record, transcript)["decision"] == "audit_failed"
