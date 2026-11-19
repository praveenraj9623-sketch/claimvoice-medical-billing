"""Judge a control or changed-menu test from the caller and receiver artifacts."""
import argparse
import json
from pathlib import Path
import re


def passed(case, result, insurer_log):
    digits = re.findall(r"CLAIMCALL_MENU_EXIT digit=\[([0-9*#]*)\]", insurer_log)
    if case == "menu-control":
        return (result.get("decision") == "authorized" and result.get("heard_digit") == "2"
                and result.get("sent_digits") == ["2"] and set(digits) == {"2"})
    if case == "menu-changed":
        return (result.get("decision") == "review_required" and result.get("reason") == "menu_changed"
                and result.get("heard_digit") == "3" and result.get("sent_digits") == [] and set(digits) == {""})
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=("menu-control", "menu-changed"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = json.loads((args.directory / "menu-result.json").read_text())
    ok = passed(args.case, result, (args.directory / "insurer.log").read_text())
    print(f"{args.case}: {'PASS' if ok else 'FAIL'} ({args.directory})")
    raise SystemExit(0 if ok else 1)
