# tests/test_crc.py

"""CRC checksums: catalog check values, round-trips, framing, parameter effects."""

import zlib
import pytest
from xaeian.crc import (
  CRC, reflect_bit,
  crc32_iso, crc32_aixm, crc32_autosar, crc32_cksum,
  crc16_kermit, crc16_modbus, crc16_buypass,
  crc8_maxim, crc8_smbus,
)

CHECK = b"123456789" # the standard CRC catalog test vector

#---------------------------------------------------------------------------------- reflect_bit

def reflect_reverses_bit_order():
  assert reflect_bit(0b1100, 4) == 0b0011
  assert reflect_bit(0b10000000, 8) == 0b00000001

def reflect_is_its_own_inverse():
  for value in (0x00, 0x01, 0x80, 0xA5, 0xFF):
    assert reflect_bit(reflect_bit(value, 8), 8) == value

def reflect_palindrome_is_unchanged():
  assert reflect_bit(0b1001_1001, 8) == 0b1001_1001

#------------------------------------------------------------------------------- catalog values

# Every predefined instance matched against its published check value for "123456789".
CATALOG = [
  (crc32_iso, 0xCBF43926), # standard CRC-32 (Ethernet, ZIP, PNG)
  (crc32_aixm, 0x3010BF7F),
  (crc32_autosar, 0x1697D06A),
  (crc32_cksum, 0x765E7680),
  (crc16_kermit, 0x2189),
  (crc16_modbus, 0x374B), # 0x4B37 byte-swapped by invertOut
  (crc16_buypass, 0xFEE8),
  (crc8_maxim, 0xA1),
  (crc8_smbus, 0xF4),
]

@pytest.mark.parametrize("crc, expected", CATALOG)
def predefined_matches_catalog_check_value(crc, expected):
  assert crc.checksum(CHECK) == expected

@pytest.mark.parametrize("crc, _", CATALOG)
def checksum_is_deterministic(crc, _):
  assert crc.checksum(CHECK) == crc.checksum(CHECK)

@pytest.mark.parametrize("crc, _", CATALOG)
def checksum_fits_width(crc, _):
  assert 0 <= crc.checksum(b"random payload") < (1 << crc.width)

#---------------------------------------------------------------------------- to_bytes / to_int

@pytest.mark.parametrize("crc", [crc8_smbus, crc16_kermit, crc32_iso])
def bytes_int_round_trip(crc):
  value = crc.checksum(CHECK)
  assert crc.to_int(crc.to_bytes(value)) == value

@pytest.mark.parametrize("crc, n", [(crc8_smbus, 1), (crc16_kermit, 2), (crc32_iso, 4)])
def to_bytes_length_follows_width(crc, n):
  assert len(crc.to_bytes(crc.checksum(CHECK))) == n

def to_bytes_is_big_endian():
  assert crc16_kermit.to_bytes(0x1234) == b"\x12\x34"
  assert crc32_iso.to_bytes(0x01020304) == b"\x01\x02\x03\x04"

def to_int_rejects_unsupported_width():
  odd = CRC(8, 0x07, 0x00, False, False, 0x00, False)
  odd.width = 24 # force an unsupported width past the constructor
  with pytest.raises(ValueError):
    odd.to_int(b"\x00\x00\x00")

#--------------------------------------------------------------------------------------- encode

def encode_appends_crc_after_message():
  assert crc16_modbus.encode(b"hello") == b"hello\xf64"

@pytest.mark.parametrize("crc, n", [(crc8_smbus, 1), (crc16_kermit, 2), (crc32_iso, 4)])
def encode_keeps_message_and_adds_width_bytes(crc, n):
  msg = b"payload"
  frame = crc.encode(msg)
  assert frame[:len(msg)] == msg
  assert len(frame) == len(msg) + n

#--------------------------------------------------------------------------------------- decode

@pytest.mark.parametrize("crc", [crc8_smbus, crc16_modbus, crc16_kermit, crc32_iso])
def decode_recovers_encoded_message(crc):
  for msg in (b"", b"x", b"Hello!", bytes(range(64))):
    assert crc.decode(crc.encode(msg)) == msg

def decode_rejects_corrupted_payload():
  frame = crc16_modbus.encode(b"important")
  corrupt = bytes([frame[0] ^ 0xFF]) + frame[1:]
  assert crc16_modbus.decode(corrupt) is None

def decode_rejects_corrupted_crc():
  frame = crc16_modbus.encode(b"important")
  assert crc16_modbus.decode(frame[:-1] + bytes([frame[-1] ^ 0xFF])) is None

@pytest.mark.parametrize("crc", [crc8_smbus, crc16_kermit, crc32_iso])
def decode_rejects_frame_shorter_than_crc(crc):
  assert crc.decode(b"") is None
  assert crc.decode(b"\x00" * (crc.width // 8 - 1)) is None

#---------------------------------------------------------------------------- parameter effects

def reflect_in_out_change_the_result():
  plain = CRC(16, 0x8005, 0x0000, False, False, 0x0000, False)
  reflected = CRC(16, 0x8005, 0x0000, True, True, 0x0000, False)
  assert plain.checksum(CHECK) != reflected.checksum(CHECK)

def invert_out_byte_swaps_the_crc():
  # crc16_modbus differs from the same spec without invertOut only by byte order
  straight = CRC(16, 0x8005, 0xFFFF, True, True, 0x0000, False)
  assert crc16_modbus.checksum(CHECK) == straight.checksum(CHECK) << 8 & 0xFF00 \
    | straight.checksum(CHECK) >> 8

def xor_mask_flips_output():
  no_xor = CRC(16, 0x1021, 0x0000, True, True, 0x0000, False)
  with_xor = CRC(16, 0x1021, 0x0000, True, True, 0xFFFF, False)
  assert with_xor.checksum(CHECK) == no_xor.checksum(CHECK) ^ 0xFFFF

def custom_crc_from_docstring_example():
  crc = CRC(16, 0x8005, 0xFFFF, True, True, 0x0000, False)
  assert crc.checksum(b"123456789") == 0x4B37

#--------------------------------------------------------------------------- real-world vectors

@pytest.mark.parametrize("data", [b"", b"The quick brown fox", bytes(range(256))])
def crc32_iso_equals_zlib(data):
  # crc32_iso is the standard CRC-32 - it must agree with the stdlib bit-for-bit
  assert crc32_iso.checksum(data) == zlib.crc32(data)

def modbus_rtu_request_frame():
  # "read 10 holding registers from slave 1" - the canonical Modbus textbook frame
  request = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
  assert crc16_modbus.encode(request).hex(" ") == "01 03 00 00 00 0a c5 cd"

def one_wire_rom_checksums_to_zero():
  # 1-Wire trick: a frame followed by its CRC-8/Maxim re-checksums back to 0
  rom = bytes([0x28, 0xFF, 0x64, 0x1E, 0x0F, 0x9A, 0x6B]) # DS18B20-style ROM code
  assert crc8_maxim.checksum(crc8_maxim.encode(rom)) == 0

@pytest.mark.parametrize("crc", [crc8_smbus, crc16_modbus, crc32_iso])
def every_single_bit_flip_is_detected(crc):
  # the core promise of a CRC: any one-bit error in the frame fails verification
  frame = crc.encode(b"sensor")
  for i in range(len(frame)):
    for bit in range(8):
      broken = bytearray(frame)
      broken[i] ^= (1 << bit)
      assert crc.decode(bytes(broken)) is None
