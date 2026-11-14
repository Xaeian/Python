# tests/test_cstruct.py

"""Binary (de)serialization: round-trips, transforms, messages, frames and what gets refused."""

import random, subprocess
from enum import IntEnum
from pathlib import Path

import pytest
from xaeian.cstruct import Struct, Field, Type, Bitfield, Endian, Message, Frame, Padding
from xaeian.crc import crc32_iso

class State(IntEnum):
  """Names of the numbers of a deck's state, sparse as a firmware's codes often are."""
  Idle = 0
  Run = 1
  Fault = 7

# The example of the readme
POINT = Struct("point", Field(Type.int16, "x", "mm"), Field(Type.int16, "y", "mm"))
SAMPLE = Struct("sample",
  Field(Type.uint32, "time", "us"),
  Field(POINT, "pos", length=2, doc="start and end"),
  Field(Type.int16, "temp", "°C", scale=10, doc="board temperature"),
  Bitfield("flags", [("mode", 4), ("fault", 4)]),
  Padding(1),
)
RECORD = {
  "time": 1200,
  "pos": [{"x": 1, "y": -2}, {"x": 3, "y": 4}],
  "temp": 23.4,
  "flags": {"mode": 3, "fault": 9},
}

#------------------------------------------------------------------------------------------ records

def the_readme_sample_round_trips():
  data = SAMPLE.encode(RECORD)
  assert SAMPLE.decode(data) == RECORD and SAMPLE.records(data * 2) == [RECORD, RECORD]
  assert SAMPLE.size == len(data) == 16

def integers_keep_value():
  s = Struct("integers", Field(Type.uint8, "a"), Field(Type.int16, "b"), Field(Type.uint32, "c"))
  data = {"a": 7, "b": -1234, "c": 100_000}
  assert s.decode(s.encode(data)) == data

def decode_reads_one_record_and_records_a_run():
  """One shape per call: `decode` a dict, `records` a list, whatever the count."""
  s = Struct("rec", Field(Type.uint8, "n"))
  assert s.decode(s.encode({"n": 1})) == {"n": 1}
  assert s.records(s.encode({"n": 1})) == [{"n": 1}]
  assert s.records(s.encode({"n": 1}) + s.encode({"n": 2})) == [{"n": 1}, {"n": 2}]
  with pytest.raises(ValueError):
    s.decode(s.encode({"n": 1}) + s.encode({"n": 2})) # a second record is no part of the first

def floats_keep_value():
  s = Struct("floats", Field(Type.float, "x"), Field(Type.double, "y"))
  data = {"x": 1.5, "y": 0.25} # exact in IEEE-754, no rounding slack needed
  assert s.decode(s.encode(data)) == data

def a_float_decodes_to_what_its_type_holds():
  """At 3 decimals 0.000123A would decode as 0.0; at 7 digits 12345678 would come back 12345680."""
  s = Struct("meter",
    Field(Type.float, "a"), Field(Type.float, "v"), Field(Type.float, "n"),
    Field(Type.float, "k"), Field(Type.double, "wh"),
  )
  data = {"a": 0.000123, "v": 3.2999, "n": 12345678.0, "k": 1.2345678, "wh": 12345.678901}
  assert s.decode(s.encode(data)) == data
  top = Struct("top", Field(Type.float, "v"))
  assert top.decode(top.encode({"v": 3.4028235e38})) == {"v": 3.4028235e38} # FLT_MAX, no reading

def a_float_read_and_written_back_keeps_its_bits():
  """A config read, one field changed and saved again must leave every other float as it was."""
  s = Struct("cfg", Field(Type.float, "x"), Field(Type.float, "k", scale=1000))
  rng = random.Random(1)
  for _ in range(2000):
    wire = s.encode({"x": rng.uniform(-1e4, 1e4), "k": rng.uniform(-10, 10)})
    assert s.encode(s.decode(wire)) == wire

def scale_stores_fixed_point():
  s = Struct("scaled", Field(Type.uint16, "mv", scale=1000))
  assert s.encode({"mv": 1.5}) == (1500).to_bytes(2, "little")
  assert s.decode(s.encode({"mv": 1.5})) == {"mv": 1.5}

@pytest.mark.parametrize("sp, lim", [(2.3, 33.3), (19.99, 1.1), (-1.15, 0.3), (4.35, 99.9)])
def fixed_point_rounds_to_its_step(sp, lim):
  """`2.3 * 100` is 229.99999999999997 in floating point: truncated, the device would get 2.29."""
  s = Struct("setpoint", Field(Type.int16, "sp", scale=100), Field(Type.uint16, "lim", scale=10))
  assert s.decode(s.encode({"sp": sp, "lim": lim})) == {"sp": sp, "lim": lim}

def an_array_is_a_list():
  s = Struct("arr", Field(Type.uint8, "xs", length=4))
  data = {"xs": [10, 20, 30, 40]}
  assert s.decode(s.encode(data)) == data

def a_string_and_bytes_keep_value():
  s = Struct("blob", Field(Type.string, "name"), Field(Type.bytes, "data"))
  data = {"name": "xaeian", "data": b"\x01\x02\x03"}
  assert s.decode(s.encode(data)) == data

def a_string_keeps_its_utf8():
  s = Struct("txt", Field(Type.string, "t"))
  data = {"t": "żółw → OK"}
  assert s.decode(s.encode(data)) == data

def a_char_text_keeps_its_record_of_fixed_size():
  """`length` counts bytes of UTF-8 and the NUL that C reads up to; a full one still reads."""
  s = Struct("dev", Field(Type.char, "model", length=8), Field(Type.uint8, "rev"))
  record = {"model": "żółw", "rev": 1} # 7 bytes of UTF-8, the NUL the 8th
  assert s.size == 9 and s.decode(s.encode(record)) == record
  full = b"abcdefgh\x02" # as a writer that leaves no NUL puts it
  assert s.decode(full)["model"] == "abcdefgh" and s.decode(full, raw=True)["model"] == b"abcdefgh"

@pytest.mark.parametrize("value, error", [
  ("abcdefgh", ValueError), # 8 bytes leave its NUL no room
  ("żółwik", ValueError), # 6 letters, 9 bytes of UTF-8
  ("ab\0c", ValueError), # the NUL that ends it
  (7, TypeError),
])
def a_char_text_refuses_what_its_bytes_cannot_hold_by_name(value, error):
  with pytest.raises(error, match="'model' of 'dev'"):
    Struct("dev", Field(Type.char, "model", length=8)).encode({"model": value})

def a_char_text_that_is_no_utf8_is_refused_by_name():
  with pytest.raises(ValueError, match="'model' of 'dev' holds no UTF-8"):
    Struct("dev", Field(Type.char, "model", length=8)).decode(b"\xff" + bytes(7))

def crc_travels_with_every_record():
  s = Struct("cf", Field(Type.uint16, "x"), crc=crc32_iso)
  run = s.encode({"x": 1}) + s.encode({"x": 2})
  assert s.records(run) == [{"x": 1}, {"x": 2}]
  assert len(run) == 2 * (2 + 4) # a crc behind each record, not one at the end

def a_bitfield_is_a_dict_of_bits():
  s = Struct("flags", Bitfield("st", [("on", 1), ("err", 1), ("mode", 6)]))
  data = {"st": {"on": 1, "err": 0, "mode": 42}}
  assert s.decode(s.encode(data)) == data

def a_bitfield_refuses_a_name_it_lacks_and_a_value_outside_its_bits():
  """A typo would pack its bit as 0 and -1 would pack as all ones, both without a word."""
  st = Bitfield("st", [("on", 1), ("mode", 6)])
  with pytest.raises(KeyError, match="onn"):
    st.encode({"onn": 1})
  for mode in (-1, 64):
    with pytest.raises(ValueError, match="mode"):
      st.encode({"mode": mode})
  with pytest.raises(TypeError, match="mode"):
    st.encode({"mode": 1.0}) # bits are counted, never measured

def a_bitfield_refuses_a_layout_it_cannot_pack():
  """
  A repeated name would fold two groups into one; bits past the integer would be lost;
  no group at all would be a byte on the wire that carries nothing.
  """
  with pytest.raises(ValueError):
    Bitfield("twice", [("mode", 4), ("mode", 4)])
  with pytest.raises(ValueError, match="bit group"):
    Bitfield("empty", [])
  for kind in (Type.uint8, Type.int16): # too narrow, signed
    with pytest.raises(ValueError):
      Bitfield("wide", [("count", 12)], type=kind)
  assert Bitfield("reg", [("on", 1)], type=Type.uint16).size == 2 # a 16-bit register, one bit used

def a_default_stands_in_for_a_missing_field():
  s = Struct("opt", Field(Type.uint8, "a"), Field(Type.uint8, "b", default=9))
  assert s.decode(s.encode({"a": 1})) == {"a": 1, "b": 9}

DECK = Struct("deck", Field(Type.uint8, "state", values=State),
  Bitfield("flags", [("mode", 4), ("fault", 4)], values={"mode": State}))

def an_enum_reads_its_members_and_keeps_a_number_it_lacks():
  """Members are numbers too; a newer firmware's state comes back as a number, never refused."""
  read = DECK.decode(DECK.encode({"state": State.Run, "flags": {"mode": 7, "fault": 2}}))
  assert read == {"state": 1, "flags": {"mode": 7, "fault": 2}}
  assert read["state"] is State.Run and read["flags"]["mode"] is State.Fault
  newer = DECK.decode(b"\x05\x05")
  assert newer == {"state": 5, "flags": {"mode": 5, "fault": 0}} and type(newer["state"]) is int
  assert DECK.decode(DECK.encode({"state": 1, "flags": {}}), raw=True) == {"state": 1, "flags": 0}

def an_enum_refuses_a_number_it_lacks_on_the_way_out():
  with pytest.raises(ValueError, match="'state' of 'deck' holds 5, not a State"):
    DECK.encode({"state": 5, "flags": {}})
  with pytest.raises(ValueError, match="'mode' holds 5, not a State"):
    DECK.encode({"state": 0, "flags": {"mode": 5}})

def a_record_key_the_struct_lacks_is_refused():
  """A typo would leave its field at the default and go out without a word."""
  s = Struct("modes", Field(Type.uint8, "a"), Field(Type.uint8, "mode", default=0))
  with pytest.raises(KeyError, match="mdoe"):
    s.encode({"a": 1, "mdoe": 3})

def a_string_holding_a_nul_is_refused():
  """The NUL ends a string on the wire, so what follows it would read as the next record."""
  with pytest.raises(ValueError, match="'t' of 'txt'"):
    Struct("txt", Field(Type.string, "t")).encode({"t": "a\0b"})

def a_string_that_is_no_utf8_is_refused_by_its_name():
  """Every read error names its field and struct, a byte that is no UTF-8 included."""
  with pytest.raises(ValueError, match="'t' of 'txt'"):
    Struct("txt", Field(Type.uint8, "kind"), Field(Type.string, "t")).decode(b"\x01\xff\x00")
  text = Struct("txt", Field(Type.uint8, "kind"), Field(Type.string, "t"))
  with pytest.raises(ValueError, match="'t' of 'txt'"):
    text.encode({"kind": 1, "t": "\ud800"}) # a lone surrogate, no UTF-8 either

@pytest.mark.parametrize("endian, order", [(Endian.little, "little"), (Endian.big, "big")])
def endian_mirrors_bytes(endian, order):
  s = Struct(f"e_{order}", Field(Type.uint16, "n"), endian=endian)
  assert s.encode({"n": 258}) == (258).to_bytes(2, order) # 258 == 0x0102
  assert s.decode(s.encode({"n": 258})) == {"n": 258}

def size_counts_every_byte_of_a_record():
  s = Struct("sized", Field(Type.uint8, "a"), crc=crc32_iso, align=4)
  assert s.size == len(s.encode({"a": 1})) == 8 # 1 byte, 3 of alignment, 4 of CRC
  assert Struct("loose", Field(Type.string, "t")).size is None

PRINTED = Struct("rec",
  Field(Type.int16, "t", "C", scale=10), Bitfield("f", [("a", 4)]), Padding(1))

@pytest.mark.parametrize("other", [
  Struct("rec", Field(Type.int16, "t", "C", scale=100), Bitfield("f", [("a", 4)]), Padding(1)), # scale
  Struct("rec", Field(Type.int16, "t", "C", scale=10, offset=1), Bitfield("f", [("a", 4)]), Padding(1)), # offset
  Struct("rec", Field(Type.int16, "t", "C", scale=10), Bitfield("f", [("a", 5)]), Padding(1)), # a bit width
  Struct("rec", Field(Type.int16, "t", "C", scale=10), Bitfield("f", [("a", 4)]), Padding(3)), # padding
  Struct("rec", Field(Type.int16, "t", "C", scale=10), Bitfield("f", [("a", 4)]), Padding(1), endian=Endian.big), # byte order
  Struct("rec", Field(Type.int16, "t", "C", scale=10), Bitfield("f", [("a", 4)]), Padding(1), crc=crc32_iso), # a crc
  Struct("rec", Field(Type.int16, "t", "C", scale=10), Bitfield("f", [("a", 4)]), Padding(1), align=4), # alignment
  Struct("rec", Field(Type.int16, "v", "C", scale=10), Bitfield("f", [("a", 4)]), Padding(1)), # a name
  Struct("rec", Field(Type.int16, "t", "C", scale=10), Bitfield("f", [("a", 4)], values={"a": State}), Padding(1)), # an enum
])
def a_fingerprint_moves_with_what_the_bytes_mean(other):
  assert other.fingerprint != PRINTED.fingerprint

def a_fingerprint_stays_with_the_words_around_the_bytes():
  """`doc`, `unit` and `default` leave it be, and `scale=10.0` is `scale=10`."""
  same = Struct("rec",
    Field(Type.int16, "t", "°C", scale=10.0, default=0, doc="board temperature"),
    Bitfield("f", [("a", 4)], doc="flags"), Padding(1), doc="one record")
  assert same.fingerprint == PRINTED.fingerprint
  assert Message({1: PRINTED, 2: POINT}).fingerprint == Message({2: POINT, 1: same}).fingerprint
  message = Message({1: PRINTED})
  define = f"#define REC_SCHEMA 0x{message.fingerprint:08X}u"
  assert define in message.export_c_header(prefix="REC")

def alignment_padding_roundtrips_each_record():
  # `records` consumes the padding `encode` appends behind each record
  s = Struct("aligned", Field(Type.uint8, "a"), Field(Type.uint16, "b"), align=4)
  recs = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
  assert s.records(b"".join(s.encode(rec) for rec in recs)) == recs

def members_keep_wire_order():
  """Padding and bitfields are members too: a walk over a struct meets the owner of every byte."""
  s = Struct("row",
    Field(Type.uint8, "a", "V", length=2), Padding(1), Bitfield("flags", [("on", 1)]),
  )
  assert [repr(member) for member in s.members] == [
    "Field(uint8, 'a', 'V', length=2)", "Padding(1)", "Bitfield('flags', [('on', 1)])",
  ]
  assert sum(member.size for member in s.members) == s.size == 4

#------------------------------------------------------------------------------------------ nesting

def a_struct_nests_as_a_field_byte_for_byte():
  """A nested struct is its members, as in C: the bytes of the flat record."""
  foc = Struct("foc", Field(Type.uint16, "seq"), Field(Type.int16, "iq"))
  nested = Struct("sample", Field(foc, "foc"), Field(Type.int16, "w"))
  flat = Struct("flat", Field(Type.uint16, "seq"), Field(Type.int16, "iq"), Field(Type.int16, "w"))
  record = {"foc": {"seq": 7, "iq": -3}, "w": 12}
  assert nested.encode(record) == flat.encode({"seq": 7, "iq": -3, "w": 12})
  assert nested.decode(nested.encode(record)) == record

def an_array_of_structs_is_a_list_of_dicts():
  xy = Struct("xy", Field(Type.int16, "x"), Field(Type.int16, "y"))
  path = Struct("path", Field(xy, "points", length=2))
  data = {"points": [{"x": 1, "y": 2}, {"x": -3, "y": 4}]}
  assert path.decode(path.encode(data)) == data

@pytest.mark.parametrize("tail", [{"crc": crc32_iso}, {"align": 4}])
def a_struct_with_a_tail_does_not_nest(tail):
  """A CRC inside a record checks nothing, and `align` pads a whole record."""
  with pytest.raises(ValueError):
    Field(Struct("inner", Field(Type.uint8, "a"), **tail), "inner")

def a_nested_struct_shares_its_hosts_byte_order():
  """Its bytes go out in the host's order, so a struct of another order would lie about itself."""
  big = Struct("big", Field(Type.uint16, "n"), endian=Endian.big)
  with pytest.raises(ValueError):
    Struct("host", Field(big, "inner"))
  host = Struct("host", Field(big, "inner"), endian=Endian.big)
  assert host.encode({"inner": {"n": 258}}) == b"\x01\x02"

#--------------------------------------------------------------------------------------------- wire

def message_routes_by_code():
  pos = Struct("pos", Field(Type.int16, "x"), Field(Type.int16, "y"))
  temp = Struct("temp", Field(Type.float, "t"))
  message = Message({1: pos, 2: temp})
  body = message.encode({"pos": [{"x": -3, "y": 7}], "temp": [{"t": 21.5}]})
  assert message.decode(body) == {"pos": [{"x": -3, "y": 7}], "temp": [{"t": 21.5}]}
  assert message.structs[1] is pos

def a_message_takes_lists_of_records_only():
  """One shape: a lone dict would read either as a record or as a dict of records."""
  message = Message({1: Struct("pos", Field(Type.int16, "x"))})
  with pytest.raises(TypeError):
    message.encode({"pos": {"x": 1}})

def block_header_is_code_then_size():
  pair = Struct("pair", Field(Type.uint16, "a"), Field(Type.uint16, "b"))
  block = Message({1: pair}).encode({"pair": [{"a": 0x1234, "b": 0x5678}]})
  assert block == bytes.fromhex("0100 0400 3412 7856")
  assert pair.records(block[4:]) == [{"a": 0x1234, "b": 0x5678}]

def a_block_is_read_out_of_its_declared_size():
  """A lying size header must not walk into the next block and desynchronise the stream."""
  temp = Struct("block_temp", Field(Type.uint16, "v"))
  hum = Struct("block_hum", Field(Type.uint16, "v"))
  message = Message({71: temp, 72: hum})
  good = message.encode({"block_temp": [{"v": 11}, {"v": 22}], "block_hum": [{"v": 33}]})
  assert message.decode(good) == {"block_temp": [{"v": 11}, {"v": 22}], "block_hum": [{"v": 33}]}

  over = bytearray(good); over[2] = 200
  with pytest.raises(ValueError, match="Block declares"):
    message.decode(bytes(over))

  partial = bytearray(good); partial[2] = 5
  with pytest.raises(ValueError):
    message.decode(bytes(partial))

def a_code_belongs_to_its_message():
  """Two protocols may both use code 1; bytes of a code a message lacks raise `ValueError`."""
  first = Struct("first", Field(Type.uint8, "a"))
  second = Struct("second", Field(Type.uint8, "b"))
  one, two = Message({1: first}), Message({1: second})
  assert one.decode(one.encode({"first": [{"a": 1}]})) == {"first": [{"a": 1}]}
  assert two.decode(two.encode({"second": [{"b": 2}]})) == {"second": [{"b": 2}]}
  with pytest.raises(ValueError):
    Message({1: first, 2: first}) # one name, two codes: `encode` could not tell which
  with pytest.raises(ValueError):
    Message({9: second}).decode(one.encode({"first": [{"a": 1}]}))

def a_message_takes_the_byte_order_of_its_structs():
  """The order belongs to the structs; mixed, one of them would go out in the other's order."""
  big = Struct("big", Field(Type.uint16, "n"), endian=Endian.big)
  little = Struct("little", Field(Type.uint16, "n"))
  with pytest.raises(ValueError):
    Message({1: big, 2: little})
  assert Message({1: big}).encode({"big": [{"n": 258}]}) == bytes.fromhex("0001 0002 0102")

def a_frame_orders_its_length_itself():
  """The length belongs to the envelope, little as in `FRAME_t` unless its link says otherwise."""
  assert Frame().encode(b"ab")[2:4] == b"\x06\x00" # 2 bytes of body, 4 of crc
  assert Frame(endian=Endian.big).encode(b"ab")[2:4] == b"\x00\x06"

def a_frame_carries_a_message_the_caller_joins():
  """Envelope and body are two pieces: dicts in and out, the wire cut anywhere between."""
  pos = Struct("pos", Field(Type.int16, "x"), Field(Type.int16, "y"))
  temp = Struct("temp", Field(Type.float, "t"))
  message, link = Message({1: pos, 2: temp}), Frame(limit=64)
  data = {"pos": [{"x": 1, "y": 2}, {"x": 3, "y": 4}], "temp": [{"t": 21.5}]}
  wire = link.encode(message.encode(data)) * 2
  bodies = list(link.feed(wire[:7])) + list(link.feed(wire[7:]))
  assert [message.decode(body) for body in bodies] == [data, data] and link.errors == 0

def a_body_its_message_cannot_read_stops_nothing_behind_it():
  """A sender of another layout: the caller refuses its body, the frames behind still come."""
  mine = Message({1: Struct("mine", Field(Type.uint8, "v"))})
  other = Message({9: Struct("other", Field(Type.uint8, "v"))})
  link = Frame()
  sent = [(mine, "mine", 1), (other, "other", 2), (mine, "mine", 3)]
  wire = b"".join(link.encode(message.encode({name: [{"v": v}]})) for message, name, v in sent)
  read, refused = [], 0
  for body in link.feed(wire):
    try: read.append(mine.decode(body))
    except ValueError: refused += 1
  assert read == [{"mine": [{"v": 1}]}, {"mine": [{"v": 3}]}] and refused == 1 and link.errors == 0

def a_body_over_the_limit_is_refused_at_the_sender():
  """The receiver drops it as structural nonsense, so the sender is the one left to say so."""
  link = Frame(limit=4)
  with pytest.raises(ValueError, match="limit"):
    link.encode(b"12345")
  assert list(Frame(limit=4).feed(link.encode(b"1234"))) == [b"1234"]

def an_empty_body_is_a_frame():
  """A ping carries nothing; what `encode` makes, `feed` must take."""
  link = Frame(limit=8)
  assert list(link.feed(link.encode(b""))) == [b""]
  assert link.errors == 0

def frame_matches_the_c_layer():
  # Captured from `FRAME_Send` of `demo/com/frame` built on the host,
  # the block above as payload and `crc32_iso`;
  # `zlib.crc32` of that payload gives the same four bytes.
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
  # A sync pair in noise between frames, with a plausible length behind it
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

def frame_pending_closes_the_byte_count():
  """Every fed byte is accounted for: yielded, dropped, or still waiting."""
  frame = Frame(limit=64)
  good = frame.encode(b"12345678")
  bad = bytearray(good); bad[6] ^= 0xFF
  wire = good + bytes(bad) + good[:5]
  assert list(frame.feed(wire)) == [b"12345678"]
  assert frame.pending == 5 # the last frame, still on its way
  assert len(wire) - len(good) - frame.pending == len(bad)
  assert frame.errors == 1

#----------------------------------------------------------------------------------------- C header

def the_header_mirrors_the_wire():
  """Padding and the crc tail are bytes on the wire, so they are members in C."""
  s = Struct("hdr", Field(Type.uint16, "a"), Field(Type.uint8, "b"), crc=crc32_iso, align=4)
  assert len(s.encode({"a": 1, "b": 2})) == 8
  header = s.export_c_header()
  assert "uint8_t _align[1];" in header and "uint8_t crc[4];" in header
  loose = Struct("txt", Field(Type.uint8, "kind"), Field(Type.string, "t"), crc=crc32_iso)
  assert "_align" not in loose.export_c_header() and "Variable size" in loose.export_c_header()

def a_natural_layout_is_not_packed_and_every_offset_is_asserted():
  """Only a layout C would pad is packed; the asserts hold either way."""
  natural = Struct("nat",
    Field(Type.uint16, "a"), Field(Type.uint16, "b"), Field(Type.uint32, "c"),
  )
  header = natural.export_c_header()
  assert "packed" not in header
  assert '_Static_assert(sizeof(nat_t) == 8, "nat_t is 8B on the wire");' in header
  assert '_Static_assert(offsetof(nat_t, c) == 4, "nat_t.c at 4 on the wire");' in header
  odd = Struct("odd", Field(Type.uint8, "a"), Field(Type.uint32, "b"))
  assert "typedef struct __attribute__((packed)) {" in odd.export_c_header()

def a_message_header_names_codes_block_and_types_after_its_module():
  foc = Struct("foc_dump", Field(Type.uint16, "seq"), Field(Type.int16, "iq"))
  sample = Struct("sample", Field(foc, "foc"), Field(Type.int16, "w_hat"))
  state = Struct("state", Bitfield("flags", [("mode", 4), ("exit", 4)]))
  extern = {foc: ("FOC_Dump_t", "foc.h")}
  message = Message({1: sample, 2: state})
  lines = message.export_c_header("diag/rec_wire.h", "REC", extern).splitlines()
  assert lines[0] == "// diag/rec_wire.h" and "#ifndef REC_WIRE_H_" in lines
  assert "#define REC_CODE_SAMPLE 1" in lines and "} REC_Block_t;" in lines
  assert "} REC_Sample_t;" in lines and "} REC_StateFlags_t;" in lines
  assert '#include "foc.h"' in lines and "} FOC_Dump_t;" not in lines # defined in `foc.h` alone
  assert '_Static_assert(sizeof(FOC_Dump_t) == 4, "FOC_Dump_t is 4B on the wire");' in lines
  assert all(len(line) == 99 for line in lines if line.startswith("//--"))

def a_check_past_99_characters_puts_its_message_on_a_line_of_its_own():
  """A header line stays within 99: a long member name would push its offset check past it."""
  s = Struct("drive", Field(Type.uint16, "entry_timeout_s_of_the_closing_gate"))
  lines = s.export_c_header("dev/drive.h").splitlines()
  assert all(len(line) <= 99 for line in lines)
  at = lines.index("_Static_assert(offsetof(drive_t, entry_timeout_s_of_the_closing_gate) == 0,")
  assert lines[at + 1] == '  "drive_t.entry_timeout_s_of_the_closing_gate at 0 on the wire");'

def a_c_type_keeps_an_acronym_in_capitals():
  for name, kind in (("foc_dump", "REC_FocDump_t"), ("FOC_dump", "REC_FOCDump_t")):
    assert f"}} {kind};" in Struct(name, Field(Type.uint8, "a")).export_c_header(prefix="REC")

def a_note_gives_the_unit_only_where_c_holds_the_value_in_it():
  """A scaled field holds raw counts in C: its unit belongs to the decoded value."""
  s = Struct("meter",
    Field(Type.uint16, "ms", "ms"), Field(Type.int16, "bus", "V", scale=10, doc="raw DC bus"),
  )
  header = s.export_c_header()
  assert "// [ms]" in header and "// raw DC bus" in header and "[V]" not in header

def a_bitfield_note_reaches_c():
  s = Struct("state", Bitfield("flags", [("mode", 4)], doc="`mode` as the drive numbers it"))
  assert "  state_flags_t flags; // `mode` as the drive numbers it" in s.export_c_header()

def a_note_of_lines_or_too_long_to_trail_goes_above_its_member():
  """
  A header line stays within 99: a note past it goes above its member,
  a declaration whose column would push the other notes past it gives the column up,
  and a note of several lines keeps the breaks its author put where the sentence pauses.
  """
  gate = "closing_gate_entry_timeout_at_the_far_end_of_the_drive_run_s"
  bus = "raw counts of the drive's own ADC,\nnever scaled on the wire"
  s = Struct("drive",
    Field(Type.uint16, "seq", doc="first sample of the frame, its clock on the wire"),
    Field(Type.uint16, gate, doc="gate timeout"),
    Field(Type.int16, "bus", doc=bus),
  )
  lines = s.export_c_header().splitlines()
  assert all(len(line) <= 99 for line in lines)
  assert "  uint16_t seq; // first sample of the frame, its clock on the wire" in lines # alone
  at = lines.index(f"  uint16_t {gate};")
  assert lines[at - 1] == "  // Gate timeout" # above, a comment line opens with a capital
  at = lines.index("  int16_t bus;")
  above = ["  // Raw counts of the drive's own ADC,", "  // never scaled on the wire"]
  assert lines[at - 2:at] == above

def notes_line_up_two_spaces_past_the_longest_line_that_has_one():
  """A line without a note, however long, does not push the column of notes."""
  s = Struct("state", Field(Type.uint16, "seq", doc="first sample"),
    Bitfield("flags", [("mode", 4)]), Field(Type.int8, "hand", "ticks"))
  lines = s.export_c_header().splitlines()
  noted = [line for line in lines if line.startswith(("  uint16_t seq;", "  int8_t hand;"))]
  assert [line.index("//") for line in noted] == [len("  uint16_t seq;") + 2] * 2

def a_note_standing_alone_takes_one_space():
  """A column of one is padding: a lone note sits one space behind its line."""
  s = Struct("state", Field(Type.uint8, "b", doc="the only note"),
    Bitfield("flags_of_the_whole_drive", [("mode", 4)]))
  assert "  uint8_t b; // the only note" in s.export_c_header().splitlines()

def a_struct_doc_stands_above_its_c_type():
  s = Struct("deck", Field(Type.uint8, "a"), doc="one deck of the set,\nwhat it plays")
  lines = s.export_c_header().splitlines()
  at = lines.index("typedef struct {")
  above = ["// One deck of the set,", "// what it plays"] # a comment line opens with a capital
  assert lines[at - 2:at] == above

def a_char_text_is_char_in_c_and_bytes_in_numpy():
  """C learns the text ends in a NUL, so its string functions take it as it is."""
  np = pytest.importorskip("numpy")
  s = Struct("dev", Field(Type.char, "model", length=8, doc="model"), Field(Type.uint8, "rev"))
  assert "  char model[8]; // model [UTF-8, NUL-terminated]" in s.export_c_header()
  rows = np.frombuffer(s.encode({"model": "ab", "rev": 1}), s.dtype())
  assert rows["model"][0] == b"ab" and s.dtype().itemsize == s.size

def an_enum_gives_c_its_constants_and_the_field_keeps_its_width():
  """A C `enum` is as wide as its compiler likes, so the field stays `uint8_t`."""
  lines = Message({1: DECK}).export_c_header(prefix="DECKS").splitlines()
  assert ["  DECKS_State_Idle = 0,", "  DECKS_State_Run = 1,", "  DECKS_State_Fault = 7,"] == [
    line for line in lines if line.startswith("  DECKS_State_")]
  assert lines.count("} DECKS_State_t;") == 1 and "  uint8_t state;" in lines # once for both

class Mode(IntEnum):
  """Names as Python writes them, one of them a C keyword."""
  manual = 0
  auto = 1

def an_enum_takes_its_c_names_as_a_struct_does():
  """PascalCase behind the module: `auto` is a keyword alone, never as `REC_Mode_Auto`."""
  header = Struct("switch", Field(Type.uint8, "mode", values=Mode)).export_c_header(prefix="REC")
  assert "  REC_Mode_Auto = 1," in header and "} REC_Mode_t;" in header
  assert "} REC_Switch_t;" in header # a struct named like a keyword as well

GEO_H = """\
// geo.h

#ifndef GEO_H_
#define GEO_H_

#include <stdint.h>

typedef struct {
  int16_t x;
  int16_t y;
} GEO_Point_t;

typedef struct {
  uint8_t kind;
  uint8_t spare;
  uint16_t code;
} GEO_Item_t;

#endif
"""

ITEM = Struct("item", Field(Type.uint8, "kind"), Padding(1), Field(Type.uint16, "code"))
EDGES = Message({ # every layout the exporter writes its own way
  1: Struct("held", Field(ITEM, "item"), Field(Type.uint32, "stamp")), # a type from `extern` naming its filler itself
  2: Struct("odd", Field(Type.uint8, "kind"), Field(Type.uint32, "stamp"), align=4, crc=crc32_iso), # packed, an alignment tail, a crc
  3: Struct("blob", Field(Type.uint8, "kind"), Field(Type.bytes, "data")), # a length before a flexible array
  4: Struct("note", Field(Type.uint8, "kind", doc="a note of two lines,\nas its author broke it"), Field(Type.string, "text")), # a string behind a member
  5: Struct("deck", Field(Type.char, "label", length=6), Field(Type.uint8, "state", values=State), Bitfield("flags", [("mode", 4)], values={"mode": State}), doc="one deck of the set"), # a text, one enum twice, a doc
})

MAIN_C = """\
#include <stdio.h>
#include <string.h>

#include "edge_wire.h"
#include "link_wire.h"

static const unsigned char wire[] = {WIRE};

int main(void)
{
  LINK_Block_t block;
  LINK_Sample_t s;
  memcpy(&block, wire, sizeof block);
  memcpy(&s, wire + sizeof block, sizeof s);
  printf("%d %u %u ", block.code == LINK_CODE_SAMPLE, block.size, (unsigned)s.time);
  printf("%d %d %d %d ", s.pos[0].x, s.pos[0].y, s.pos[1].x, s.pos[1].y);
  printf("%d %u %u", s.temp, s.flags.mode, s.flags.fault);
  return 0;
}
"""

C_FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
COMPILERS = { # the three of the plan, each test skipping where its compiler is missing
  "gcc": ["gcc"],
  "cortex-m4": ["arm-none-eabi-gcc", "-mcpu=cortex-m4", "-mthumb"],
  "wsl": ["wsl", "-e", "gcc"],
}

class CSide:
  """The headers in C, kept out of reach of `python_functions = ["*"]` collection."""
  @staticmethod
  def build(folder:Path, compiler:str, *args:str) -> None:
    """Write the readme's header, the edges' and a `main.c` into `folder`; a warning fails."""
    command = COMPILERS[compiler]
    try: found = subprocess.run([*command, "--version"], capture_output=True).returncode == 0
    except FileNotFoundError: found = False
    if not found: pytest.skip(f"no {compiler} compiler")
    link = Message({1: SAMPLE})
    header = link.export_c_header("dev/link_wire.h", "LINK", {POINT: ("GEO_Point_t", "geo.h")})
    edges = EDGES.export_c_header("dev/edge_wire.h", "EDGE", {ITEM: ("GEO_Item_t", "geo.h")})
    wire = ", ".join(str(byte) for byte in link.encode({"sample": [RECORD]}))
    (folder / "geo.h").write_text(GEO_H, encoding="utf-8")
    (folder / "link_wire.h").write_text(header, encoding="utf-8")
    (folder / "edge_wire.h").write_text(edges, encoding="utf-8")
    (folder / "main.c").write_text(MAIN_C.replace("WIRE", wire), encoding="utf-8")
    build = subprocess.run([*command, *C_FLAGS, *args], cwd=folder, capture_output=True)
    assert build.returncode == 0, build.stderr.decode(errors="replace")

@pytest.mark.parametrize("compiler", COMPILERS)
def the_headers_compile_without_a_warning(compiler, tmp_path):
  CSide.build(tmp_path, compiler, "-c", "main.c", "-o", "main.o")

def a_type_from_extern_is_checked_by_the_names_the_schema_gives_it():
  """A C type of its own names its filler itself: `GEO_Item_t` has `spare`, not `_pad1`."""
  header = EDGES.export_c_header(prefix="EDGE", extern={ITEM: ("GEO_Item_t", "geo.h")})
  assert "offsetof(GEO_Item_t, code) == 2" in header and "_pad1" not in header

def c_reads_the_bytes_python_wrote(tmp_path):
  """A shared vector: C copies the encoded block into the generated types and prints the fields."""
  CSide.build(tmp_path, "gcc", "main.c", "-o", "main")
  run = subprocess.run([str(tmp_path / "main")], capture_output=True, text=True)
  assert run.stdout == "1 16 1200 1 -2 3 4 234 3 9"

def a_fingerprint_is_the_same_number_release_after_release():
  """Firmware keeps it as `PREFIX_SCHEMA`: a rework of `_shape` that moves it shows here."""
  assert SAMPLE.fingerprint == 0x7E71EB4E and EDGES.fingerprint == 0x93750228

#-------------------------------------------------------------------------------------------- numpy

def dtype_reads_encoded_records_as_their_raw_values():
  """Every byte of a record is in the dtype, so rows read in bulk land on the right fields."""
  np = pytest.importorskip("numpy")
  xy = Struct("xy", Field(Type.int16, "x"), Field(Type.int16, "y"))
  s = Struct("row",
    Field(Type.uint16, "seq"), Field(Type.int16, "bus", "V", scale=10),
    Bitfield("flags", [("mode", 4), ("fault", 4)]), Padding(1), Field(Type.float, "temp"),
    Field(xy, "path", length=2),
    align=4, crc=crc32_iso,
  )
  records = [{"seq": i, "bus": 24.1, "flags": {"mode": 3, "fault": i}, "temp": 21.5,
    "path": [{"x": i, "y": -i}] * 2} for i in range(3)]
  rows = np.frombuffer(b"".join(s.encode(record) for record in records), s.dtype())
  assert s.dtype().itemsize == s.size == len(s.encode(records[0]))
  assert rows["seq"].tolist() == [0, 1, 2] and rows["bus"].tolist() == [241] * 3 # raw, ×10
  assert rows["flags"].tolist() == [3, 19, 35] and rows["path"]["y"][:, 1].tolist() == [0, -1, -2]
  assert rows["crc"][0] == crc32_iso.checksum(s.encode(records[0])[:-4])

def dtype_refuses_a_record_of_varying_size():
  pytest.importorskip("numpy")
  with pytest.raises(ValueError):
    Struct("txt", Field(Type.string, "t")).dtype()

#----------------------------------------------------------------------------------------- refusals

@pytest.mark.parametrize("struct", [
  Struct("text_first", Field(Type.string, "t"), Field(Type.uint8, "a")), # C takes it only last
  Struct("spaced", Field(Type.uint8, "two words")), # no name C can take
  Struct("keyword", Field(Type.uint8, "default")), # a keyword
  Struct("c23", Field(Type.uint8, "bool")), # a keyword since C23, GCC's default
  Struct("reserved", Field(Type.uint8, "_Mode")), # `_X` is the compiler's
  Struct("length", Field(Type.uint8, "data_len"), Field(Type.bytes, "data")), # the length of `data`
  Struct("filler", Field(Type.uint8, "_pad1"), Padding(1)), # the name of the padding
  Struct("log", Field(Type.string, "text")), # a flexible array needs a member before it
  Struct("noted", Field(Type.uint8, "a", doc="n" * 95)), # a note line past 99 in C
  Struct("broken", Field(Type.uint8, "a", doc="short\n" + "n" * 95)), # one its author broke too
  Struct("described", Field(Type.uint8, "a"), doc="d" * 97), # a doc line of the type past 99
  Struct("null", Field(Type.uint8, "NULL")), # `<stddef.h>` makes it `((void*)0)`
  Struct("limit", Field(Type.uint8, "INT8_MAX")), # `<stdint.h>` makes it a number
  Struct("big", Field(Type.uint16, "a"), endian=Endian.big), # C holds the target's order
  Struct("deck-a", Field(Type.uint8, "a")), # no C type comes of the name
  Struct("moded", Field(Type.uint8, "state", values=State)), # enum constants of no module
])
def what_no_c_struct_can_mirror_is_refused(struct):
  with pytest.raises(ValueError):
    struct.export_c_header()

def a_path_must_give_an_include_guard():
  """The guard comes from the file's name, and no C macro is named `2D_H_`."""
  with pytest.raises(ValueError):
    Struct("one", Field(Type.uint8, "a")).export_c_header("dev/2d.h")

@pytest.mark.parametrize("structs", [
  {1: Struct("state", Field(Struct("state", Field(Type.uint8, "a")), "inner"))}, # `REC_State_t` for both
  {1: Struct("state", Bitfield("flags", [("on", 1)])), 2: Struct("state_flags", Field(Type.uint8, "a"))}, # `REC_StateFlags_t`
  {1: Struct("state", Field(Type.uint8, "a")), 2: Struct("State", Field(Type.uint8, "a"))}, # `REC_CODE_STATE`
  {1: Struct("block", Field(Type.uint8, "a"))}, # `REC_Block_t`, the header of every block
  {1: Struct("deck", Field(Type.uint8, "mode", values=IntEnum("Twin", {"off": 0, "Off": 1})))}, # `REC_Twin_Off`
])
def a_header_never_defines_a_name_twice(structs):
  with pytest.raises(ValueError, match="twice"):
    Message(structs).export_c_header(prefix="REC")

@pytest.mark.parametrize("name", ["size", "int16", "uint_least8"])
def a_type_the_includes_define_is_never_defined_again(name):
  """Without a prefix, a struct `size` would be a second `size_t` beside that of `<stddef.h>`."""
  with pytest.raises(ValueError, match="twice"):
    Struct(name, Field(Type.uint8, "a")).export_c_header()

def a_message_header_needs_its_module_prefix():
  """Codes and the block type are module defines in C, named after the module."""
  with pytest.raises(ValueError):
    Message({1: Struct("one", Field(Type.uint8, "a"))}).export_c_header()

def a_prefix_and_an_extern_type_are_c_names():
  """Both go into the header as they are given."""
  message = Message({1: Struct("one", Field(POINT, "p"))})
  for prefix, extern in (("REC-X", None), ("REC", {POINT: ("geo point", "geo.h")})):
    with pytest.raises(ValueError):
      message.export_c_header(prefix=prefix, extern=extern)

def a_field_takes_a_type_or_a_struct():
  """A type named in a string would pass every check and fail at the first record."""
  with pytest.raises(TypeError):
    Field("uint8", "a")

def a_member_and_a_struct_need_a_name():
  """A member's name is its key in the record; a struct's keys its blocks and names its C type."""
  for member in (Field(Type.uint8, ""), Bitfield("", [("on", 1)])):
    with pytest.raises(ValueError):
      Struct("named", member)
  with pytest.raises(ValueError):
    Struct("")

def a_member_name_stands_for_one_member():
  """One name, one key: a field and a bitfield cannot share it, nor a field and the crc tail."""
  with pytest.raises(ValueError):
    Struct("dup", Field(Type.uint8, "flags"), Bitfield("flags", [("on", 1)]))
  with pytest.raises(ValueError):
    Struct("tail", Field(Type.uint8, "crc"), crc=crc32_iso) # the tail is `crc` in C and numpy
  assert Struct("free", Field(Type.uint8, "crc")).size == 1 # without a tail the name is free

class Wide(IntEnum):
  """Names whose numbers a `uint8` cannot hold."""
  Small = 1
  Huge = 300

@pytest.mark.parametrize("make, error", [
  (lambda: Field(Type.uint8, "state", values=dict), TypeError), # no IntEnum
  (lambda: Field(Type.float, "state", values=State), ValueError), # an enum names whole numbers
  (lambda: Field(Type.uint8, "state", values=State, scale=10), ValueError), # raw ones, unscaled
  (lambda: Field(Type.uint8, "state", values=Wide), ValueError), # 300 is past uint8
  (lambda: Bitfield("flags", [("mode", 2)], values={"mode": State}), ValueError), # 7 is past 2 bits
  (lambda: Bitfield("flags", [("mode", 4)], values={"mod": State}), KeyError), # no such group
])
def an_enum_that_cannot_name_its_numbers_is_refused_where_it_is_made(make, error):
  with pytest.raises(error):
    make()

def what_a_uint16_length_cannot_count_is_refused():
  """A block, a bytes field and a frame each count their bytes in 16 bits."""
  big = Struct("big", Field(Type.uint32, "a", length=16384))
  with pytest.raises(ValueError, match="'big'"):
    Message({1: big}).encode({"big": [{"a": [0] * 16384}]})
  with pytest.raises(ValueError, match="'data'"):
    Struct("blob", Field(Type.bytes, "data")).encode({"data": bytes(65536)})
  with pytest.raises(ValueError):
    Frame(limit=65532) # with the 4 bytes of its crc, one past 65535
  assert Frame(limit=65531).limit == 65531

def decoding_a_struct_short_of_its_padding_raises():
  """Padding and alignment skip bytes without reading them, so a short record would decode fine."""
  s = Struct("short_pad", Field(Type.uint8, "a"), Padding(3))
  with pytest.raises(ValueError, match="cut short"):
    s.decode(b"\x01")
  assert s.decode(b"\x01\x00\x00\x00") == {"a": 1}

@pytest.mark.parametrize("make", [
  lambda: Struct("empty"), # C has no empty struct, and no run of empty records ends
  lambda: Struct("unaligned", Field(Type.uint8, "a"), align=0),
  lambda: Padding(0), # C has no zero-length array
  lambda: Bitfield("zero", [("a", 0)]), # nor a named bit group of no width
  lambda: Field(Type.uint8, "none", length=0), # no bytes, yet one value would go out
  lambda: Field(Type.string, "text", length=2), # a string sizes itself
  lambda: Field(Type.bytes, "data", scale=10), # no number to scale
  lambda: Field(POINT, "pos", offset=1), # nor in a struct
  lambda: Field(Type.char, "text", length=8, scale=10), # nor in a text
  lambda: Field(Type.char, "letter"), # a text and its NUL take 2 bytes at least
  lambda: Field(Type.int16, "flat", scale=0), # a read would divide by it
  lambda: Field(Type.int16, "text", scale="10"), # a string repeats instead of scaling
  lambda: Field(Type.int16, "shift", offset="1"),
  lambda: Field(Type.int16, "half", length=2.0), # `a[2.0]` in C
  lambda: Field(Type.int16, "flag", length=True),
  lambda: Padding(1.5),
  lambda: Struct("half", Field(Type.uint8, "a"), align=1.5),
  lambda: Bitfield("half", [("a", 1.5)]),
  lambda: Field(Type.uint8, "pair", length=2, default=0), # one value where two go out
  lambda: Field(Type.uint8, "wide", default=300), # past its type
])
def a_layout_the_bytes_would_contradict_is_refused_where_it_is_made(make):
  """A default is checked against its own field: in a struct it is encoded once, as it is made."""
  with pytest.raises((ValueError, TypeError)):
    made = make()
    if isinstance(made, Field): Struct("host", made)

@pytest.mark.parametrize("make", [
  lambda: Struct("order", Field(Type.uint8, "a"), endian="<"),
  lambda: Struct("guard", Field(Type.uint8, "a"), crc=32),
  lambda: Bitfield("kind", [("a", 1)], type="uint8"),
  lambda: Frame(crc="crc32"),
  lambda: Frame(endian=">"),
  lambda: Message({1: "sample"}), # a struct's name, not the struct
])
def a_part_of_the_wrong_kind_is_refused_where_it_is_made(make):
  """A plain string or number in its place would fail only at the first record, unnamed."""
  with pytest.raises(TypeError):
    make()

def a_block_code_is_an_integer():
  """Keys read from JSON are strings, and the code "1" would never meet a 1 on the wire."""
  with pytest.raises(TypeError):
    Message({"1": Struct("one", Field(Type.uint8, "a"))})

def crc_detects_corruption():
  s = Struct("guarded", Field(Type.uint16, "n"), crc=crc32_iso)
  frame = s.encode({"n": 0xBEEF})
  assert s.decode(frame) == {"n": 0xBEEF}
  for at in (0, -1): # a flipped payload byte, a flipped crc byte
    corrupt = bytearray(frame); corrupt[at] ^= 0xFF
    with pytest.raises(ValueError):
      s.decode(bytes(corrupt))

def missing_required_field_raises():
  s = Struct("req", Field(Type.uint8, "a"))
  with pytest.raises(KeyError):
    s.encode({})

@pytest.mark.parametrize("kind, value", [
  (Type.int16, 400), # 40000 is past int16
  (Type.int16, float("inf")), # no integer holds it
  (Type.int16, float("nan")),
  (Type.float, 1e39), # past FLT_MAX
])
def a_value_its_type_cannot_hold_is_refused_by_the_field_name(kind, value):
  s = Struct("range", Field(Type.uint8, "ok"), Field(kind, "temp", scale=100))
  with pytest.raises(ValueError, match="temp"):
    s.encode({"ok": 1, "temp": value})

@pytest.mark.parametrize("value", ["7", None, b"\x07", [7]])
def a_number_field_refuses_what_is_no_number_by_its_name(value):
  """Arithmetic on the scale would raise first, naming an operand instead of the field."""
  s = Struct("state", Field(Type.uint16, "seq"), Field(Type.int16, "bus", "V", scale=10))
  with pytest.raises(TypeError, match="'bus' of 'state'"):
    s.encode({"seq": 1, "bus": value})

MIXED = Struct("mixed", # every member of fixed size in one record, its tail included
  Field(Type.uint16, "seq"),
  Field(Type.int16, "temp", "°C", scale=10, offset=-5, default=20.0),
  Field(Type.float, "gain", length=2),
  Field(Type.double, "ratio"),
  Field(POINT, "pos", length=2),
  Bitfield("flags", [("mode", 4), ("fault", 12)]),
  Padding(2),
  crc=crc32_iso, align=8,
)
MIXED_RECORD = {"seq": 1, "gain": [1.0, 2.0], "ratio": 0.5, "pos": [{"x": 1, "y": 2}] * 2,
  "flags": {"mode": 1, "fault": 2}}

def a_record_of_every_kind_reads_back_as_it_was_written():
  rng = random.Random(7)
  for _ in range(200):
    record = {
      "seq": rng.randrange(65536), "temp": rng.randrange(-3000, 3000) / 10,
      "gain": [rng.uniform(-1e3, 1e3), rng.uniform(-1, 1)], "ratio": rng.uniform(-1e9, 1e9),
      "pos": [{"x": rng.randrange(-99, 99), "y": rng.randrange(-99, 99)} for _ in range(2)],
      "flags": {"mode": rng.randrange(16), "fault": rng.randrange(4096)},
    }
    if rng.random() < 0.3: del record["temp"] # the default stands in
    data = MIXED.encode(record)
    read = MIXED.decode(data)
    assert read["temp"] == record.get("temp", 20.0) and read["pos"] == record["pos"]
    assert MIXED.encode(read) == data and MIXED.records(data * 3) == [read] * 3

@pytest.mark.parametrize("change, name", [
  ({"seq": "7"}, "'seq' of 'mixed'"), # no number
  ({"seq": None}, "'seq' of 'mixed'"),
  ({"seq": [7]}, "'seq' of 'mixed'"), # one value, not a list
  ({"seq": 70000}, "'seq' of 'mixed'"), # past uint16
  ({"seq": float("nan")}, "'seq' of 'mixed'"),
  ({"gain": [1.0]}, "'gain' of 'mixed'"), # two items
  ({"gain": (1.0, 2.0, 3.0)}, "'gain' of 'mixed'"),
  ({"gain": b"\x00\x00"}, "'gain' of 'mixed'"),
  ({"pos": {"x": 1, "y": 2}}, "'pos' of 'mixed'"), # a list of two points
  ({"pos": [{"x": 1, "z": 2}] * 2}, "'point' has no z"), # a key the point lacks
  ({"flags": {"mode": 16}}, "'mode'"), # past its 4 bits
  ({"flags": {"mod": 1}}, "'flags' has no mod"),
  ({"sequence": 1}, "'mixed' has no sequence"), # a key the record lacks
])
def a_record_off_its_layout_is_refused_by_the_name_of_what_is_off(change, name):
  with pytest.raises((TypeError, ValueError, KeyError), match=name):
    MIXED.encode({**MIXED_RECORD, **change})

def a_record_cut_short_is_refused_by_the_member_it_cuts():
  data = MIXED.encode(MIXED_RECORD)
  with pytest.raises(ValueError, match="'gain' of 'mixed' is cut short"):
    MIXED.decode(data[:5])
  with pytest.raises(ValueError, match="'y' of 'point' is cut short"):
    MIXED.decode(data[:22]) # inside the first of the two points
  with pytest.raises(ValueError, match="CRC"):
    MIXED.decode(data[:-1]) # the crc short of a byte

def a_cut_in_padding_says_so_by_the_nearest_name():
  """Padding names no member: the record says so, or the field of a host that holds it."""
  s = Struct("text", Field(Type.string, "t"), Field(Type.uint8, "a"), Padding(3))
  with pytest.raises(ValueError, match="'text' is cut short in its padding"):
    s.decode(s.encode({"t": "ab", "a": 1})[:5])
  inner = Struct("inner", Field(Type.uint8, "a"), Padding(1))
  host = Struct("host", Field(inner, "in"), Field(Type.uint8, "b"))
  with pytest.raises(ValueError, match="'in' of 'host' is cut short"):
    host.decode(host.encode({"in": {"a": 1}, "b": 2})[:1]) # in the padding of `inner`

def a_blank_line_of_a_note_leaves_nothing_behind_its_slashes():
  header = Struct("noted", Field(Type.uint8, "a", doc="first\n\nthird")).export_c_header()
  assert "  //\n" in header and all(line == line.rstrip() for line in header.splitlines())

def raw_reads_the_numbers_the_wire_holds():
  """A database of raw counts takes them as the wire has them, a bitfield as one integer."""
  s = Struct("state",
    Field(Type.int16, "bus", "V", scale=10), Bitfield("flags", [("mode", 4), ("fault", 4)]),
    Field(POINT, "pos"), Field(Type.float, "temp"),
  )
  record = {"bus": 24.1, "flags": {"mode": 3, "fault": 1}, "pos": {"x": 1, "y": -2}, "temp": 0.1}
  wire = {"bus": 241, "flags": 19, "pos": {"x": 1, "y": -2}, "temp": 0.10000000149011612}
  data = s.encode(record)
  assert s.decode(data, raw=True) == wire and s.records(data * 2, raw=True) == [wire] * 2
  message = Message({1: s})
  assert message.decode(message.encode({"state": [record]}), raw=True) == {"state": [wire]}
