# tests/test_cstruct.py

"""Binary (de)serialization: round-trips, transforms, framing, regressions."""

import pytest
from xaeian.cstruct import Struct, Field, Type, Bitfield, Variant, Endian, Frame
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
def frame_routes_by_code():
  pos = Struct(code=1, name="pos").add(Field(Type.int16, "x"), Field(Type.int16, "y"))
  temp = Struct(code=2, name="temp").add(Field(Type.float, "t"))
  frame = Frame(pos, temp)
  data = {"pos": {"x": -3, "y": 7}, "temp": {"t": 21.5}}
  assert frame.decode(frame.encode(data)) == data

def alignment_padding_roundtrips_each_record():
  # regression: decode must consume the padding encode appends after each record
  s = Struct(name="aligned", align=4).add(Field(Type.uint8, "a"), Field(Type.uint16, "b"))
  recs = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
  assert s.decode(s.encode(recs)) == recs

def crc_detects_corruption():
  s = Struct(name="guarded", crc=crc32_iso).add(Field(Type.uint16, "n"))
  frame = s.encode({"n": 0xBEEF})
  assert s.decode(frame) == {"n": 0xBEEF}
  corrupt = bytes([frame[0] ^ 0xFF]) + frame[1:]
  with pytest.raises(ValueError):
    s.decode(corrupt)

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
