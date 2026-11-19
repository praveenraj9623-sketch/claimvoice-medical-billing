"""Decode received call or menu audio in a process isolated from Piper and ONNX Runtime."""
import argparse
import json
import os
import sys
from importlib import metadata
from time import monotonic, sleep
from pathlib import Path


def load_model(*, cached_only=False):
    os.environ.setdefault("CT2_USE_MKL", "0")
    from faster_whisper import WhisperModel

    name = os.environ.get("CLAIMCALL_WHISPER_MODEL", "small.en")
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=4,
                         local_files_only=cached_only)
    return name, model


def decode(model, path):
    segments, _ = model.transcribe(str(path), language="en", beam_size=5, temperature=0.0,
                                   condition_on_previous_text=False)
    return " ".join(segment.text.strip() for segment in segments).strip()


def recognize_menu(directory):
    # Emit before any native import so fatal loader errors still have diagnostics.
    print(json.dumps({"python": sys.executable, "cwd": os.getcwd(),
                      "ct2_use_mkl": os.environ.get("CT2_USE_MKL", "0"),
                      "ctranslate2": metadata.version("ctranslate2"),
                      "ld_library_path": os.environ.get("LD_LIBRARY_PATH"),
                      "ld_preload": os.environ.get("LD_PRELOAD")}), flush=True)
    name, model = load_model(cached_only=True)
    (directory / "ready").touch()
    wav = directory / "menu-speech.wav"
    deadline = monotonic() + 120
    while not wav.exists():
        if monotonic() >= deadline:
            raise TimeoutError("No complete received menu WAV")
        sleep(0.1)
    return {"transcript": decode(model, wav), "model": name}


def recognize(recordings, *, paid=False):
    model_name, model = load_model()
    result = {"model": model_name, "ct2_use_mkl": os.environ["CT2_USE_MKL"]}
    result["caller"] = decode(model, recordings / "question-heard.wav")
    result["insurer"] = decode(model, recordings / "reply-heard.wav")
    if paid:
        result["reference_readings"] = [decode(model, recordings / f"reference-{turn}-heard.wav") for turn in (1, 2)]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path)
    parser.add_argument("output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--paid", action="store_true")
    mode.add_argument("--menu", action="store_true")
    args = parser.parse_args()
    result = recognize_menu(args.recordings) if args.menu else recognize(args.recordings, paid=args.paid)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(args.output)
