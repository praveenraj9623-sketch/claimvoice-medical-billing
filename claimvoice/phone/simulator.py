"""Synthetic insurer fixtures and a repeatable local benchmark."""

from dataclasses import dataclass
import argparse
import json

from .engine import Call, FIELDS
from .review import build_report, metrics

MENU_PROMPTS = ("For claims, press 2.", "For claim status, press 1.", "Representative here. How can I help?")
PAID = ("The claim is paid.", "125.50 dollars", "EFT number: EFT-771",
        "March 20, 2026", "Reference: QA-111", "My name is Alex Smith.")
DENIED = ("The claim is denied.", "Denial code: CO-16", "Reference: QA-112", "Morgan Reed")
PENDING = ("The claim is pending.", "Reference: QA-113", "Taylor Reed")


def expected(**values):
    return {key: values.get(key) for key in FIELDS}


@dataclass(frozen=True)
class Fixture:
    prompts: tuple
    gold: dict | None = None
    advance_seconds: int = 0
    expected_outcome: str = "answered"


FIXTURES = {
    "Paid after hold": Fixture(
        (*MENU_PROMPTS, "Please hold.", "I am back.", "Could you repeat the claim number?", *PAID),
        expected(status="paid", paid_amount="125.50", payment_reference="EFT-771",
                 payment_date="2026-03-20", reference_number="QA-111", representative_name="Alex Smith"),
        advance_seconds=12,
    ),
    "Denied with a code": Fixture(
        (*MENU_PROMPTS, *DENIED),
        expected(status="denied", denial_code="CO-16", reference_number="QA-112", representative_name="Morgan Reed"),
    ),
    "Pending claim": Fixture(
        (*MENU_PROMPTS, *PENDING),
        expected(status="pending", reference_number="QA-113", representative_name="Taylor Reed"),
    ),
    "Missing payment amount": Fixture(
        (*MENU_PROMPTS, PAID[0], "Unknown", "Unknown", *PAID[2:]),
        expected(status="paid", payment_reference="EFT-771", payment_date="2026-03-20",
                 reference_number="QA-111", representative_name="Alex Smith"),
    ),
    "Menu changed": Fixture(("For payments, press 4.", "For payments, press 4."), expected_outcome="ivr_mismatch"),
    "Hold exceeds limit": Fixture((*MENU_PROMPTS, "Please hold."), advance_seconds=45, expected_outcome="hold_timeout"),
}


def simulate(name):
    from time import monotonic

    fixture = FIXTURES[name]
    extra_seconds = 0

    def clock():
        return monotonic() + extra_seconds

    call = Call(clock=clock)
    for prompt in fixture.prompts:
        call.prompt(prompt)
        if prompt == "Please hold.":
            extra_seconds += fixture.advance_seconds
        if call.outcome != "in_progress":
            break
    if call.outcome == "in_progress":
        if call.seconds_remaining() == 0:
            call.timeout()
        else:
            call.finish("disconnected")
    report = build_report(call, transport="simulator", estimated_cost=0, fixture=name)
    report["expected_fields"] = fixture.gold
    report["expected_outcome"] = fixture.expected_outcome
    return report


def benchmark(repetitions=1):
    return [simulate(name) for _ in range(repetitions) for name in FIXTURES]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--details", action="store_true", help="Include the individual synthetic reports")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    reports = benchmark(args.repeat)
    print(json.dumps({"metrics": metrics(reports), **({"calls": reports} if args.details else {})}, indent=2))


if __name__ == "__main__":
    main()
