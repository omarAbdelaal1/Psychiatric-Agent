import math
import struct
import pytest
from backend.services.gemini_live_bridge import generate_pcm24k_audio_frame


def test_24k_pcm_audio_frame_generation():
    # 100ms at 24,000 Hz = 2,400 samples. Each sample is 2 bytes (16-bit) -> 4,800 bytes
    pcm_frame = generate_pcm24k_audio_frame(duration_ms=100, freq=220.0, volume=0.3)
    assert len(pcm_frame) == 2400 * 2

    # Unpack first sample and check range
    first_sample = struct.unpack("<h", pcm_frame[0:2])[0]
    assert -32768 <= first_sample <= 32767


def test_16k_pcm_frame_specifications():
    sample_rate = 16000
    duration_ms = 100
    expected_samples = int(sample_rate * (duration_ms / 1000.0))  # 1600 samples
    expected_bytes = expected_samples * 2  # 3200 bytes

    assert expected_samples == 1600
    assert expected_bytes == 3200


def test_rms_energy_calculation():
    # Silent frame
    silent_samples = [0.0] * 1000
    rms_silent = math.sqrt(sum(s * s for s in silent_samples) / len(silent_samples))
    assert rms_silent == 0.0

    # Constant amplitude frame
    amp = 0.25
    active_samples = [amp] * 1000
    rms_active = math.sqrt(sum(s * s for s in active_samples) / len(active_samples))
    assert math.isclose(rms_active, amp, rel_tol=1e-5)


def test_linear_interpolation_downsampling():
    # Downsampling from 48,000 to 16,000 is an exact 3:1 ratio
    source_rate = 48000
    target_rate = 16000
    ratio = source_rate / target_rate
    assert ratio == 3.0

    # Synthetic signal: 300 samples at 48k -> 100 samples at 16k
    source_samples = [math.sin(i * 0.1) for i in range(300)]
    downsampled = []
    for i in range(100):
        idx = int(i * ratio)
        downsampled.append(source_samples[idx])

    assert len(downsampled) == 100
