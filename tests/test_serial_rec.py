# tests/test_serial_rec.py

"""
Recorder lifecycle over a fake port: who owns the thread, who owns the connection.

The calling thread must not close the port under a reader still reading it.
These tests pin the ownership down: the thread opens and closes its own port,
`with` starts and stops the thread.
"""

import threading, time
import pytest

pytest.importorskip("serial", reason="serial needs the [serial] extra")

from xaeian.serial import Recorder, MultiRecorder, SerialPort
from xaeian.crc import crc16_modbus

class FakePort:
  """Scripted byte stream; a `gate` makes every read block until the test releases it."""
  def __init__(self, chunks=(), gate:threading.Event|None=None):
    self.chunks = list(chunks)
    self.gate = gate
    self.closed = False

  def read(self, n):
    if self.gate: self.gate.wait()
    return self.chunks.pop(0) if self.chunks else b""

  def close(self):
    self.closed = True

  def plug(self, monkeypatch) -> None:
    """Make `SerialPort.connect` hand out this port instead of opening hardware."""
    def connect(port):
      if port.serial is None:
        port.serial = self
        port.connected = True
      return True
    monkeypatch.setattr(SerialPort, "connect", connect)

@pytest.fixture
def recorder(monkeypatch):
  """A Recorder whose `connect()` plugs in a `FakePort` instead of opening hardware."""
  def build(**port_kw):
    rec = Recorder("FAKE", print_console=False)
    fake = FakePort(**port_kw)
    fake.plug(monkeypatch)
    return rec, fake
  return build

#---------------------------------------------------------------------------------------- lifecycle

def with_block_starts_the_reader_and_stops_it(recorder):
  rec, fake = recorder(chunks=[b"1.5\n", b"2.5\n"])
  with rec:
    deadline = time.time() + 2
    while rec.value is None and time.time() < deadline:
      time.sleep(0.01)
    assert rec.value in (1.5, 2.5)
  assert rec._thread is None, "the reader outlived the with block"
  assert fake.closed, "the thread did not close its own port"

def stop_keeps_the_handle_when_the_thread_does_not_exit_in_time(recorder):
  gate = threading.Event()
  rec, fake = recorder(gate=gate)
  rec.start()
  time.sleep(0.05) # let the reader block on the gate
  assert rec.stop(timeout_ms=1) is False
  assert rec._thread is not None, "a live thread lost its handle"
  gate.set()
  assert rec.stop(timeout_ms=2000) is True
  assert rec._thread is None

def disconnect_refuses_to_close_under_a_live_thread(recorder):
  gate = threading.Event()
  rec, fake = recorder(gate=gate)
  rec.start()
  time.sleep(0.05)
  rec.stop = lambda timeout_ms=2000: Recorder.stop(rec, timeout_ms=1)
  rec.disconnect()
  assert not fake.closed, "the port was closed under a live thread"
  del rec.stop
  gate.set()
  rec.stop()

#-------------------------------------------------------------------------------------- read policy

def a_read_before_connect_is_a_programming_error():
  port = SerialPort("FAKE")
  with pytest.raises(RuntimeError, match="Not connected"):
    port.read()
  with pytest.raises(RuntimeError, match="Not connected"):
    port.send("hello")

def a_read_after_disconnect_says_not_connected(recorder):
  rec, fake = recorder()
  rec.connect()
  rec.serial = fake
  SerialPort.disconnect(rec)
  with pytest.raises(RuntimeError, match="Not connected"):
    rec.read()

def values_split_across_chunks_still_match(recorder):
  rec, fake = recorder(chunks=[b"12.", b"5\n99", b".5\n"])
  rec.connect()
  assert rec.read_value() is None # "12." alone is not a complete line yet
  assert rec.read_value() == 12.5
  assert rec.read_value() == 99.5

def scientific_notation_reads_whole_by_default(recorder):
  """The last match wins, so a pattern blind to exponents would read `01` out of `1.25e+01`."""
  rec, _ = recorder(chunks=[b"1.25e+01\n"])
  rec.connect()
  assert rec.read_value() == 12.5

def an_overload_is_no_reading_not_the_last_one(recorder):
  """A meter over its range prints `OL`: the reading before it is no longer true."""
  rec, _ = recorder(chunks=[b"1.234\n", b"OL\n"])
  rec.connect()
  assert rec.read_value() == 1.234
  assert rec.read_value() is None

def a_meter_showing_ol_keeps_its_port(recorder):
  """A line without a number still comes in: it pushes back the deadline only silence reaches."""
  rec, _ = recorder(chunks=[b"OL\n"])
  rec.connect()
  rec.read_value()
  assert rec.err_time > time.time()

def a_reply_cut_by_the_timeout_is_read_whole(monkeypatch):
  """Modbus RTU ends a reply with silence; cut by the timeout, neither half would verify."""
  reply = crc16_modbus.encode(bytes.fromhex("010302002a"))
  FakePort([reply[:3], reply[3:]]).plug(monkeypatch)
  port = SerialPort("FAKE", crc=crc16_modbus, print_console=False)
  port.connect()
  assert port.read() == bytes.fromhex("010302002a")

def a_zero_reading_reads_as_zero(recorder):
  """A meter at 0V prints a 0 before the point; missed, a true zero would read as no reading."""
  rec, _ = recorder(chunks=[b"+4.99876543E+00\n", b"+0.00000000E+00\n"])
  rec.regex = Recorder.SCI_NORM
  rec.connect()
  assert rec.read_value() == 4.99876543
  assert rec.read_value() == 0.0

@pytest.mark.parametrize("regex, line", [
  ("SCI_NORM", b"10.5E+02\n"), # not normalized: 0.5E+02 out of it would read 50
  ("SCI_NORM", b"1.23E+045\n"), # three exponent digits: 1.23E+04 out of it would read 12300
  ("FLOAT", b"1.2e-05\n"), # the mantissa alone would read 1.2
  ("NUM", b"1.2.3\n"), # a version, not a reading: its last part would read 3
])
def a_pattern_never_reads_part_of_a_number(recorder, regex, line):
  rec, _ = recorder(chunks=[line])
  rec.regex = getattr(Recorder, regex)
  rec.connect()
  assert rec.read_value() is None

def a_line_of_values_reads_whole_by_default(monkeypatch):
  """The readme's line, an integer among the values and an exponent on the next."""
  FakePort([b"12.5,0.34,25.0,1500\r\n", b"0.5,1.2e-05,25,3.3\r\n"]).plug(monkeypatch)
  mr = MultiRecorder("FAKE", count=4, separator=",", print_console=False)
  mr.connect()
  assert mr.read_values() == [12.5, 0.34, 25.0, 1500.0]
  assert mr.read_values() == [0.5, 1.2e-05, 25.0, 3.3]

def float_refuses_a_line_it_would_cut(monkeypatch):
  FakePort([b"0.5,1.2e-05,25.0,3.3\r\n"]).plug(monkeypatch)
  mr = MultiRecorder("FAKE", count=4, separator=",", regex=Recorder.FLOAT, print_console=False)
  mr.connect()
  assert mr.read_values() is None # never 1.2 in place of 0.000012

def a_silent_device_is_reconnected_not_abandoned(recorder):
  """After `err_delay_ms` of silence the reader drops the port and opens it again, still alive."""
  rec, fake = recorder(chunks=[b"1.5\n"])
  rec.err_delay_ms = 50
  rec.start()
  time.sleep(0.4)
  alive = rec._thread is not None and rec._thread.is_alive()
  rec.stop()
  assert alive, "the reader died on the first dropout"
  assert fake.closed, "the silent link was never dropped"
  assert rec.value is None
