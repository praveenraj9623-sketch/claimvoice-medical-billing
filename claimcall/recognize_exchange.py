"""Decode the two received WAVs in a process isolated from Piper and ONNX Runtime."""
import argparse
import json
import os
from pathlib import Path


def recognize(recordings, *, paid=False):
    # CTranslate2 reads backend settings at import. Respect explicit operator overrides.
    os.environ.setdefault("CT2_USE_MKL", "0")
    from faster_whisper import WhisperModel

    model_name = os.environ.get("CLAIMCALL_WHISPER_MODEL", "small.en")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4)
    result = {"model": model_name, "ct2_use_mkl": os.environ["CT2_USE_MKL"]}
    def decode(filename):
        segments, _ = model.transcribe(str(recordings / filename), language="en", beam_size=5,
                                       temperature=0.0, condition_on_previous_text=False)
        return " ".join(segment.text.strip() for segment in segments).strip()
    result["caller"] = decode("question-heard.wav")
    result["insurer"] = decode("reply-heard.wav")
    if paid:
        result["reference_readings"] = [decode(f"reference-{turn}-heard.wav") for turn in (1, 2)]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--paid", action="store_true")
    args = parser.parse_args()
    args.output.write_text(json.dumps(recognize(args.recordings, paid=args.paid), indent=2), encoding="utf-8")
