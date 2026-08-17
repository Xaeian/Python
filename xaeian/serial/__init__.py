# xaeian/serial/__init__.py

"""
Serial communication over `pyserial`.

`SerialPort` is the colored-console base, `Recorder`/`MultiRecorder` poll numeric values in a
background thread, `Shell` speaks the embedded SH command protocol.
"""

__extras__ = ("serial", ["pyserial"])

from .port import SerialPort, serial_scan
from .rec import Recorder, MultiRecorder
from .sh import Shell, convert_value

__all__ = [
  "SerialPort", "serial_scan",
  "Recorder", "MultiRecorder",
  "Shell", "convert_value",
]