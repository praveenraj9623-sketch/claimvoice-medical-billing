"""Decode the two received WAVs in a process isolated from Piper and ONNX Runtime."""
import argparse
import json
import os
from pathlib import Path


def recognize(recordings):
    # CTranslate2 reads backend settings at import. Respect explicit operator overrides.
    os.environ.setdefault("CT2_USE_MKL", "0")
    from faster_whisper import WhisperModel

    model_name = os.environ.get("CLAIMCALL_WHISPER_MODEL", "small.en")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4)
    result = {"model": model_name, "ct2_use_mkl": os.environ["CT2_USE_MKL"]}
    for role, filename in (("caller", "question-heard.wav"), ("insurer", "reply-heard.wav")):
        segments, _ = model.transcribe(str(recordings / filename), language="en", beam_size=5,
                                       temperature=0.0, condition_on_previous_text=False)
        result[role] = " ".join(segment.text.strip() for segment in segments).strip()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(recognize(args.recordings), indent=2), encoding="utf-8")
