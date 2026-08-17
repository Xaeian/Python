# xaeian/dsp.py

"""
Signal processing for embedded sensor data.

Immutable `Signal` wraps a numpy array with its sample rate. Every transform returns a new
Signal, so calls chain: `sig.highpass(10).integrate().rms`.

Requires: `pip install xaeian[dsp]`

Example:
  >>> from xaeian.dsp import Signal
  >>> sig = Signal.sine(50, duration=0.1, fs=1000)
  >>> sig.lowpass(100).rms
  >>> sig * 2 + sig
"""

from __future__ import annotations
import operator

__extras__ = ("dsp", ["scipy", "numpy"])

try:
  import numpy as np
  from scipy.signal import (
    butter, sosfilt, sosfiltfilt, sosfreqz,
    detrend as _detrend, hilbert, welch, windows,
  )
  from scipy.integrate import cumulative_trapezoid
except ImportError as e:
  raise ImportError("Install with: pip install xaeian[dsp]  (scipy + numpy)") from e

#----------------------------------------------------------------------------------------- Spectrum

class Spectrum:
  """FFT result: frequency bins in Hz, complex coefficients, sample rate of the source."""
  __slots__ = ("freqs", "complex", "fs")

  def __init__(self, freqs:np.ndarray, complex:np.ndarray, fs:float):
    self.freqs = freqs
    self.complex = complex
    self.fs = fs

  @property
  def magnitudes(self) -> np.ndarray:
    """Amplitude spectrum |X|, unscaled: multiply by 2/N for physical amplitude."""
    return np.abs(self.complex)

  @property
  def power(self) -> np.ndarray:
    """Power spectrum |X|²."""
    return np.abs(self.complex) ** 2

  @property
  def phase(self) -> np.ndarray:
    """Phase spectrum in radians."""
    return np.angle(self.complex)

  @property
  def peak_freq(self) -> float:
    """Frequency of highest amplitude bin."""
    return float(self.freqs[np.argmax(self.magnitudes)])

  @property
  def centroid(self) -> float:
    """Spectral centroid: amplitude-weighted mean frequency."""
    mag = self.magnitudes
    total = np.sum(mag)
    if total == 0: return 0.0
    return float(np.sum(self.freqs * mag) / total)

  @property
  def median_freq(self) -> float:
    """Frequency splitting the power spectrum into equal halves."""
    cumpower = np.cumsum(self.power)
    if cumpower[-1] == 0: return 0.0
    idx = np.searchsorted(cumpower, cumpower[-1] / 2)
    return float(self.freqs[min(idx, len(self.freqs) - 1)])

  def to_signal(self) -> Signal:
    """Inverse FFT back to time domain."""
    n = round(self.fs / (self.freqs[1] - self.freqs[0])) if len(self.freqs) > 1 else 1
    data = np.fft.irfft(self.complex, n=n)
    return Signal(data, fs=self.fs)

  def __repr__(self):
    return (f"Spectrum(bins={len(self.freqs)}, "
      f"range=0-{self.freqs[-1]:.0f}Hz, peak={self.peak_freq:.1f}Hz)")

#------------------------------------------------------------------------------------------- Signal

class Signal:
  """
  Immutable signal container: input is copied and flattened to 1-D, `fs` in Hz,
  `units` free-form ("g", "m/s", "V").

  Arithmetic is elementwise; Signal-Signal operands must share fs and length.
  """
  __slots__ = ("_data", "_fs", "_units", "_label")

  def __init__(self, data, fs:float=1000, units:str="", label:str=""):
    self._data = np.array(data, dtype=np.float64, copy=True).flatten()
    self._data.flags.writeable = False
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
  def samples(self) -> int:
    """Number of samples."""
    return len(self._data)

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
    """Crest factor (peak / rms). > 3.0 may indicate bearing faults."""
    r = self.rms
    return float(self.peak / r) if r > 0 else 0.0

  #-------------------------------------------------------------------------------------- Operators

  def _check_compat(self, other:Signal):
    if self._fs != other._fs:
      raise ValueError(f"Sample rates differ: {self._fs} vs {other._fs}")
    if len(self._data) != len(other._data):
      raise ValueError(f"Lengths differ: {len(self._data)} vs {len(other._data)}")

  def _binop(self, op, other) -> Signal:
    if isinstance(other, Signal):
      self._check_compat(other)
      return self._new(op(self._data, other._data))
    return self._new(op(self._data, np.asarray(other)))

  def __add__(self, other):
    return self._binop(operator.add, other)

  def __radd__(self, other):
    return self.__add__(other)

  def __sub__(self, other):
    return self._binop(operator.sub, other)

  def __rsub__(self, other):
    return self._new(np.asarray(other) - self._data)

  def __mul__(self, other):
    return self._binop(operator.mul, other)

  def __rmul__(self, other):
    return self.__mul__(other)

  def __truediv__(self, other):
    return self._binop(operator.truediv, other)

  def __neg__(self):
    return self._new(-self._data)

  def __abs__(self):
    return self._new(np.abs(self._data))

  def __pow__(self, exp):
    return self._new(self._data ** exp)

  #------------------------------------------------------------------------------- Indexing / numpy

  def __len__(self):
    return len(self._data)

  def __getitem__(self, key) -> Signal:
    """Slice by sample index."""
    return self._new(self._data[key])

  def __array__(self, dtype=None):
    """NumPy interop: `np.asarray(sig)` yields a copy, never the read-only buffer."""
    if dtype: return self._data.astype(dtype)
    return self._data.copy()

  def __iter__(self):
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
    """Normalize to [-1, 1] range."""
    peak = np.max(np.abs(self._data))
    if peak == 0: return self._new(self._data.copy())
    return self._new(self._data / peak)

  def window(self, name:str="hann") -> Signal:
    """Apply window function (hann, hamming, blackman, tukey, bartlett)."""
    n = len(self._data)
    win_fn = getattr(windows, name, None) or getattr(np, name, None)
    if win_fn is None:
      raise ValueError(f"Unknown window: '{name}'")
    return self._new(self._data * win_fn(n))

  def trim(self, start_s:float=0, end_s:float|None=None) -> Signal:
    """Trim by time in seconds."""
    i0 = int(start_s * self._fs)
    i1 = int(end_s * self._fs) if end_s is not None else len(self._data)
    return self._new(self._data[i0:i1])

  def integrate(self, highpass_Hz:float=1.0, units:str|None=None) -> Signal:
    """
    Integrate signal (acceleration → velocity → displacement).

    DC removal, Tukey window, high-pass and final detrend suppress the drift that plain
    cumulative integration accumulates. `units` is inherited when omitted, so pass the
    new unit explicitly.
    """
    data = self._data - np.mean(self._data)
    data *= windows.tukey(len(data), alpha=0.05)
    sos = butter(4, highpass_Hz, "high", fs=self._fs, output="sos")
    data = sosfiltfilt(sos, data)
    result = cumulative_trapezoid(data, dx=1 / self._fs, initial=0)
    result = _detrend(result, type="linear")
    return self._new(result, units=units)

  def derivative(self) -> Signal:
    """Numerical derivative, same length as input."""
    return self._new(np.gradient(self._data, 1 / self._fs))

  def envelope(self) -> Signal:
    """Amplitude envelope via Hilbert transform."""
    analytic = hilbert(self._data)
    return self._new(np.abs(analytic))

  #--------------------------------------------------------------------------------------- Spectral

  def fft(self, window:str|None=None) -> Spectrum:
    """One-sided FFT, `window` applied first when given."""
    data = self._data
    if window: data = self.window(window)._data
    freqs = np.fft.rfftfreq(len(data), d=1 / self._fs)
    coeffs = np.fft.rfft(data)
    return Spectrum(freqs, coeffs, self._fs)

  def psd(self, nperseg:int=256, window:str="hann") -> tuple[np.ndarray, np.ndarray]:
    """Power spectral density via Welch's method → (frequencies_Hz, power_density)."""
    f, pxx = welch(self._data, fs=self._fs, nperseg=min(nperseg, len(self._data)), window=window)
    return f, pxx

  @property
  def spectral_centroid(self) -> float:
    """Spectral centroid from FFT."""
    return self.fft().centroid

  @property
  def median_freq(self) -> float:
    """Median frequency from FFT power spectrum."""
    return self.fft().median_freq

  #-------------------------------------------------------------------------------- Filter response

  def freq_response(
    self,
    cutoff_Hz:float|list,
    btype:str = "low",
    order:int = 4,
    n:int = 2000,
  ) -> tuple[np.ndarray, np.ndarray]:
    """
    Butterworth filter response → (frequencies_Hz, magnitude).

    Args:
      cutoff_Hz: single frequency, or [low, high] for "band" and "bandstop".
      btype: "low", "high", "band", "bandstop".
    """
    sos = butter(order, cutoff_Hz, btype, fs=self._fs, output="sos")
    w, h = sosfreqz(sos, worN=n, fs=self._fs)
    return w, np.abs(h)

  #-------------------------------------------------------------------------------------- Factories

  @classmethod
  def from_adc(
    cls,
    raw,
    fs:float,
    bits:int = 12,
    vref:float = 3.3,
    offset:int|None = None,
    scale:float|None = None,
    units:str = "V",
    label:str = "",
  ) -> Signal:
    """
    Signal from raw ADC counts, converted as `(raw - offset) * scale`.

    Args:
      offset: zero level, mid-scale `2 ** (bits - 1)` when omitted.
      scale: units per count, replaces the `vref / 2 ** bits` default.
    """
    data = np.asarray(raw, dtype=np.float64)
    if offset is None: offset = 2 ** (bits - 1)
    if scale is None: scale = vref / (2 ** bits)
    data = (data - offset) * scale
    return cls(data, fs=fs, units=units, label=label)

  @classmethod
  def from_accel(cls, raw, fs:float, bits:int=16, g_range:float=2.0, label:str="") -> Signal:
    """
    Signal from signed accelerometer counts (IMU int16, zero-centered), scaled to m/s².

    Args:
      g_range: full-scale range in g, ±2g → 2.0.
    """
    scale = (g_range * 9.81) / (2 ** (bits - 1))
    return cls.from_adc(raw, fs, bits, scale=scale, offset=0, units="m/s²", label=label)

  @classmethod
  def magnitude(cls, *signals:Signal) -> Signal:
    """Per-sample vector magnitude across axes, which must share fs and length."""
    if not signals: raise ValueError("Need at least one signal")
    fs = signals[0]._fs
    n = len(signals[0]._data)
    for s in signals[1:]:
      if s._fs != fs: raise ValueError("All signals must have same sample rate")
      if len(s._data) != n: raise ValueError("All signals must have same length")
    squared = sum(s._data ** 2 for s in signals)
    return cls(np.sqrt(squared), fs=fs, units=signals[0]._units, label="magnitude")

  @classmethod
  def sine(
    cls,
    freq_Hz:float,
    duration:float = 1.0,
    fs:float = 1000,
    amplitude:float = 1.0,
    phase:float = 0,
  ) -> Signal:
    """Sine wave test signal, `phase` in radians."""
    t = np.arange(int(fs * duration)) / fs
    return cls(amplitude * np.sin(2 * np.pi * freq_Hz * t + phase), fs=fs)

  @classmethod
  def noise(cls, duration:float=1.0, fs:float=1000, amplitude:float=1.0) -> Signal:
    """White noise test signal; `amplitude` is the standard deviation, not the peak."""
    n = int(fs * duration)
    return cls(amplitude * np.random.randn(n), fs=fs)

  #---------------------------------------------------------------------------------------- Special

  def __repr__(self):
    parts = [f"n={self.samples}", f"fs={self._fs:.0f}Hz",
      f"duration={self.duration:.3f}s", f"rms={self.rms:.4g}"]
    if self._units: parts.append(f"units='{self._units}'")
    if self._label: parts.append(f"label='{self._label}'")
    return f"Signal({", ".join(parts)})"

  def __str__(self):
    return self.__repr__()

  def __eq__(self, other):
    if not isinstance(other, Signal): return NotImplemented
    return self._fs == other._fs and np.array_equal(self._data, other._data)

  __hash__ = None # numpy data not safely hashable

  def copy(self) -> Signal:
    """Deep copy."""
    return self._new(self._data.copy())

#--------------------------------------------------------------------------------------------- Demo

def demo():
  """Signal processing demo: filter, FFT, vibration metrics."""
  t = np.arange(10000) / 10000
  raw = 2 * np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 200 * t)
  raw += 0.3 * np.random.randn(len(t))
  sig = Signal(raw, fs=10000, units="m/s²", label="accel_x")
  print("Original:", sig)
  print(f"  RMS={sig.rms:.4f}  peak={sig.peak:.4f}  crest={sig.crest_factor:.2f}")
  print()
  clean = sig.highpass(10).lowpass(100)
  print("After BP 10-100Hz:", clean)
  print(f"  RMS={clean.rms:.4f}  (50Hz component isolated)")
  print()
  sp = sig.fft("hann")
  print("Spectrum:", sp)
  print(f"  Peak freq: {sp.peak_freq:.1f} Hz")
  print(f"  Centroid:  {sp.centroid:.1f} Hz")
  print(f"  Median:    {sp.median_freq:.1f} Hz")
  print()
  doubled = sig * 2
  diff = sig - clean
  print(f"sig * 2:     RMS={doubled.rms:.4f} (2x original)")
  print(f"sig - clean: RMS={diff.rms:.4f} (residual noise + 200Hz)")
  print()
  vel = sig.integrate(highpass_Hz=5, units="m/s")
  print("Velocity:", vel)
  print()
  sine = Signal.sine(440, duration=0.5, fs=44100)
  noise = Signal.noise(duration=0.5, fs=44100)
  mix = sine + noise * 0.1
  print("Sine:", sine)
  print("Noise:", noise)
  print("Mix:", mix)

if __name__ == "__main__":
  demo()