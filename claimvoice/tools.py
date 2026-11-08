"""Allowlisted tools with transcript grounding, shared by scripted and live modes."""
from datetime import date
from copy import deepcopy
from .claims import lookup

FIELDS = ("reported_status", "reference_number", "requested_documents", "next_action", "follow_up_date")
props = {k: {"type": ["string", "null"], "description": "Exact substring supplied by the representative, or null if unknown."} for k in FIELDS}
props["supporting_turn_ids"] = {"type": "array", "items": {"type": "integer"}, "description": "Representative turn IDs supporting every non-null value."}


def schema(name, description, properties):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}}


SCHEMAS = [
    schema("lookup_claim", "Look up only the selected synthetic claim.", {"claim_id": {"type": "string"}}),
    schema("record_draft", "Replace the draft with representative-supplied facts. Never infer missing facts. This does not save a final record.", props),
    schema("flag_handoff", "Flag a human review request; no actual transfer occurs.", {"reason": {"type": "string"}, "supporting_turn_id": {"type": "integer"}}),
    schema("end_session", "End this browser demonstration when the representative requests it.", {"supporting_turn_id": {"type": "integer"}}),
]


def execute(state, name, args):
    try:
        definition = next((s["function"] for s in SCHEMAS if s["function"]["name"] == name), None)
        if definition is None:
            raise ValueError("Tool is not allowed.")
        if not isinstance(args, dict) or set(args) != set(definition["parameters"]["properties"]):
            raise ValueError("Arguments must contain exactly the required fields.")
        if state.ended:
            raise ValueError("Session has ended; start a new session.")
        users = {t["id"]: t for t in state.turns if t["role"] == "user"}
        if name == "lookup_claim":
            if args["claim_id"] != state.claim_id:
                raise ValueError("Only the selected claim can be accessed.")
            result = lookup(args["claim_id"])
        elif name == "record_draft":
            ids = args["supporting_turn_ids"]
            if not isinstance(ids, list) or not ids or any(type(i) is not int or i not in users for i in ids):
                raise ValueError("Supply existing representative turn IDs.")
            evidence = [users[i] for i in dict.fromkeys(ids)]
            for key in FIELDS:
                value = args[key]
                if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 2000 or not any(value in t["content"] for t in evidence)):
                    raise ValueError(f"{key} must be an exact representative quote or null.")
            if args["follow_up_date"] is not None:
                try:
                    date.fromisoformat(args["follow_up_date"])
                except ValueError:
                    raise ValueError("Follow-up date must be YYYY-MM-DD or null.") from None
                if len(args["follow_up_date"]) != 10:
                    raise ValueError("Follow-up date must be YYYY-MM-DD or null.")
            state.draft = {"claim_id": state.claim_id, **deepcopy(args), "supporting_transcript_turns": deepcopy(evidence)}
            result = {"draft": deepcopy(state.draft), "requires_human_review": True}
        else:
            tid = args["supporting_turn_id"]
            if type(tid) is not int or tid not in users:
                raise ValueError("Supply an existing representative turn ID.")
            if name == "flag_handoff":
                reason = args["reason"]
                if not isinstance(reason, str) or not reason.strip() or reason not in users[tid]["content"]:
                    raise ValueError("Handoff reason must quote the representative.")
                state.handoff = True
                result = {"human_review_flagged": True, "reason": reason, "transferred": False}
            else:
                state.ended = True
                result = {"session_ended": True}
        response = {"ok": True, "result": result}
    except ValueError as exc:
        # Validation messages are fixed strings; never echo arbitrary model arguments.
        response = {"ok": False, "error": str(exc)}
    except (TypeError, KeyError):
        response = {"ok": False, "error": "Invalid argument types. Use the tool schema and selected claim."}
    state.activity.append({"tool": name if name in {s['function']['name'] for s in SCHEMAS} else "unknown", **deepcopy(response)})
    return response
