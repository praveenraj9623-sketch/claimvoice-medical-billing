import numpy as np

from lab.sip.audio import matches, tone


def test_telephone_marker_and_returned_audio_are_distinct():
    for hz, other in ((660, 980), (980, 660)):
        block = tone(hz, 400)
        assert matches(block, hz)
        assert not matches(block, other)
        assert not matches(bytes(800), hz)
        assert not matches(np.random.default_rng(42).integers(-4000, 4000, size=400, dtype="int16").tobytes(), hz)
