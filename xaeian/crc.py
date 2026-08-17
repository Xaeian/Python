# xaeian/crc.py

"""
Table-driven CRC checksums.

Fully configurable CRC-8/16/32, plus predefined instances for common standards
(ISO, Modbus, SMBus, Maxim).

Example:
  >>> from xaeian.crc import crc16_modbus
  >>> encoded = crc16_modbus.encode(b"hello")
  >>> crc16_modbus.decode(encoded)
  b'hello'
"""

CRC_MASK = {8: 0xFF, 16: 0xFFFF, 32: 0xFFFFFFFF}

def reflect_bit(data:int, width:int) -> int:
  """Reverse the low `width` bits of `data`: `0b1100`, `4` → `0b0011`."""
  reflection = 0
  for bit in range(width):
    if data & 0x01: reflection |= (1 << ((width - 1) - bit))
    data = (data >> 1)
  return reflection

class CRC:
  """
  Table-driven CRC calculator.

  Args:
    width: CRC width in bits, `8`, `16` or `32`.
    polynomial: Generator polynomial without the leading `1`.
    initial: Starting register value.
    reflect_in: Reflect each input byte.
    reflect_out: Reflect the whole CRC once the message is consumed.
    xor: Mask XOR-ed in after reflection.
    invert_out: Byte-swap the result, as Modbus RTU expects.
  """
  def __init__(
    self,
    width:int,
    polynomial:int,
    initial:int,
    reflect_in:bool,
    reflect_out:bool,
    xor:int,
    invert_out:bool,
  ):
    self.width = width
    self.polynomial = polynomial
    self.initial = initial
    self.reflect_in = reflect_in
    self.reflect_out = reflect_out
    self.xor = xor
    self.invert_out = invert_out
    self.topbit = (1 << (width - 1))
    self.array: list[int] = []
    self.__init()

  def __init(self):
    """Build the remainder lookup table, plus the reflected-byte table when `reflect_in`."""
    for i in range(256):
      remainder = i << (self.width - 8)
      for bit in range(8, 0, -1):
        if remainder & self.topbit: remainder = (remainder << 1) ^ self.polynomial
        else: remainder = (remainder << 1)
      remainder &= CRC_MASK[self.width]
      self.array.append(remainder)
    self._ref_byte = [reflect_bit(i, 8) for i in range(256)] if self.reflect_in else None

  def checksum(self, msg:bytes) -> int:
    """CRC of `msg` with this instance's reflect, xor and invert steps applied."""
    remainder = self.initial
    ref = self._ref_byte
    shift = self.width - 8
    mask = CRC_MASK[8]
    wide = CRC_MASK[self.width]
    for byte in msg:
      if ref: byte = ref[byte]
      data = (byte ^ (remainder >> shift)) & mask
      remainder = (self.array[data] ^ (remainder << 8)) & wide
    remainder &= wide
    if self.reflect_out: remainder = reflect_bit(remainder, self.width)
    remainder = remainder ^ self.xor
    if self.invert_out:
      remainder = self.to_int(bytes(reversed(self.to_bytes(remainder))))
    return remainder

  def to_bytes(self, crc:int) -> bytes:
    """Convert CRC integer to bytes (big-endian)."""
    return crc.to_bytes(self.width // 8, byteorder="big")

  def to_int(self, crc:bytes) -> int:
    """Convert big-endian CRC bytes to integer."""
    if self.width == 32: return int((crc[0] << 24) + (crc[1] << 16) + (crc[2] << 8) + crc[3])
    if self.width == 16: return int((crc[0] << 8) + crc[1])
    if self.width == 8: return int(crc[0])
    raise ValueError(f"Unsupported CRC width: {self.width} (supported: 32, 16, 8)")

  def decode(self, frame:bytes) -> bytes|None:
    """Verify and strip the trailing CRC of `frame`, `None` when it does not match."""
    n = self.width // 8
    if not frame or len(frame) < n: return None
    msg = frame[:-n]
    crc = frame[-n:]
    if self.to_int(crc) == self.checksum(msg): return msg
    return None

  def encode(self, msg:bytes) -> bytes:
    """Append the CRC of `msg` to `msg`."""
    crc = self.checksum(msg)
    return msg + self.to_bytes(crc)

#--------------------------------------------------------------------------------------- Predefined

crc32_iso = CRC(32, 0x04C11DB7, 0xFFFFFFFF, True, True, 0xFFFFFFFF, False)
"""CRC-32 ISO 3309: Ethernet, ZIP, PNG, GZIP."""

crc32_aixm = CRC(32, 0x814141AB, 0x00000000, False, False, 0x00000000, False)
"""CRC-32 AIXM: aviation data exchange."""

crc32_autosar = CRC(32, 0xF4ACFB13, 0xFFFFFFFF, True, True, 0xFFFFFFFF, False)
"""CRC-32 AUTOSAR: automotive E2E protection."""

crc32_cksum = CRC(32, 0x04C11DB7, 0x00000000, False, False, 0xFFFFFFFF, False)
"""CRC-32 POSIX cksum."""

crc16_kermit = CRC(16, 0x1021, 0x0000, True, True, 0x0000, False)
"""CRC-16 Kermit (CCITT)."""

crc16_modbus = CRC(16, 0x8005, 0xFFFF, True, True, 0x0000, True)
"""CRC-16 Modbus RTU: industrial communication."""

crc16_buypass = CRC(16, 0x8005, 0x0000, False, False, 0x0000, False)
"""CRC-16 Buypass: payment systems."""

crc8_maxim = CRC(8, 0x31, 0x00, True, True, 0x00, False)
"""CRC-8 Maxim/Dallas: 1-Wire devices."""

crc8_smbus = CRC(8, 0x07, 0x00, False, False, 0x00, False)
"""CRC-8 SMBus: System Management Bus."""

#-------------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  msg = b"123456789"
  print("checksum:", hex(crc32_iso.checksum(msg)))
  print("checksum:", hex(crc16_modbus.checksum(msg)))
  print("checksum:", hex(crc8_smbus.checksum(msg)))
  print()
  data = b"Hello!"
  encoded = crc16_modbus.encode(data)
  print("encode:", data, "→", encoded.hex(" "))
  print("decode:", crc16_modbus.decode(encoded))
  print("decode corrupted:", crc16_modbus.decode(encoded[:-1] + b"\x00"))
