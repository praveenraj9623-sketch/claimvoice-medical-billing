import numpy as np

from lab.sip.audio import matches, tone, tone_frames


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
