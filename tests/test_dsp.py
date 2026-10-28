# tests/test_dsp.py

"""
Signal pipeline: filters, FFT, vibration metrics, operators.

The module's own demo turned into assertions,
plus every refusal that stands between a caller and a wrong number.
"""

import pytest

np = pytest.importorskip("numpy", reason="dsp needs the [dsp] extra")
pytest.importorskip("scipy", reason="dsp needs the [dsp] extra")

from scipy.signal import get_window, sosfiltfilt, sosfreqz
from xaeian.dsp import Signal, Spectrum, butterworth, filtfilt

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
  assert Signal.sine(50, fs=1000).crest_factor == pytest.approx(np.sqrt(2), rel=1e-3)

def a_band_pass_isolates_the_component_inside_it(accel):
  clean = accel.highpass(10).lowpass(100)
  # only the 50Hz sine survives: rms of amplitude 2 is 2/sqrt(2)
  assert clean.rms == pytest.approx(1.414, abs=0.05)
  assert clean.rms < accel.rms

def a_band_stop_takes_out_the_component_inside_it(accel):
  assert accel.bandstop(40, 60).fft("hann").peak_freq == pytest.approx(200, abs=1)

def the_filters_leave_the_source_untouched(accel):
  before = accel.rms
  accel.highpass(10).lowpass(100)
  assert accel.rms == before

def the_offset_goes_and_the_peak_scales_to_one(accel):
  assert abs(np.mean((accel + 5).detrend().data)) < 1e-9
  assert accel.normalize().peak == pytest.approx(1)
  silence = Signal(np.zeros(8), fs=1)
  assert silence.normalize() == silence

def the_envelope_of_a_sine_is_its_amplitude():
  envelope = Signal.sine(50, fs=1000, amplitude=3).envelope()
  assert np.allclose(envelope.trim(0.1, 0.9).data, 3, atol=0.01)

#------------------------------------------------------------------------------------------ filters

@pytest.mark.parametrize("zero_phase", [True, False])
@pytest.mark.parametrize("method, edges, freq", [
  ("lowpass", (100,), 100),
  ("highpass", (100,), 100),
  ("bandpass", (100, 400), 100),
  ("bandpass", (100, 400), 400),
  ("bandstop", (100, 400), 100),
  ("bandstop", (100, 400), 400),
])
def a_sine_on_an_edge_comes_out_3dB_down(method, edges, freq, zero_phase):
  """-3dB is half the power: the rms of a unit sine, 1/√2, falls to 1/2 either way it is run."""
  sine = Signal.sine(freq, 2, fs=FS)
  out = getattr(sine, method)(*edges, zero_phase=zero_phase).trim(0.5, 1.5)
  assert out.rms == pytest.approx(0.5, rel=0.01)

@pytest.mark.parametrize("zero_phase, passes", [(False, 1), (True, 2)])
@pytest.mark.parametrize("order", [2, 4, 8])
def the_order_is_the_slope_far_from_the_edge(order, zero_phase, passes):
  """20dB a decade for each order, from one pass of it or from a zero-phase pair of half."""
  _, h = sosfreqz(butterworth("lowpass", 1, FS, order, zero_phase=zero_phase), [10, 100], fs=FS)
  gain_dB = 20 * passes * np.log10(np.abs(h))
  assert gain_dB[0] - gain_dB[1] == pytest.approx(20 * order, abs=0.5)

@pytest.mark.parametrize("zero_phase", [True, False])
def a_gap_in_a_signal_stays_a_gap(zero_phase):
  data = np.random.default_rng(0).standard_normal(5000)
  data[2000:2100] = np.nan
  out = Signal(data, fs=FS).lowpass(100, zero_phase=zero_phase).data
  assert np.array_equal(np.isnan(out), np.isnan(data))

def filtfilt_is_sosfiltfilt_a_block_at_a_time(monkeypatch):
  monkeypatch.setattr("xaeian.dsp.BLOCK", 1000) # 25 blocks, a seam every 1000 samples
  sos = butterworth("bandpass", [50, 500], FS)
  noise = np.random.default_rng(0).standard_normal(25_000)
  assert np.allclose(filtfilt(sos, noise), sosfiltfilt(sos, noise), rtol=0, atol=1e-12)

def a_gap_stays_and_each_run_is_filtered_on_its_own():
  sos = butterworth("lowpass", 100, FS)
  data = np.random.default_rng(0).standard_normal(5000)
  data[2000:2100] = np.nan
  out = filtfilt(sos, data)
  assert np.array_equal(np.isnan(out), np.isnan(data))
  assert np.allclose(out[:2000], sosfiltfilt(sos, data[:2000]))
  assert np.allclose(out[2100:], sosfiltfilt(sos, data[2100:]))

def a_run_too_short_to_pad_stays_a_gap():
  data = np.ones(1000)
  data[[400, 410]] = np.nan # 9 samples between two gaps, and the padding takes 9
  out = filtfilt(butterworth("lowpass", 100, FS), data)
  assert np.isnan(out[400:411]).all()
  assert np.isfinite(out[:400]).all() and np.isfinite(out[411:]).all()

def filtfilt_writes_float32_in_place():
  sos = butterworth("lowpass", 100, FS)
  data = np.random.default_rng(0).standard_normal(5000).astype(np.float32)
  expect = sosfiltfilt(sos, data)
  assert filtfilt(sos, data, out=data) is data
  assert np.allclose(data, expect, atol=1e-5)

def raw_adc_counts_filter_as_their_values():
  """Counts at rest near 0 and a ramp near full scale: their odd reflection leaves the type."""
  sos = butterworth("lowpass", 100, FS)
  rest = np.random.default_rng(0).integers(0, 12, 5000).astype(np.uint16)
  ramp = np.linspace(32_000, -32_000, 600).astype(np.int16) # 107 counts a sample off the top
  for counts in (rest, ramp):
    assert np.allclose(filtfilt(sos, counts), sosfiltfilt(sos, counts.astype(np.float64)))

def one_pass_starts_settled_after_a_gap():
  """Gravity on the axis: from rest at 0, every run would ring up to 9.81 first."""
  data = 9.81 + 0.1 * np.random.default_rng(0).standard_normal(4000)
  data[2000:2100] = np.nan
  out = Signal(data, fs=1000).lowpass(100, zero_phase=False).data
  assert abs(out[0] - 9.81) < 0.5 and abs(out[2100] - 9.81) < 0.5

#----------------------------------------------------------------------------------------- spectrum

def the_fft_finds_the_strongest_component(accel):
  spectrum = accel.fft("hann")
  assert isinstance(spectrum, Spectrum)
  assert spectrum.peak_freq == pytest.approx(50, abs=1)

def amplitudes_read_in_the_signals_units_whatever_the_window():
  sig = Signal.sine(50, fs=1000, amplitude=2) + 9.81
  for window in (None, "hann", "hamming"):
    amplitudes = sig.fft(window).amplitudes
    assert amplitudes[0] == pytest.approx(9.81, rel=1e-3)
    assert amplitudes[50] == pytest.approx(2, rel=1e-3)

def an_offset_is_not_the_peak_frequency():
  """Gravity on the axis is the largest bin by far; the vibration is what was asked about."""
  spectrum = (Signal.sine(50, fs=1000, amplitude=0.5) + 9.81).fft()
  assert spectrum.peak_freq == 50 and spectrum.median_freq == 50
  assert spectrum.centroid == pytest.approx(50, abs=1)

def the_centroid_follows_where_the_energy_sits(accel):
  """Broadband noise pulls the centroid high; filtering it away has to pull it back down."""
  wide = accel.fft("hann").centroid
  narrow = accel.highpass(10).lowpass(100).fft("hann").centroid
  assert narrow < wide
  assert narrow == pytest.approx(50, abs=25)
  assert 0 < accel.fft("hann").median_freq < FS / 2

def the_spectrum_turns_back_into_the_signal():
  for n in (999, 1000):
    sig = Signal.noise(n / 1000, fs=1000, seed=1)
    assert np.allclose(sig.fft().to_signal().data, sig.data)

def the_density_integrates_to_the_power_of_the_signal(accel):
  freqs, density = accel.psd(nperseg=1024)
  assert freqs[np.argmax(density)] == pytest.approx(50, abs=10)
  assert np.sum(density) * (freqs[1] - freqs[0]) == pytest.approx(accel.rms ** 2, rel=0.05)

#---------------------------------------------------------------------------------------- operators

def arithmetic_scales_and_subtracts_signals(accel):
  doubled = accel * 2
  assert doubled.rms == pytest.approx(accel.rms * 2, rel=1e-6)
  residual = accel - accel.highpass(10).lowpass(100)
  # what the band-pass removed: the 200Hz component and the noise
  assert 0 < residual.rms < accel.rms
  assert (1 / Signal([2.0, 4.0], fs=1)).data.tolist() == [0.5, 0.25]

def operands_at_another_rate_are_refused(accel):
  with pytest.raises(ValueError):
    accel + Signal(accel.data, fs=FS / 2)

def integration_turns_acceleration_into_velocity(accel):
  velocity = accel.integrate(highpass_Hz=5, units="m/s")
  assert velocity.units == "m/s"
  assert velocity.fs == accel.fs
  assert len(velocity) == len(accel)
  assert accel.integrate().units == accel.derivative().units == "" # never the source's m/s²

def integration_high_passes_3dB_down_at_its_edge():
  """A unit 5Hz sine integrates to amplitude 1/(2π·5), and a 5Hz edge takes 1/√2 of that."""
  velocity = Signal.sine(5, 10, fs=1000).integrate(highpass_Hz=5).trim(2, 8)
  assert velocity.rms == pytest.approx(1 / (2 * np.pi * 5) / 2, rel=0.01)

def numpy_gets_a_writable_copy_without_a_warning(accel, recwarn):
  data = np.asarray(accel)
  data[0] = 0.0
  assert accel.data[0] != 0.0
  assert not recwarn.list

#----------------------------------------------------------------------------------------- refusals

def the_rate_is_never_assumed():
  with pytest.raises(TypeError):
    Signal([1.0, 2.0])
  with pytest.raises(TypeError):
    Signal.sine(50, 0.1, 1000) # a positional rate is refused, not read as something else

def one_channel_per_signal():
  with pytest.raises(ValueError):
    Signal(np.zeros((100, 3)), fs=100) # rows of xyz would interleave into one axis

def a_slice_keeps_the_rate_and_a_step_is_refused():
  sig = Signal(np.arange(10), fs=100)
  assert sig[2:5].fs == 100 and list(sig[2:5]) == [2, 3, 4]
  assert sig[3] == 3.0 and isinstance(sig[3], float)
  with pytest.raises(ValueError):
    sig[::2] # half the samples at the old rate: every frequency would read double

def a_window_is_one_scipy_knows():
  sig = Signal.sine(50, fs=1000)
  assert np.allclose(sig.window("hann").data, sig.data * get_window("hann", len(sig)))
  with pytest.raises(ValueError):
    sig.window("sum") # a numpy function, which would have scaled the signal by its length

def a_zero_phase_order_is_even():
  sig = Signal.sine(50, fs=1000)
  with pytest.raises(ValueError):
    sig.lowpass(100, order=3) # half of it each way would not be whole
  assert len(sig.lowpass(100, order=3, zero_phase=False)) == len(sig) # one pass takes an odd one

def an_order_is_at_least_one():
  sig = Signal.sine(50, fs=1000)
  with pytest.raises(ValueError):
    sig.lowpass(100, order=0, zero_phase=False) # scipy's order 0 passes the samples unfiltered

def an_edge_lies_inside_half_the_rate_low_edge_first():
  sig = Signal.sine(50, fs=1000)
  with pytest.raises(ValueError):
    sig.lowpass(500)
  with pytest.raises(ValueError):
    sig.highpass(0)
  with pytest.raises(ValueError):
    sig.bandpass(300, 200)
  with pytest.raises(ValueError, match="an edge lies"):
    sig.lowpass(float("nan")) # NaN fails every comparison, so only a positive check catches it

def butterworth_takes_only_its_four_kinds():
  """scipy's alias "band" would otherwise get the edge shift of a band-stop."""
  with pytest.raises(ValueError):
    butterworth("band", [100, 400], FS)

def a_band_takes_both_edges():
  with pytest.raises(ValueError):
    butterworth("bandpass", 100, FS)

def filtfilt_takes_one_channel_long_enough_to_pad():
  sos = butterworth("lowpass", 100, FS) # pads 9 samples at each end
  with pytest.raises(ValueError):
    filtfilt(sos, np.zeros((100, 2))) # rows of channels would run as one
  with pytest.raises(ValueError):
    filtfilt(sos, np.ones(9))

def times_land_on_the_nearest_sample():
  sig = Signal(np.arange(100), fs=100)
  assert sig.trim(0.29).data[0] == 29 # 0.29 * 100 is 28.999... in floating point
  assert len(Signal.sine(5, 0.58, fs=100)) == 58

#--------------------------------------------------------------------------------------- generators

def sine_and_noise_build_signals_of_the_asked_length():
  sine = Signal.sine(440, duration=0.5, fs=44100)
  noise = Signal.noise(duration=0.5, fs=44100)
  assert len(sine) == len(noise) == 22050
  assert sine.fft().peak_freq == pytest.approx(440, abs=2)
  mix = sine + noise * 0.1
  assert mix.rms > sine.rms * 0.9

def noise_repeats_with_a_seed():
  assert Signal.noise(fs=100, seed=7) == Signal.noise(fs=100, seed=7)

def adc_counts_become_volts():
  assert np.allclose(Signal.from_adc([0, 2048], fs=1000, bits=12, vref=3.3).data, [0, 1.65])
  bipolar = Signal.from_adc([0, 2048], fs=1000, bits=12, vref=3.3, offset=2048)
  assert np.allclose(bipolar.data, [-1.65, 0]) and bipolar.units == "V"

def accelerometer_counts_become_metres_per_second_squared():
  sig = Signal.from_accel([16384, -16384], fs=100, g_range=2) # half of the ±2g full scale
  assert np.allclose(sig.data, [9.80665, -9.80665]) and sig.units == "m/s²"

def magnitude_combines_axes_that_share_a_rate():
  x, y = Signal([3.0], fs=100), Signal([4.0], fs=100)
  assert Signal.magnitude(x, y).data[0] == 5
  with pytest.raises(ValueError):
    Signal.magnitude(x, Signal([4.0], fs=50))
