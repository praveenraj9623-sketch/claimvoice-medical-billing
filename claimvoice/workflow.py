from .claims import lookup
from .groq_client import ServiceError
from .state import Conversation
from .tools import execute, FIELDS


def start(claim_id, mode):
    lookup(claim_id)
    state = Conversation(claim_id, mode)
    execute(state, "lookup_claim", {"claim_id": claim_id})
    state.add("assistant", f"Hello, I am the billing assistant following up on synthetic ambulance claim {claim_id}. Could you report its status, any reference number, requested documents and next steps? Unknown details can stay unknown.")
    return state


def scripted_reply(state):
    turn = state.turns[-1]
    text = turn["content"]
    if text.strip().lower() == "end session":
        execute(state, "end_session", {"supporting_turn_id": turn["id"]})
        return "Scripted walkthrough ended. You can still review and save your draft."
    if text.strip().lower() == "human handoff":
        execute(state, "flag_handoff", {"reason": text, "supporting_turn_id": turn["id"]})
        return "Human review flagged. This demo does not transfer a call."
    labels = {"Status": "reported_status", "Reference": "reference_number", "Documents": "requested_documents", "Next action": "next_action", "Follow-up date": "follow_up_date"}
    values = {f: None for f in FIELDS}
    ids = []
    for t in state.turns:
        if t["role"] != "user":
            continue
        used = False
        for part in t["content"].split(";"):
            label, sep, value = part.strip().partition(":")
            if sep and label in labels and value.strip():
                values[labels[label]] = value.strip()
                used = True
        if used:
            ids.append(t["id"])
    if not ids:
        return "Scripted mode reads labelled facts only. Use the scenario example, or type Status: your reported status; Reference: your reference. You can also type human handoff or end session. No AI request was made."
    result = execute(state, "record_draft", {**values, "supporting_turn_ids": ids})
    return ("Scripted draft prepared from your labelled statements. Review the quoted facts below; unknown fields remain null. Nothing has been submitted or verified." if result["ok"] else "The draft could not be updated. Check tool activity; use an explicit YYYY-MM-DD date or omit the date.")


def submit(state, text, request_id, client=None):
    if state.ended:
        raise ValueError("Session ended. Start a new session.")
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError("Enter a reply of 1–8000 characters.")
    if not state.reserve(request_id):
        return False
    state.add("user", text.strip())
    return respond(state, client)


def respond(state, client=None):
    state.error = ""
    try:
        reply = client.reply(state) if state.mode == "Live Groq" else scripted_reply(state)
        state.add("assistant", reply)
        return True
    except ServiceError as exc:
        state.error = str(exc)
        return False
