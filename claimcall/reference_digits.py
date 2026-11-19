"""Parse explicitly numbered digits in a spoken reference confirmation."""
import re

DIGITS = "zero one two three four five six seven eight nine".split()
POSITIONS = "first second third fourth fifth sixth seventh eighth ninth tenth".split()


ORDINALS = "1st 2nd 3rd 4th 5th 6th 7th 8th 9th 10th".split()
CARDINALS = DIGITS[1:] + ["ten"]


def positional_reference(text: str) -> str | None:
    """Accept only a complete sequence of explicitly numbered single digits."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    digits = []
    while words and len(digits) < len(POSITIONS):
        index = len(digits)
        label = words.pop(0)
        if label == "position":
            if not words or words.pop(0) not in (CARDINALS[index], str(index + 1)):
                return None
        elif label in (POSITIONS[index], ORDINALS[index]):
            if words[:1] == ["digit"]:
                words.pop(0)
        else:
            return None
        if words[:1] == ["is"]:
            words.pop(0)
        if not words:
            return None
        token = words.pop(0)
        if token in DIGITS:
            digits.append(str(DIGITS.index(token)))
        elif re.fullmatch(r"[0-9]", token):
            digits.append(token)
        else:
            return None
    return "".join(digits) if digits and not words else None
