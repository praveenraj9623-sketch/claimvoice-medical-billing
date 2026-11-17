"""Second pass over a call's transcript and captured fields."""

from collections import Counter
from math import ceil
from statistics import mean

from .engine import CLAIM_ID, FIELDS, normalize, required_fields


def check_transcript(fields, evidence, transcript):
    issues = []
    for key in required_fields(fields.get("status")):
        if fields.get(key) is None:
            issues.append(f"missing:{key}")
    for key in FIELDS:
        value = fields.get(key)
        if value is None:
            continue
        index = evidence.get(key)
        if type(index) is not int or not 0 <= index < len(transcript):
            issues.append(f"unsupported:{key}")
            continue
        quote = transcript[index]
        if (quote.get("speaker") != "representative" or quote.get("asked_for") != key
                or normalize(key, quote["text"]) != value):
            issues.append(f"unsupported:{key}")
    return issues


def build_report(call, transport, estimated_cost=None, fixture=None):
    issues = check_transcript(call.fields, call.evidence, call.transcript)
    if call.outcome != "answered":
        issues.insert(0, call.outcome)
    return {
        "call_id": call.call_id,
        "claim_id": CLAIM_ID,
        "transport": transport,
        "fixture": fixture,
        "outcome": call.outcome,
        "ivr_passed": call.ivr_passed,
        "fields": call.fields.copy(),
        "evidence": call.evidence.copy(),
        "transcript": list(call.transcript),
        "checks": issues,
        "review_status": "needs_review" if issues else "evidence_matched",
        "duration_seconds": round((call.ended_at - call.started), 3),
        "app_latency_ms": list(call.latencies_ms),
        "estimated_cost_usd": estimated_cost,
    }


def metrics(reports):
    answered = [r for r in reports if r["outcome"] == "answered"]
    complete = [r for r in answered if not r["checks"]]
    app_ms = sorted(value for r in reports for value in r["app_latency_ms"])
    cost_known = all(r["estimated_cost_usd"] is not None for r in reports)
    gold = [r for r in reports if r.get("expected_fields") is not None]
    checked_fields = sum(len(r["expected_fields"]) for r in gold)
    matched_fields = sum(sum(r["fields"][key] == expected for key, expected in r["expected_fields"].items()) for r in gold)
    return {
        "attempts": len(reports),
        "answered": len(answered),
        "complete": len(complete),
        "ivr_passed": sum(r["ivr_passed"] for r in reports),
        "needs_review": sum(r["review_status"] == "needs_review" for r in reports),
        "app_latency_mean_ms": round(mean(app_ms), 4) if app_ms else None,
        "app_latency_p95_ms": app_ms[ceil(0.95 * len(app_ms)) - 1] if app_ms else None,
        "latency_samples": len(app_ms),
        "fixture_matching_fields": matched_fields,
        "fixture_checked_fields": checked_fields,
        "estimated_cost_per_completed_call": (
            round(sum(r["estimated_cost_usd"] for r in reports) / len(complete), 4)
            if complete and cost_known else None
        ),
        "outcomes": dict(Counter(r["outcome"] for r in reports)),
    }
