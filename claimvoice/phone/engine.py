"""Bounded call flow for one synthetic insurer route."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import re
from time import monotonic
from uuid import uuid4

CLAIM_ID = "TEST-48213"
GREETING = (
    f"Hello, this is the EMS billing office calling about claim {CLAIM_ID}. "
    "The service date is March 14, 2026. The patient is Alex Demo."
)
MENU = (("claims", "2"), ("claim status", "1"))
QUESTIONS = {
    "status": "What is the claim status: paid, denied, or pending?",
    "denial_code": "What is the denial code? Please read it as shown.",
    "paid_amount": "What amount was paid in dollars?",
    "payment_reference": "What is the check or electronic payment reference number?",
    "payment_date": "What date was the payment issued? Please give the month, day and year.",
    "reference_number": "What is the reference number for this call?",
    "representative_name": "May I have your name, please?",
}
FIELDS = tuple(QUESTIONS)
STATUS_FIELDS = {
    "paid": ("paid_amount", "payment_reference", "payment_date"),
    "denied": ("denial_code",),
    "pending": (),
}


def required_fields(status):
    return ("status", *STATUS_FIELDS.get(status, ()), "reference_number", "representative_name")


@dataclass(frozen=True)
class Action:
    kind: str
    value: str = ""


def normalize(field_name, text):
    """Parse a representative answer in the sandbox's supported formats."""
    text = text.strip().rstrip(".!?").strip()
    labels = {
        "denial_code": r"denial code",
        "paid_amount": r"(?:amount paid|paid amount)",
        "payment_reference": r"(?:payment reference|eft(?: number)?|check(?: number)?)",
        "payment_date": r"payment date",
        "reference_number": r"(?:(?:call )?reference(?: number)?)",
        "representative_name": r"(?:representative name|my name|name)",
    }
    if field_name in labels:
        text = re.sub(rf"^(?:the )?{labels[field_name]}(?:\s+is\s+|\s*:\s*)", "", text, flags=re.I)
    if field_name == "status":
        match = re.fullmatch(r"(?:(?:the )?claim (?:status is |is )|status\s*:\s*)?(paid|denied|pending)", text, re.I)
        return match[1].lower() if match else None
    if field_name == "paid_amount":
        match = re.fullmatch(r"\$?((?:\d{1,3}(?:,\d{3})+|\d{1,9})(?:\.\d{1,2})?)(?: dollars)?", text, re.I)
        return str(Decimal(match[1].replace(",", "")).quantize(Decimal("0.01"))) if match else None
    if field_name == "payment_date":
        for parser in (date.fromisoformat, *(lambda value, fmt=fmt: datetime.strptime(value, fmt).date()
                                                for fmt in ("%m/%d/%Y", "%B %d, %Y", "%B %d %Y"))):
            try:
                return parser(text).isoformat()
            except ValueError:
                continue
        return None
    if field_name == "representative_name":
        return text if re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,50}", text) else None
    return text.upper() if re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", text) and len(text) <= 36 else None


@dataclass
class Call:
    clock: object = monotonic
    max_seconds: int = 180
    max_hold_seconds: int = 30
    max_prompts: int = 22
    call_id: str = field(default_factory=lambda: uuid4().hex)
    started: float = field(init=False)
    ended_at: float | None = None
    menu_step: int = 0
    ivr_passed: bool = False
    hold_until: float | None = None
    awaiting: str = ""
    retries: int = 0
    outcome: str = "in_progress"
    fields: dict = field(default_factory=lambda: dict.fromkeys(FIELDS))
    evidence: dict = field(default_factory=dict)
    transcript: list = field(default_factory=list)
    latencies_ms: list = field(default_factory=list)
    prompts_seen: int = 0

    def __post_init__(self):
        self.started = self.clock()

    def speak(self, text):
        self.transcript.append({"speaker": "agent", "text": text})
        return Action("speak", text)

    def finish(self, outcome):
        if self.outcome == "in_progress":
            self.outcome = outcome
            self.ended_at = self.clock()
            self.transcript.append({"speaker": "system", "text": outcome})
        return [Action("end", self.outcome)]

    def seconds_remaining(self):
        deadline = self.started + self.max_seconds
        if self.hold_until is not None:
            deadline = min(deadline, self.hold_until)
        return max(0, deadline - self.clock())

    def timeout(self):
        reason = "hold_timeout" if self.hold_until is not None and self.clock() >= self.hold_until else "call_timeout"
        return self.finish(reason)

    def prompt(self, text):
        if self.outcome != "in_progress":
            return []
        before = self.clock()
        actions = self._handle(text)
        if any(action.kind in {"speak", "digits"} for action in actions):
            self.latencies_ms.append(round((self.clock() - before) * 1000, 4))
        return actions

    def _handle(self, text):
        if self.seconds_remaining() == 0:
            return self.timeout()
        self.prompts_seen += 1
        if self.prompts_seen > self.max_prompts:
            return self.finish("turn_limit")
        text = text.strip()[:1000]
        lower = text.lower()
        if re.search(r"\b(?:do not call|stop calling|wrong number)\b", lower):
            self.transcript.append({"speaker": "remote", "text": text})
            return self.finish("stop_requested")
        if not self.ivr_passed:
            self.transcript.append({"speaker": "ivr", "text": text})
            if self.menu_step < len(MENU):
                phrase, digits = MENU[self.menu_step]
                key = {"1": "one", "2": "two"}[digits]
                button = rf"(?:{digits}|{key})"
                if re.search(rf"\bpress\s+{button}\s+for\s+{phrase}\b|\b{phrase}\s*,?\s*press\s+{button}\b", lower):
                    self.menu_step += 1
                    self.retries = 0
                    self.transcript.append({"speaker": "agent", "text": f"DTMF {digits}"})
                    return [Action("digits", digits)]
                self.retries += 1
                return self.finish("ivr_mismatch") if self.retries >= 2 else []
            if re.search(r"\b(?:please hold|please wait|will be with you|transferring your call)\b", lower):
                if self.hold_until is None:
                    self.hold_until = self.clock() + self.max_hold_seconds
                return []
            if not re.search(r"\b(?:representative here|how (?:can|may) i help)\b", lower):
                self.retries += 1
                return self.finish("ivr_mismatch") if self.retries >= 2 else []
            self.ivr_passed = True
            self.hold_until = None
            self.retries = 0
            self.awaiting = "status"
            return [self.speak(f"{GREETING} {QUESTIONS[self.awaiting]}")]

        self.transcript.append({"speaker": "representative", "text": text, "asked_for": self.awaiting})
        if re.search(r"\b(?:please hold|hold please|one moment|please wait)\b", lower):
            if self.hold_until is not None:
                return []
            self.hold_until = self.clock() + self.max_hold_seconds
            return [self.speak("Of course. I will wait.")]
        if self.hold_until is not None:
            if not re.search(r"\b(?:back|thanks for holding|thank you for holding)\b", lower):
                return []
            self.hold_until = None
            return [self.speak(QUESTIONS[self.awaiting])]
        if re.search(r"\b(?:repeat|confirm)\b.*\bclaim (?:number|id)\b|\bclaim (?:number|id) again\b", lower):
            return [self.speak(f"The claim number is {CLAIM_ID}. {QUESTIONS[self.awaiting]}")]

        value = normalize(self.awaiting, text)
        if value is None or re.search(r"\b(?:unknown|unavailable|not available|cannot disclose|don't know)\b", lower):
            self.retries += 1
            if self.retries < 2:
                return [self.speak(f"Could you repeat that? {QUESTIONS[self.awaiting]}")]
        else:
            self.fields[self.awaiting] = value
            self.evidence[self.awaiting] = len(self.transcript) - 1
        self.retries = 0
        required = required_fields(self.fields["status"])
        position = required.index(self.awaiting) + 1
        if position >= len(required):
            return self.finish("answered")
        self.awaiting = required[position]
        return [self.speak(QUESTIONS[self.awaiting])]
