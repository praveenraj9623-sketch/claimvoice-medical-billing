import wave

import numpy as np
import pytest

from lab.sip.audio import matches, prepare_menu_audio, tone, tone_frames


def test_telephone_marker_and_returned_audio_are_distinct():
    for hz, other in ((660, 980), (980, 660)):
        block = tone(hz, 400)
        assert matches(block, hz)
        assert not matches(block, other)
        assert not matches(bytes(800), hz)
        assert not matches(np.random.default_rng(42).integers(-4000, 4000, size=400, dtype="int16").tobytes(), hz)


def test_return_tone_survives_packet_boundaries_and_unaligned_detection():
    frames = list(tone_frames(980, samples_per_frame=160, frame_count=40))
    assert len(frames) == 40
    assert all(len(frame) == 320 for frame in frames)
    audio = b"".join(frames)
    for sample_offset in range(160):
        start = sample_offset * 2
        assert matches(audio[start:start + 800], 980)
        assert matches(audio[start + 800:start + 1600], 980)

@pytest.mark.parametrize("pcm", [
    tone(440, 400) + tone(1520, 400),
    tone(440, 400) + tone(660, 800),
    bytes(800) + tone(1520, 800),
])
def test_incomplete_or_silent_menu_produces_no_asr_input(tmp_path, pcm):
    recording = tmp_path / "received.wav"
    output = tmp_path / "speech.wav"
    with wave.open(str(recording), "wb") as src:
        src.setparams((1, 2, 8000, 0, "NONE", ""))
        src.writeframes(pcm)
    with pytest.raises(ValueError):
        prepare_menu_audio(recording, output)
    assert not output.exists()
