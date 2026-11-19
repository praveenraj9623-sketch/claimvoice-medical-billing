import argparse
from pathlib import Path
import wave

import numpy as np

RATE = 8000


def tone(hz, samples):
    phase = 2 * np.pi * hz * np.arange(samples) / RATE
    return (np.sin(phase) * 6000).astype("<i2").tobytes()


def tone_frames(hz, samples_per_frame, frame_count):
    """Split one continuous waveform into PCM frames without resetting its phase."""
    waveform = tone(hz, samples_per_frame * frame_count)
    frame_bytes = samples_per_frame * 2
    for offset in range(0, len(waveform), frame_bytes):
        yield waveform[offset:offset + frame_bytes]


def matches(samples, hz):
    """A dominant sinusoid within a 50 ms block of narrowband audio."""
    signal = np.frombuffer(samples, dtype="<i2").astype(float)
    if len(signal) != 400 or np.max(np.abs(signal)) < 200:
        return False
    phase = 2 * np.pi * hz * np.arange(len(signal)) / RATE
    power = abs(np.dot(signal, np.exp(-1j * phase))) ** 2
    return 2 * power > 0.65 * len(signal) * np.dot(signal, signal)


def prepare_menu_audio(recording, output):
    """Remove the lab's two detected end-marker blocks from a completed SIP capture."""
    with wave.open(str(recording), "rb") as src:
        if (src.getframerate(), src.getnchannels(), src.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Expected an 8 kHz mono PCM16 SIP menu recording")
        pcm = src.readframes(src.getnframes())
    block = 800  # wait_audio tests consecutive 50 ms blocks
    if (len(pcm) <= 2 * block or len(pcm) % block
            or not matches(pcm[-2 * block:-block], 1520)
            or not matches(pcm[-block:], 1520)):
        raise ValueError("Missing the recorded end-of-menu marker")
    speech = pcm[:-2 * block]
    # Drop only whole digital-silence blocks before speech; retain a 150 ms lead.
    start = 0
    while speech[start:start + block] == bytes(block):
        start += block
    if start == len(speech):
        raise ValueError("Received only silence before the end-of-menu marker")
    start = max(0, start - 3 * block)
    temporary = output.with_suffix(".tmp")
    with wave.open(str(temporary), "wb") as dst:
        dst.setparams((1, 2, RATE, 0, "NONE", ""))
        dst.writeframes(speech[start:])
    temporary.replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare a received SIP menu for speech recognition")
    parser.add_argument("recording", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.recording.resolve() == args.output.resolve():
        parser.error("Use a separate output file")
    prepare_menu_audio(args.recording, args.output)
