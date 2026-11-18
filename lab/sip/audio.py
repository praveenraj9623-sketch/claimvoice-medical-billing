import numpy as np

RATE = 8000


def tone(hz, samples):
    phase = 2 * np.pi * hz * np.arange(samples) / RATE
    return (np.sin(phase) * 6000).astype("<i2").tobytes()


def matches(samples, hz):
    """A dominant sinusoid within a 50 ms block of narrowband audio."""
    signal = np.frombuffer(samples, dtype="<i2").astype(float)
    if len(signal) != 400 or np.max(np.abs(signal)) < 200:
        return False
    phase = 2 * np.pi * hz * np.arange(len(signal)) / RATE
    power = abs(np.dot(signal, np.exp(-1j * phase))) ** 2
    return 2 * power > 0.65 * len(signal) * np.dot(signal, signal)
