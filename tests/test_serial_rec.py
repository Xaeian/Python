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

from xaeian.serial import Recorder, SerialPort

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

@pytest.fixture
def recorder(monkeypatch):
  """A Recorder whose `connect()` plugs in a `FakePort` instead of opening hardware."""
  def build(**port_kw):
    rec = Recorder("FAKE", print_console=False)
    fake = FakePort(**port_kw)
    def connect(self):
      if self.serial is None:
        self.serial = fake
        self.connected = True
      return True
    monkeypatch.setattr(SerialPort, "connect", connect)
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
