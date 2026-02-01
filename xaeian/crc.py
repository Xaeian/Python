# xaeian/crc.py

"""
CRC checksum calculations with table-driven algorithm.

Supports CRC-8, CRC-16, and CRC-32 with configurable parameters.
Includes predefined instances for common standards (Modbus, ISO, etc.).

Example:
  >>> from xaeian.crc import crc16_modbus, crc32_iso
  >>> crc16_modbus.checksum(b"hello")
  19342
  >>> encoded = crc16_modbus.encode(b"hello")
  >>> crc16_modbus.decode(encoded)
  b'hello'
"""

CRC_MASK = {8: 0xFF, 16: 0xFFFF, 32: 0xFFFFFFFF}

def reflect_bit(data:int, width:int) -> int:
  """
  Reflect (reverse) bits in a value.

  Args:
    data: Value to reflect.
    width: Number of bits to reflect.

  Returns:
    Bit-reversed value.

  Example:
    >>> reflect_bit(0b1100, 4)
    3  # 0b0011
  """
  reflection = 0
  for bit in range(width):
    if data & 0x01: reflection |= (1 << ((width - 1) - bit))
    data = (data >> 1)
  return reflection

class CRC:
  """
  Configurable CRC calculator with table-driven algorithm.

  Supports CRC-8, CRC-16, and CRC-32 with full parameter control.

  Args:
    width: CRC width in bits (`8`, `16`, or `32`).
    polynomial: Generator polynomial (without leading 1).
    initial: Initial register value.
    reflectIn: Reflect input bytes when `True`.
    reflectOut: Reflect final CRC when `True`.
    xor: XOR mask applied to final CRC.
    invertOut: Byte-reverse output when `True` (for Modbus).

  Example:
    >>> crc = CRC(16, 0x8005, 0xFFFF, True, True, 0x0000, False)
    >>> crc.checksum(b"123456789")
    47933
  """
  def __init__(
    self,
    width: int,
    polynomial: int,
    initial: int,
    reflectIn: bool,
    reflectOut: bool,
    xor: int,
    invertOut: bool,
  ):
    self.width = width
    self.polynomial = polynomial
    self.initial = initial
    self.reflectIn = reflectIn
    self.reflectOut = reflectOut
    self.xor = xor
    self.invertOut = invertOut
    self.topbit = (1 << (width - 1))
    self.array: list[int] = []
    self.__init()

  def __init(self):
    """Build lookup table for fast CRC calculation."""
    for i in range(256):
      remainder = i << (self.width - 8)
      for bit in range(8, 0, -1):
        if remainder & self.topbit: remainder = (remainder << 1) ^ self.polynomial
        else: remainder = (remainder << 1)
      remainder &= CRC_MASK[self.width]
      self.array.append(remainder)

  def checksum(self, msg:bytes) -> int:
    """
    Calculate CRC checksum for message.

    Args:
      msg: Input bytes to checksum.

    Returns:
      CRC value as integer.

    Example:
      >>> crc16_modbus.checksum(b"hello")
      19342
    """
    msg = [x for x in msg]
    remainder = self.initial
    for byte in range(len(msg)):
      if self.reflectIn: msg[byte] = reflect_bit(msg[byte], 8)
      data = msg[byte] ^ (remainder >> (self.width - 8))
      tmp = data & CRC_MASK[8]
      remainder = self.array[tmp] ^ (remainder << 8)
    remainder &= CRC_MASK[self.width]
    if self.reflectOut: remainder = reflect_bit(remainder, self.width)
    remainder = remainder ^ self.xor
    if self.invertOut:
      remainder = self.to_int(bytes(reversed(self.to_bytes(remainder))))
    return remainder

  def to_bytes(self, crc:int) -> bytes:
    """Convert CRC integer to bytes (big-endian)."""
    return crc.to_bytes(int(self.width / 8), byteorder="big")

  def to_int(self, crc:bytes) -> int:
    """Convert CRC bytes to integer."""
    crc = [x for x in crc]
    if self.width == 32: return int((crc[0] << 24) + (crc[1] << 16) + (crc[2] << 8) + crc[3])
    if self.width == 16: return int((crc[0] << 8) + crc[1])
    if self.width == 8: return int(crc[0])

  def decode(self, frame:bytes) -> bytes|None:
    """
    Decode and verify CRC-protected frame.

    Args:
      frame: Message with appended CRC bytes.

    Returns:
      Original message without CRC, or `None` on CRC mismatch.

    Example:
      >>> encoded = crc16_modbus.encode(b"hello")
      >>> crc16_modbus.decode(encoded)
      b'hello'
    """
    n = int(self.width / 8)
    if not frame or len(frame) < n: return None
    msg = frame[:-n]
    crc = frame[-n:]
    if self.to_int(crc) == self.checksum(msg): return msg
    return None

  def encode(self, msg:bytes) -> bytes:
    """
    Encode message with appended CRC.

    Args:
      msg: Message bytes to protect.

    Returns:
      Message with CRC appended.

    Example:
      >>> crc16_modbus.encode(b"hello")
      b'hello\\x8eK'
    """
    crc = self.checksum(msg)
    return msg + self.to_bytes(crc)

#----------------------------------------------------------------------------------- Predefined

# CRC-32 variants
crc32_iso = CRC(32, 0x04C11DB7, 0xFFFFFFFF, True, True, 0xFFFFFFFF,False)
"""CRC-32 ISO 3309 — Ethernet, ZIP, PNG, GZIP."""

crc32_aixm = CRC(32, 0x814141AB, 0x00000000, False, False, 0x00000000, False)
"""CRC-32 AIXM — aviation data exchange."""

crc32_autosar = CRC(32, 0xF4ACFB13, 0xFFFFFFFF, True,  True,  0xFFFFFFFF, False)
"""CRC-32 AUTOSAR — automotive E2E protection."""

crc32_cksum = CRC(32, 0x04C11DB7, 0x00000000, False, False, 0xFFFFFFFF, False)
"""CRC-32 POSIX cksum."""

# CRC-16 variants
crc16_kermit = CRC(16, 0x1021, 0x0000, True, True, 0x0000, False)
"""CRC-16 Kermit (CCITT)."""

crc16_modbus = CRC(16, 0x8005, 0xFFFF, True, True, 0x0000, True)
"""CRC-16 Modbus RTU — industrial communication."""

crc16_buypass = CRC(16, 0x8005,     0x0000,     False, False, 0x0000, False)
"""CRC-16 Buypass — payment systems."""

# CRC-8 variants
crc8_maxim = CRC(8, 0x31, 0x00, True,  True,  0x00, False)
"""CRC-8 Maxim/Dallas — 1-Wire devices."""

crc8_smbus = CRC(8, 0x07, 0x00, False, False, 0x00, False)
"""CRC-8 SMBus — System Management Bus."""

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  msg = b"123456789"
  print("checksum:", hex(crc32_iso.checksum(msg)))
  print("checksum:", hex(crc16_modbus.checksum(msg)))
  print("checksum:", hex(crc8_smbus.checksum(msg)))
  print()
  data = b"Hello!"
  encoded = crc16_modbus.encode(data)
  print("encode:", data, "->", encoded.hex(" "))
  print("decode:", crc16_modbus.decode(encoded))
  print("decode corrupted:", crc16_modbus.decode(encoded[:-1] + b"\x00"))
