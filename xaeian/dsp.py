# xaeian/dsp.py

"""
Signal processing for embedded sensor data.

Immutable `Signal` wraps one channel of samples with its sample rate.
Every transform returns a new Signal, so calls chain: `sig.highpass(10).integrate().rms`.
What would come out wrong is refused instead: a 2-D array, a stepped slice, an unknown window.

Requires: `pip install xaeian[dsp]`

Example:
  >>> from xaeian.dsp import Signal
  >>> sig = Signal.sine(50, duration=0.1, fs=1000)
  >>> sig.lowpass(100).rms
  >>> sig * 2 + sig
"""

from __future__ import annotations
import operator
from typing import Iterator
from .extras import MissingExtra, absent

__extras__ = ("dsp", ["scipy", "numpy"])

try:
  import numpy as np
  from scipy.signal import (
    butter, sosfilt, sosfiltfilt,
    detrend as _detrend, get_window, hilbert, welch, windows,
  )
  from scipy.integrate import cumulative_trapezoid
except ModuleNotFoundError as e:
  if not absent(e, "scipy", "numpy"): raise
  raise MissingExtra("Install with: pip install xaeian[dsp]") from e

#----------------------------------------------------------------------------------------- Spectrum

class Spectrum:
  """
  One-sided FFT of a Signal: frequency bins in Hz, complex coefficients, the source's rate.

  `gain` is the sum of the window the samples went through, their count without one,
  so `amplitudes` reads in the signal's units whichever window was used.
  The frequency descriptors leave DC out: an offset is not a frequency.
  """
  __slots__ = ("freqs", "complex", "fs", "gain")

  def __init__(self, freqs:np.ndarray, complex:np.ndarray, fs:float, gain:float) -> None:
    self.freqs = freqs
    self.complex = complex
    self.fs = fs
    self.gain = gain

  @property
  def _n(self) -> int:
    """Sample count of the signal behind the bins."""
    if len(self.freqs) < 2: return 1
    return round(self.fs / (self.freqs[1] - self.freqs[0]))

  @property
  def amplitudes(self) -> np.ndarray:
    """Amplitude per bin in the signal's units: a sine of amplitude 2 reads 2 at its bin."""
    amp = 2 * np.abs(self.complex) / self.gain
    amp[0] /= 2 # DC has no negative-frequency twin folded in
    if self._n % 2 == 0: amp[-1] /= 2 # nor has the Nyquist bin of an even count
    return amp

  @property
  def power(self) -> np.ndarray:
    """Power spectrum |X|², unscaled."""
    return np.abs(self.complex) ** 2

  @property
  def phase(self) -> np.ndarray:
    """Phase spectrum in radians."""
    return np.angle(self.complex)

  @property
  def peak_freq(self) -> float:
    """Frequency of the strongest component."""
    if len(self.freqs) < 2: return 0.0
    return float(self.freqs[1 + np.argmax(self.amplitudes[1:])])

  @property
  def centroid(self) -> float:
    """Spectral centroid: amplitude-weighted mean frequency."""
    amp = self.amplitudes[1:]
    total = np.sum(amp)
    if total == 0: return 0.0
    return float(np.sum(self.freqs[1:] * amp) / total)

  @property
  def median_freq(self) -> float:
    """Frequency splitting the power spectrum into equal halves."""
    cumpower = np.cumsum(self.power[1:])
    if cumpower.size == 0 or cumpower[-1] == 0: return 0.0
    idx = np.searchsorted(cumpower, cumpower[-1] / 2)
    return float(self.freqs[1 + min(idx, cumpower.size - 1)])

  def to_signal(self) -> Signal:
    """Inverse FFT back to the time domain, the window still in it when one was applied."""
    return Signal(np.fft.irfft(self.complex, n=self._n), self.fs)

  def __repr__(self) -> str:
    return (f"Spectrum(bins={len(self.freqs)}, "
      f"range=0-{self.freqs[-1]:g}Hz, peak={self.peak_freq:g}Hz)")

#------------------------------------------------------------------------------------------- Signal

class Signal:
  """
  Immutable signal: one channel of samples, copied in, `fs` in Hz
  and `units` free-form ("g", "m/s", "V").

  Arithmetic is elementwise; Signal-Signal operands must share fs and length.
  """
  __slots__ = ("_data", "_fs", "_units", "_label")

  def __init__(self, data, fs:float, units:str="", label:str="") -> None:
    data = np.array(data, dtype=np.float64)
    if data.ndim != 1: raise ValueError(f"one channel per Signal, got shape {data.shape}")
    data.flags.writeable = False
    self._data = data
    self._fs = float(fs)
    self._units = units
    self._label = label

  def _new(self, data=None, fs=None, units=None, label=None) -> Signal:
    """New Signal, each unset field inherited from this one."""
    return self.__class__(
      data if data is not None else self._data,
      fs=fs if fs is not None else self._fs,
      units=units if units is not None else self._units,
      label=label if label is not None else self._label,
    )

  #------------------------------------------------------------------------------------- Properties

  @property
  def data(self) -> np.ndarray:
    """Raw sample array (read-only view)."""
    return self._data.view()

  @property
  def fs(self) -> float:
    """Sample rate in Hz."""
    return self._fs

  @property
  def dt(self) -> float:
    """Sample period in seconds."""
    return 1.0 / self._fs

  @property
  def units(self) -> str:
    """Unit of the sample values."""
    return self._units

  @property
  def label(self) -> str:
    """Free-form name, inherited by every derived Signal."""
    return self._label

  @property
  def duration(self) -> float:
    """Duration in seconds."""
    return len(self._data) / self._fs

  @property
  def times(self) -> np.ndarray:
    """Time axis in seconds."""
    return np.arange(len(self._data)) / self._fs

  #------------------------------------------------------------------------------ Vibration metrics

  @property
  def rms(self) -> float:
    """Root mean square."""
    return float(np.sqrt(np.mean(self._data ** 2)))

  @property
  def peak(self) -> float:
    """Peak absolute value."""
    return float(np.max(np.abs(self._data)))

  @property
  def peak_to_peak(self) -> float:
    """Peak-to-peak amplitude."""
    return float(np.ptp(self._data))

  @property
  def crest_factor(self) -> float:
    """Peak over rms; a pure sine gives √2."""
    r = self.rms
    return float(self.peak / r) if r > 0 else 0.0

  #-------------------------------------------------------------------------------------- Operators

  def _check_compat(self, other:Signal):
    if self._fs != other._fs: raise ValueError(f"Sample rates differ: {self._fs} vs {other._fs}")
    if len(self._data) != len(other._data):
      raise ValueError(f"Lengths differ: {len(self._data)} vs {len(other._data)}")

  def _binop(self, op, other) -> Signal:
    if isinstance(other, Signal):
      self._check_compat(other)
      return self._new(op(self._data, other._data))
    return self._new(op(self._data, np.asarray(other)))

  def __add__(self, other) -> Signal:
    return self._binop(operator.add, other)

  def __radd__(self, other) -> Signal:
    return self.__add__(other)

  def __sub__(self, other) -> Signal:
    return self._binop(operator.sub, other)

  def __rsub__(self, other) -> Signal:
    return self._new(np.asarray(other) - self._data)

  def __mul__(self, other) -> Signal:
    return self._binop(operator.mul, other)

  def __rmul__(self, other) -> Signal:
    return self.__mul__(other)

  def __truediv__(self, other) -> Signal:
    return self._binop(operator.truediv, other)

  def __rtruediv__(self, other) -> Signal:
    return self._new(np.asarray(other) / self._data)

  def __neg__(self) -> Signal:
    return self._new(-self._data)

  def __abs__(self) -> Signal:
    return self._new(np.abs(self._data))

  def __pow__(self, exp) -> Signal:
    return self._new(self._data ** exp)

  #------------------------------------------------------------------------------- Indexing / numpy

  def __len__(self) -> int:
    return len(self._data)

  def __getitem__(self, key) -> Signal|float:
    """
    A slice is a Signal at the same rate, an index one sample.
    A step would drop samples but keep `fs`, so it is refused.
    """
    if not isinstance(key, slice): return float(self._data[key])
    if key.step not in (None, 1): raise ValueError("a step drops samples but keeps fs")
    return self._new(self._data[key])

  def __array__(self, dtype=None, copy=None) -> np.ndarray:
    """NumPy interop: always a fresh array, never the read-only buffer."""
    if copy is False: raise ValueError("a Signal hands out copies only")
    return self._data.astype(dtype or np.float64)

  def __iter__(self) -> Iterator[float]:
    return iter(self._data)

  #---------------------------------------------------------------------------------- Filters (SOS)

  def _sos_filter(self, Wn, btype:str, order:int, zero_phase:bool) -> Signal:
    sos = butter(order, Wn, btype, fs=self._fs, output="sos")
    filt = sosfiltfilt if zero_phase else sosfilt
    return self._new(filt(sos, self._data))

  def lowpass(self, cutoff_Hz:float, order:int=4, zero_phase:bool=True) -> Signal:
    """Butterworth low-pass. `zero_phase` filters forward and back: no phase shift."""
    return self._sos_filter(cutoff_Hz, "low", order, zero_phase)

  def highpass(self, cutoff_Hz:float, order:int=4, zero_phase:bool=True) -> Signal:
    """Butterworth high-pass."""
    return self._sos_filter(cutoff_Hz, "high", order, zero_phase)

  def bandpass(self, low_Hz:float, high_Hz:float, order:int=4, zero_phase:bool=True) -> Signal:
    """Butterworth band-pass."""
    return self._sos_filter([low_Hz, high_Hz], "band", order, zero_phase)

  def bandstop(self, low_Hz:float, high_Hz:float, order:int=4, zero_phase:bool=True) -> Signal:
    """Butterworth band-stop (notch)."""
    return self._sos_filter([low_Hz, high_Hz], "bandstop", order, zero_phase)

  #------------------------------------------------------------------------------------- Transforms

  def detrend(self, type:str="constant") -> Signal:
    """Remove trend: "constant" (DC offset) or "linear"."""
    return self._new(_detrend(self._data, type=type))

  def normalize(self) -> Signal:
    """Scale into [-1, 1] by the peak; silence stays silence."""
    peak = self.peak
    return self._new(self._data / peak) if peak else self

  def window(self, name:str="hann") -> Signal:
    """Samples times a window `scipy.signal.get_window` knows, periodic as an FFT wants."""
    return self._new(self._data * get_window(name, len(self._data)))

  def trim(self, start_s:float=0, end_s:float|None=None) -> Signal:
    """Trim by time in seconds, to the nearest sample."""
    i0 = round(start_s * self._fs)
    i1 = round(end_s * self._fs) if end_s is not None else len(self._data)
    return self._new(self._data[i0:i1])

  def integrate(self, highpass_Hz:float=1.0, units:str="") -> Signal:
    """
    Integrate signal (acceleration → velocity → displacement).

    DC removal, Tukey window, high-pass and final detrend suppress the drift
    that plain cumulative integration accumulates.
    The window tapers the first and last 2.5% of the samples, so metrics read low there.
    `units` names the result's unit; left out, it stays empty rather than inherit a wrong one.
    """
    data = self._data - np.mean(self._data)
    data *= windows.tukey(len(data), alpha=0.05)
    sos = butter(4, highpass_Hz, "high", fs=self._fs, output="sos")
    data = sosfiltfilt(sos, data)
    result = cumulative_trapezoid(data, dx=1 / self._fs, initial=0)
    result = _detrend(result, type="linear")
    return self._new(result, units=units)

  def derivative(self, units:str="") -> Signal:
    """Numerical derivative, same length as input; `units` as in `integrate`."""
    return self._new(np.gradient(self._data, 1 / self._fs), units=units)

  def envelope(self) -> Signal:
    """Amplitude envelope via Hilbert transform."""
    analytic = hilbert(self._data)
    return self._new(np.abs(analytic))

  #--------------------------------------------------------------------------------------- Spectral

  def fft(self, window:str|None=None) -> Spectrum:
    """One-sided FFT, `window` applied first when given."""
    n = len(self._data)
    w = get_window(window, n) if window else np.ones(n)
    freqs = np.fft.rfftfreq(n, d=1 / self._fs)
    return Spectrum(freqs, np.fft.rfft(self._data * w), self._fs, gain=float(np.sum(w)))

  def psd(self, nperseg:int=256, window:str="hann") -> tuple[np.ndarray, np.ndarray]:
    """Power spectral density via Welch's method → (frequencies_Hz, density in units²/Hz)."""
    return welch(self._data, fs=self._fs, nperseg=min(nperseg, len(self._data)), window=window)

  #-------------------------------------------------------------------------------------- Factories

  @classmethod
  def from_adc(cls, raw, fs:float, bits:int, vref:float, offset:int=0, label:str="") -> Signal:
    """
    Signal in volts from raw ADC counts: `(raw - offset) * vref / 2 ** bits`.

    A bipolar input biased at mid-rail passes its mid-scale, `2 ** (bits - 1)`, as `offset`.
    Any other scale is one line: `Signal((raw - offset) * scale, fs, units="A")`.
    """
    volts = (np.asarray(raw, dtype=np.float64) - offset) * vref / 2 ** bits
    return cls(volts, fs, units="V", label=label)

  @classmethod
  def from_accel(cls, raw, fs:float, bits:int=16, *, g_range:float, label:str="") -> Signal:
    """
    Signal in m/s² from signed accelerometer counts (IMU int16, zero-centered).

    `g_range` is the configured full scale: ±2g → 2, ±8g → 8.
    """
    scale = g_range * 9.80665 / 2 ** (bits - 1) # standard gravity
    return cls(np.asarray(raw, dtype=np.float64) * scale, fs, units="m/s²", label=label)

  @classmethod
  def magnitude(cls, *signals:Signal) -> Signal:
    """Per-sample vector magnitude across axes, which must share fs and length."""
    if not signals: raise ValueError("Need at least one signal")
    for s in signals[1:]: signals[0]._check_compat(s)
    return signals[0]._new(np.sqrt(sum(s._data ** 2 for s in signals)), label="magnitude")

  @classmethod
  def sine(
    cls,
    freq_Hz:float,
    duration:float = 1.0,
    *,
    fs:float,
    amplitude:float = 1.0,
    phase:float = 0,
  ) -> Signal:
    """Sine wave test signal, `phase` in radians."""
    t = np.arange(round(fs * duration)) / fs
    return cls(amplitude * np.sin(2 * np.pi * freq_Hz * t + phase), fs)

  @classmethod
  def noise(
    cls,
    duration:float = 1.0,
    *,
    fs:float,
    amplitude:float = 1.0,
    seed:int|None = None,
  ) -> Signal:
    """White noise test signal; `amplitude` is the standard deviation, `seed` repeats it."""
    rng = np.random.default_rng(seed)
    return cls(amplitude * rng.standard_normal(round(fs * duration)), fs)

  #---------------------------------------------------------------------------------------- Special

  def __repr__(self) -> str:
    parts = [f"n={len(self._data)}", f"fs={self._fs:g}Hz",
      f"duration={self.duration:g}s", f"rms={self.rms:.4g}"]
    if self._units: parts.append(f"units='{self._units}'")
    if self._label: parts.append(f"label='{self._label}'")
    return f"Signal({", ".join(parts)})"

  def __eq__(self, other) -> bool:
    if not isinstance(other, Signal): return NotImplemented
    return self._fs == other._fs and np.array_equal(self._data, other._data)

#--------------------------------------------------------------------------------------------- Demo

def demo() -> None:
  """Signal processing demo: filter, FFT, vibration metrics."""
  rng = np.random.default_rng(0)
  t = np.arange(10000) / 10000
  raw = 2 * np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 200 * t)
  raw += 0.3 * rng.standard_normal(len(t))
  sig = Signal(raw, fs=10000, units="m/s²", label="accel_x")
  print("Original:", sig)
  print(f"  RMS={sig.rms:.4f} peak={sig.peak:.4f} crest={sig.crest_factor:.2f}")
  print()
  clean = sig.highpass(10).lowpass(100)
  print("After BP 10-100Hz:", clean)
  print(f"  RMS={clean.rms:.4f} (50Hz component isolated)")
  print()
  sp = sig.fft("hann")
  print("Spectrum:", sp)
  print(f"  Peak: {sp.peak_freq:.1f}Hz at {sp.amplitudes.max():.2f}{sig.units}")
  print(f"  Centroid: {sp.centroid:.1f}Hz")
  print(f"  Median: {sp.median_freq:.1f}Hz")
  print()
  doubled = sig * 2
  diff = sig - clean
  print(f"sig * 2: RMS={doubled.rms:.4f} (2x original)")
  print(f"sig - clean: RMS={diff.rms:.4f} (residual noise + 200Hz)")
  print()
  vel = sig.integrate(highpass_Hz=5, units="m/s")
  print("Velocity:", vel)
  print()
  sine = Signal.sine(440, duration=0.5, fs=44100)
  noise = Signal.noise(duration=0.5, fs=44100, seed=0)
  mix = sine + noise * 0.1
  print("Sine:", sine)
  print("Noise:", noise)
  print("Mix:", mix)

if __name__ == "__main__":
  demo()
