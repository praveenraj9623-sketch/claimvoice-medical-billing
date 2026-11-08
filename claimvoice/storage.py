"""Reviewed records live only in this browser session until explicitly downloaded."""
import csv
import io
import json
from copy import deepcopy
from datetime import datetime, timezone


def save_reviewed(state, approved):
    if approved is not True or not state.draft:
        raise ValueError("Review and approve a draft before saving.")
    record = deepcopy(state.draft)
    # Idempotent save for a particular draft, while keeping prior revisions intact.
    fingerprint = json.dumps(record, sort_keys=True)
    for saved in state.saved:
        if saved["draft_fingerprint"] == fingerprint:
            return deepcopy(saved)
    record.update(reviewed=True, saved_at=datetime.now(timezone.utc).isoformat(), draft_fingerprint=fingerprint)
    state.saved.append(record)
    return deepcopy(record)


def export_json(records):
    return json.dumps([{k: v for k, v in r.items() if k != "draft_fingerprint"} for r in records], indent=2)


def export_csv(records):
    out = io.StringIO(newline="")
    rows = json.loads(export_json(records))
    if not rows:
        return ""
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            row[key] = value
        writer.writerow(row)
    return out.getvalue()


def transcript(state):
    return json.dumps({"claim_id": state.claim_id, "mode": state.mode, "turns": state.turns}, indent=2)
