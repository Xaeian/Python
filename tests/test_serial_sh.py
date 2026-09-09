# tests/test_serial_sh.py

"""
`Shell.boot` against a scripted device: the `boot` command of `lib/sh` under the bootloader.

The fake echoes every line the way the console does, answers `BOOT <verb> key:value` lines
with colors on, and drops a log line into the stream now and then.
"""

import struct
import pytest

pytest.importorskip("serial", reason="serial needs the [serial] extra")

from xaeian.crc import crc32_iso
from xaeian.serial import Shell, SerialPort, ihex_to_bin

class FakeDevice:
  """The `boot` verbs on a console: echo, colored `INF`/`ERR` tags, a log line every third call."""
  def __init__(
    self, slot:int=253952, line:int=2047, boot:int=1, torn:bool=False, stubborn:bool=False,
  ):
    self.slot, self.line, self.boot, self.torn, self.stubborn = slot, line, boot, torn, stubborn
    self.pending, self.out = b"", []
    self.size = self.crc = self.offset = 0
    self.staged = bytearray()
    self.calls = 0
    self.ended = False

  def say(self, text:str, level:str="INF"):
    self.out.append(f"\x1b[38;5;71m{level}\x1b[0m {text}\r\n".encode())

  def write(self, data:bytes):
    self.pending += data
    while b"\n" in self.pending:
      line, self.pending = self.pending.split(b"\n", 1)
      self.out.append(b"\x1b[38;5;173m>> \x1b[0m" + line + b"\x1b[38;5;71m^E\x1b[0m\r\n")
      self.handle(line.decode().split(" "))

  def handle(self, argv:list[str]):
    self.calls += 1
    if self.calls % 3 == 0: self.say("Loop alive")
    verb = argv[1]
    if verb == "info":
      self.say(f"BOOT info boot:{self.boot} app:08002000 slot:{self.slot} page:2048 "
        f"line:{self.line} image:100 crc:0000abcd active:0")
    elif verb == "begin":
      self.size, self.crc, self.offset = int(argv[2]), int(argv[3], 16), 0
      self.staged = bytearray()
      self.say(f"BOOT begin size:{self.size} crc:{self.crc:08x}")
    elif verb == "data":
      offset, payload = int(argv[2]), bytes.fromhex(argv[3])
      if len(argv[3]) + len("boot data 4294967295 ") > self.line:
        self.say("BOOT line over the console limit", "ERR")
      elif self.stubborn or offset != self.offset or len(payload) > self.size - self.offset:
        self.say(f"BOOT data at {offset} refused, expected {self.offset}", "ERR")
      else:
        self.staged += payload
        self.offset += len(payload)
        self.say(f"BOOT data offset:{self.offset}")
    elif verb == "end":
      self.ended = self.offset == self.size and crc32_iso.checksum(bytes(self.staged)) == self.crc
      if self.ended: self.say(f"BOOT end crc:{self.crc:08x} reset")
      else: self.say("BOOT image incomplete or corrupt", "ERR")

  def readline(self, n:int=0) -> bytes:
    if not self.out: return b""
    line = self.out.pop(0)
    if self.torn and len(line) > 12: # the reader sees a line in two pieces
      self.out.insert(0, line[12:])
      return line[:12]
    return line

  def read(self, n:int) -> bytes: return self.readline()
  def close(self): pass
  def flush(self): pass

class Image:
  """A class keeps the helper out of reach of `python_functions = ["*"]` collection."""
  @staticmethod
  def built(size:int) -> bytes:
    """The .bin of a build: header at 0x200, eight erased bytes behind the image."""
    body = bytearray((i * 7 + 3) & 0xFF for i in range(size))
    struct.pack_into("<II", body, 0x200, 0x4E45504F, size)
    return bytes(body) + b"\xff" * 8

  @staticmethod
  def hex(image:bytes, origin:int=0x08002000) -> str:
    """The same image as Intel HEX, the way objcopy writes it: 16-byte records, one segment."""
    def record(kind:int, addr:int, data:bytes) -> str:
      raw = bytes([len(data), addr >> 8, addr & 0xFF, kind]) + data
      return f":{raw.hex()}{(-sum(raw)) & 0xFF:02x}".upper()
    lines = [record(4, 0, (origin >> 16).to_bytes(2, "big"))]
    for offset in range(0, len(image), 16):
      lines.append(record(0, (origin + offset) & 0xFFFF, image[offset:offset + 16]))
    lines.append(record(1, 0, b""))
    return "\n".join(lines) + "\n"

@pytest.fixture
def shell(monkeypatch):
  """A Shell whose `connect()` plugs in a FakeDevice instead of opening hardware."""
  def build(**device_kw):
    device = FakeDevice(**device_kw)
    sh = Shell("FAKE", print_console=False, timeout=0.01)
    def connect(self):
      self.serial = device
      self.connected = True
      return True
    monkeypatch.setattr(SerialPort, "connect", connect)
    sh.connect()
    return sh, device
  return build

def a_whole_image_is_staged_and_the_device_resets(shell):
  sh, device = shell()
  image = Image.built(5000)
  assert sh.boot(image) is True
  assert device.ended and bytes(device.staged) == image[:5000]

def an_intel_hex_file_is_the_same_image(shell):
  image = Image.built(3000)
  assert ihex_to_bin(Image.hex(image)) == image
  sh, device = shell()
  assert sh.boot(Image.hex(image).encode()) is True
  assert device.ended and bytes(device.staged) == image[:3000]

def a_broken_hex_record_is_refused(shell):
  sh, device = shell()
  text = Image.hex(Image.built(1000)).replace("\n:10", "\n:11", 1)
  assert sh.boot(text.encode()) is False
  assert device.calls == 0

def a_path_is_read_and_sent(shell, tmp_path):
  image = Image.built(2000)
  path = tmp_path / "app.hex"
  path.write_text(Image.hex(image))
  sh, device = shell()
  assert sh.boot(str(path)) is True
  assert device.ended and bytes(device.staged) == image[:2000]
  assert sh.boot(str(tmp_path / "missing.bin")) is False

def data_lines_follow_the_console_line_of_the_device(shell):
  sh, device = shell(line=511)
  assert sh.boot(Image.built(3000)) is True
  assert device.ended

def a_reply_split_across_reads_is_joined(shell):
  sh, device = shell(torn=True)
  assert sh.boot(Image.built(2500)) is True
  assert device.ended

def info_reads_the_fields_as_numbers(shell):
  sh, _ = shell()
  info = sh.boot_info()
  assert info["boot"] == 1 and info["app"] == 0x08002000 and info["slot"] == 253952
  assert info["crc"] == 0xABCD and info["line"] == 2047

def a_file_without_the_header_never_goes_out(shell):
  sh, device = shell()
  assert sh.boot(b"\xff" * 0x300) is False
  assert device.calls == 0

def a_device_without_a_slot_is_refused(shell):
  sh, device = shell(boot=0)
  assert sh.boot(Image.built(2500)) is False
  assert device.calls == 1

def an_image_over_the_slot_is_refused_before_a_byte_goes(shell):
  sh, device = shell(slot=4096)
  assert sh.boot(Image.built(5000)) is False
  assert device.calls == 1

def a_refused_line_stops_the_transfer(shell):
  sh, device = shell(stubborn=True)
  assert sh.boot(Image.built(3000)) is False
  assert device.calls == 3 and not device.ended # info, begin, one refused data line
