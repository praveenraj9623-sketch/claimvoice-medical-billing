"""Audit a saved payment reference against the two received clarification transcripts."""
import argparse
import json
from pathlib import Path

from .reference_digits import positional_reference


def audit_files(record_path: Path, transcript_path: Path) -> dict:
    audit = {"field": "captured.reference", "decision": "audit_failed",
             "review_required": True, "evidence": []}
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        transcripts = json.loads(transcript_path.read_text(encoding="utf-8"))
        saved = record["captured"]["reference"]
        if saved is not None and not isinstance(saved, str):
            raise ValueError("captured.reference must be a string or null")
        audit["saved_value"] = saved
        readings = transcripts["reference_readings"]
        if not isinstance(readings, list) or not all(isinstance(text, str) for text in readings):
            raise ValueError("reference_readings must be an array of transcript strings")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        audit["reason"] = str(exc)
        return audit

    for turn, quote in enumerate(readings, start=1):
        audit["evidence"].append({"source": f"{transcript_path.name}#/reference_readings/{turn - 1}",
                                  "turn": turn, "quote": quote, "digits": positional_reference(quote)})
    values = [entry["digits"] for entry in audit["evidence"]]
    audit["decision"] = "review_required"
    if len(values) != 2 or None in values:
        audit["reason"] = "Two complete numbered readings are required."
    elif values[0] != values[1]:
        audit["reason"] = "The two clarification turns disagree."
    else:
        audit["confirmed_value"] = values[0]
        if saved == values[0]:
            audit.update(decision="verified", review_required=False,
                         reason="Both clarification turns support the saved reference.")
        elif saved is None:
            audit["reason"] = "The confirmed reference is missing from the saved record."
        else:
            audit["reason"] = "Both clarification turns contradict the saved reference."
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="Saved result.json or a test copy")
    parser.add_argument("--transcripts", type=Path, help="Defaults to transcripts.json beside the record")
    args = parser.parse_args()
    audit = audit_files(args.record, args.transcripts or args.record.with_name("transcripts.json"))
    print(json.dumps(audit, indent=2))
    if audit["decision"] == "audit_failed":
        return 2
    return int(audit["review_required"])


if __name__ == "__main__":
    raise SystemExit(main())
