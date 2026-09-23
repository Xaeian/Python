# tests/test_cstruct.py

"""Binary (de)serialization: round-trips, transforms, messages, frames, regressions."""

import random

import pytest
from xaeian.cstruct import Struct, Field, Type, Bitfield, Variant, Endian, Message, Frame
from xaeian.crc import crc32_iso

def scalars():
  s = Struct(name="scalars").add(
    Field(Type.uint8, "a"), Field(Type.int16, "b"), Field(Type.uint32, "c"),
  )
  data = {"a": 7, "b": -1234, "c": 100_000}
  assert s.decode(s.encode(data)) == data

def decode_returns_dict_for_one_list_for_many():
  s = Struct(name="rec").add(Field(Type.uint8, "n"))
  assert s.decode(s.encode({"n": 1})) == {"n": 1}
  assert s.decode(s.encode([{"n": 1}, {"n": 2}])) == [{"n": 1}, {"n": 2}]

def floats_keep_value():
  s = Struct(name="floats").add(Field(Type.float, "x"), Field(Type.double, "y"))
  data = {"x": 1.5, "y": 0.25} # exact in IEEE-754, no rounding slack needed
  assert s.decode(s.encode(data)) == data

def scale_stores_fixed_point():
  s = Struct(name="scaled").add(Field(Type.uint16, "mv", scale=1000))
  assert s.encode({"mv": 1.5}) == (1500).to_bytes(2, "little")
  assert s.decode(s.encode({"mv": 1.5})) == {"mv": 1.5}

def array_field():
  s = Struct(name="arr").add(Field(Type.uint8, "xs", length=4))
  data = {"xs": [10, 20, 30, 40]}
  assert s.decode(s.encode(data)) == data

def string_and_bytes():
  s = Struct(name="blob").add(Field(Type.string, "name"), Field(Type.bytes, "data"))
  data = {"name": "xaeian", "data": b"\x01\x02\x03"}
  assert s.decode(s.encode(data)) == data

def string_utf8_roundtrip():
  s = Struct(name="txt").add(Field(Type.string, "t"))
  data = {"t": "żółw → OK"}
  assert s.decode(s.encode(data)) == data

def crc_travels_with_every_record():
  s = Struct(name="cf", crc=crc32_iso).add(Field(Type.uint16, "x"))
  assert s.decode(s.encode({"x": 7})) == {"x": 7}
  assert s.decode(s.encode([{"x": 1}, {"x": 2}])) == [{"x": 1}, {"x": 2}]
  assert len(s.encode([{"x": 1}, {"x": 2}])) == 2 * (2 + 4) # a crc behind each, not one at the end

def bitfield():
  s = Struct(name="flags").add(Bitfield("st", [("on", 1), ("err", 1), ("mode", 6)]))
  data = {"st": {"on": 1, "err": 0, "mode": 42}}
  assert s.decode(s.encode(data)) == data

def optional_field_uses_default():
  s = Struct(name="opt").add(
    Field(Type.uint8, "a"), Field(Type.uint8, "b", optional=True, default=9),
  )
  assert s.decode(s.encode({"a": 1})) == {"a": 1, "b": 9}

@pytest.mark.parametrize("endian, order", [(Endian.little, "little"), (Endian.big, "big")])
def endian_mirrors_bytes(endian, order):
  s = Struct(name=f"e_{order}", endian=endian).add(Field(Type.uint16, "n"))
  assert s.encode({"n": 258}) == (258).to_bytes(2, order) # 258 == 0x0102
  assert s.decode(s.encode({"n": 258})) == {"n": 258}

@pytest.mark.parametrize("kind, body", [(0, {"a": 99}), (1, {"b": 1.5, "c": 2.5})])
def variant_selects_layout(kind, body):
  s = Struct(name="msg").add(
    Field(Type.uint8, "kind"),
    Variant("body", "kind", {
      0: [Field(Type.uint32, "a")],
      1: [Field(Type.float, "b"), Field(Type.float, "c")],
    }),
  )
  msg = {"kind": kind, "body": body}
  assert s.decode(s.encode(msg)) == msg

@pytest.mark.usefixtures("registry")
def message_routes_by_code():
  pos = Struct(code=1, name="pos").add(Field(Type.int16, "x"), Field(Type.int16, "y"))
  temp = Struct(code=2, name="temp").add(Field(Type.float, "t"))
  message = Message(pos, temp)
  body = message.encode({"pos": {"x": -3, "y": 7}, "temp": [{"t": 21.5}]}) # one record either way
  assert message.decode(body) == {"pos": [{"x": -3, "y": 7}], "temp": [{"t": 21.5}]}

@pytest.mark.usefixtures("registry")
def frame_carries_a_message_end_to_end():
  """The envelope around the blocks: dicts in, dicts out, the wire cut anywhere between."""
  pos = Struct(code=1, name="pos").add(Field(Type.int16, "x"), Field(Type.int16, "y"))
  temp = Struct(code=2, name="temp").add(Field(Type.float, "t"))
  link = Frame(Message(pos, temp), limit=64)
  data = {"pos": [{"x": 1, "y": 2}, {"x": 3, "y": 4}], "temp": [{"t": 21.5}]}
  wire = link.encode(data) * 2
  assert list(link.feed(wire[:7])) + list(link.feed(wire[7:])) == [data, data]
  assert link.errors == 0

def an_empty_body_is_a_frame():
  """A ping carries nothing; what `encode` makes, `feed` must take."""
  link = Frame(limit=8)
  assert list(link.feed(link.encode(b""))) == [b""]
  assert link.errors == 0

def the_header_mirrors_the_wire():
  """Padding and the crc tail are bytes on the wire, so they are members in C."""
  s = Struct(name="hdr", crc=crc32_iso, align=4).add(
    Field(Type.uint16, "a"), Field(Type.uint8, "b"))
  assert len(s.encode({"a": 1, "b": 2})) == 8
  header = s.export_c_header()
  assert "uint8_t _align[1];" in header and "uint8_t crc[4];" in header
  loose = Struct(name="txt", crc=crc32_iso).add(Field(Type.string, "t"))
  assert "_align" not in loose.export_c_header() and "variable size" in loose.export_c_header()

@pytest.mark.usefixtures("registry")
def block_header_is_code_then_size():
  pair = Struct(code=1, name="pair").add(Field(Type.uint16, "a"), Field(Type.uint16, "b"))
  block = pair.block({"a": 0x1234, "b": 0x5678})
  assert block == bytes.fromhex("0100 0400 3412 7856")
  assert pair.records(block[4:]) == [{"a": 0x1234, "b": 0x5678}]

def frame_matches_the_c_layer():
  # Captured from `FRAME_Send` of `demo/com/frame` built on the host,
  # the block above as payload and `crc32_iso`;
  # `zlib.crc32` of that payload gives the same four bytes
  wire = bytes.fromhex("aa55 0c00 0100 0400 3412 7856 371c8236")
  body = bytes.fromhex("0100 0400 3412 7856")
  frame = Frame()
  assert frame.encode(body) == wire
  assert list(frame.feed(wire)) == [body]
  assert frame.errors == 0

def frame_feed_survives_cuts_junk_and_a_false_sync():
  frame = Frame(limit=64)
  bodies = [bytes([i] * (5 + i)) for i in range(12)]
  wire = b"\x00\xAA" + frame.encode(bodies[0])
  # a sync pair in noise between frames, with a plausible length behind it
  wire += b"\xAA\x55\x10\x00junk" + b"".join(frame.encode(b) for b in bodies[1:6])
  broken = bytearray(frame.encode(bodies[6])); broken[7] ^= 0xFF
  wire += bytes(broken) + b"".join(frame.encode(b) for b in bodies[7:])
  got = []
  rng = random.Random(7)
  pos = 0
  while pos < len(wire):
    cut = min(len(wire), pos + rng.randint(1, 9))
    got += list(frame.feed(wire[pos:cut]))
    pos = cut
  assert got == bodies[:6] + bodies[7:]
  assert frame.errors == 2 # the false sync and the broken frame

def alignment_padding_roundtrips_each_record():
  # regression: decode must consume the padding encode appends after each record
  s = Struct(name="aligned", align=4).add(Field(Type.uint8, "a"), Field(Type.uint16, "b"))
  recs = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
  assert s.decode(s.encode(recs)) == recs

def crc_detects_corruption():
  s = Struct(name="guarded", crc=crc32_iso).add(Field(Type.uint16, "n"))
  frame = s.encode({"n": 0xBEEF})
  assert s.decode(frame) == {"n": 0xBEEF}
  for at in (0, -1): # a flipped payload byte, a flipped crc byte
    corrupt = bytearray(frame); corrupt[at] ^= 0xFF
    with pytest.raises(ValueError):
      s.decode(bytes(corrupt))

def missing_required_field_raises():
  s = Struct(name="req").add(Field(Type.uint8, "a"))
  with pytest.raises(KeyError):
    s.encode({})

@pytest.fixture
def registry():
  saved = dict(Struct._codes)
  Struct._codes.clear()
  yield
  Struct._codes.clear()
  Struct._codes.update(saved)

@pytest.mark.usefixtures("registry")
def code_registry_is_idempotent():
  Struct(code=0xA1, name="Frame")
  Struct(code=0xA1, name="Frame") # same code + name: allowed
  with pytest.raises(ValueError):
    Struct(code=0xA1, name="Other") # same code, new name: rejected
