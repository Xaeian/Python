# tests/test_dsp.py

"""
Signal pipeline: filters, FFT, vibration metrics, operators.

The module's own demo turned into assertions.
`python -m xaeian.dsp` prints the numbers; here they are checked.
"""

import pytest

np = pytest.importorskip("numpy", reason="dsp needs the [dsp] extra")
pytest.importorskip("scipy", reason="dsp needs the [dsp] extra")

from xaeian.dsp import Signal, Spectrum

FS = 10_000

@pytest.fixture
def accel():
  """50Hz at amplitude 2, plus 200Hz at 0.5, plus a little noise. One second of it."""
  rng = np.random.default_rng(0)
  t = np.arange(FS) / FS
  raw = 2 * np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 200 * t)
  raw += 0.3 * rng.standard_normal(len(t))
  return Signal(raw, fs=FS, units="m/s²", label="accel_x")

#------------------------------------------------------------------------------------------ metrics

def rms_matches_the_amplitudes_that_went_in(accel):
  # two sines of amplitude 2 and 0.5 plus noise: sqrt(2²/2 + 0.5²/2 + 0.3²)
  assert accel.rms == pytest.approx(1.49, abs=0.05)
  assert accel.peak > accel.rms
  assert accel.crest_factor == pytest.approx(accel.peak / accel.rms, rel=1e-9)

def a_band_pass_isolates_the_component_inside_it(accel):
  clean = accel.highpass(10).lowpass(100)
  # only the 50Hz sine survives: rms of amplitude 2 is 2/sqrt(2)
  assert clean.rms == pytest.approx(1.414, abs=0.05)
  assert clean.rms < accel.rms

def the_filters_leave_the_source_untouched(accel):
  before = accel.rms
  accel.highpass(10).lowpass(100)
  assert accel.rms == before

#----------------------------------------------------------------------------------------- spectrum

def the_fft_finds_the_strongest_component(accel):
  spectrum = accel.fft("hann")
  assert isinstance(spectrum, Spectrum)
  assert spectrum.peak_freq == pytest.approx(50, abs=1)

def the_centroid_follows_where_the_energy_sits(accel):
  """Broadband noise pulls the centroid high; filtering it away has to pull it back down."""
  wide = accel.fft("hann").centroid
  narrow = accel.highpass(10).lowpass(100).fft("hann").centroid
  assert narrow < wide
  assert narrow == pytest.approx(50, abs=25)
  assert 0 < accel.fft("hann").median_freq < FS / 2

#---------------------------------------------------------------------------------------- operators

def arithmetic_scales_and_subtracts_signals(accel):
  doubled = accel * 2
  assert doubled.rms == pytest.approx(accel.rms * 2, rel=1e-6)
  residual = accel - accel.highpass(10).lowpass(100)
  # what the band-pass removed: the 200Hz component and the noise
  assert 0 < residual.rms < accel.rms

def integration_turns_acceleration_into_velocity(accel):
  velocity = accel.integrate(highpass_Hz=5, units="m/s")
  assert velocity.units == "m/s"
  assert velocity.fs == accel.fs
  assert len(velocity) == len(accel)

#--------------------------------------------------------------------------------------- generators

def sine_and_noise_build_signals_of_the_asked_length():
  sine = Signal.sine(440, duration=0.5, fs=44100)
  noise = Signal.noise(duration=0.5, fs=44100)
  assert len(sine) == len(noise) == 22050
  assert sine.fft().peak_freq == pytest.approx(440, abs=2)
  mix = sine + noise * 0.1
  assert mix.rms > sine.rms * 0.9
