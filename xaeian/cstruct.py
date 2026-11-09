# xaeian/cstruct.py

"""
Binary records described once, for Python, numpy and C.

Numeric, string and byte fields, fixed arrays, nested structs, bitfields and padding,
a scale and an offset per number, a CRC per record.
A record exports as a C header that mirrors the wire byte for byte, or as a numpy `dtype()`.

Three layers put records on a wire, joined by the caller:
`Struct` is one record, `Message` puts blocks of records under codes into one body,
`Frame` is the envelope that gives a raw byte stream its boundaries and integrity,
the mirror of `FRAME_t` in C: `frame.encode(message.encode(data))`.

Example:
  >>> from xaeian.cstruct import Struct, Field, Type
  >>> point = Struct("point", Field(Type.int16, "x", "mm"), Field(Type.int16, "y", "mm"))
  >>> point.decode(point.encode({"x": 1, "y": -2}))
  {'x': 1, 'y': -2}
"""

import re
from numbers import Integral, Real
from struct import pack, unpack_from, calcsize, error as PackError, Struct as Packer
from enum import Enum
from typing import Any, Callable, Iterator, NamedTuple, cast

from .crc import CRC, crc32_iso
from .extras import MissingExtra, absent

__extras__ = ("cstruct", ["numpy"]) # `dtype()` alone

class Type(Enum):
  """Field types named as in C; the value is the `struct` format char, except string and bytes."""
  uint8 = "B"
  int8 = "b"
  uint16 = "H"
  int16 = "h"
  uint32 = "I"
  int32 = "i"
  uint64 = "Q"
  int64 = "q"
  float = "f"
  double = "d"
  string = "str" # null-terminated UTF-8
  bytes = "byte" # length-prefixed by a uint16

  @property
  def size(self) -> int|None:
    """Size in bytes, `None` for string and bytes, as for a `Struct` of varying size."""
    return None if self in (Type.string, Type.bytes) else calcsize(self.value)

  @property
  def is_integer(self) -> bool:
    """`True` for the integer types, whose values round to the nearest whole before packing."""
    return self.name.startswith(("int", "uint"))

class Endian(Enum):
  """Byte order of a struct's numbers."""
  little = "<"
  big = ">"

def _check_count(value:Any, what:str) -> None:
  """Refuse `value` as `what` unless it is a whole number of 1 or more."""
  if isinstance(value, bool) or not isinstance(value, Integral):
    raise TypeError(f"{what} is a whole number, not {value!r}")
  if value < 1: raise ValueError(f"{what} is 1 or more, not {value}")

def _float32(value:float) -> float:
  """
  Shortest decimal packing into the same float32 bits: 23.45, not 23.450000762939453.
  Nine digits keep every bit through a read and a rewrite; past the float32 range, `value` as is.
  Six come first: `%g` drops their trailing zeros, so a shorter decimal shows through them anyway.
  """
  try: bits = pack("<f", value)
  except OverflowError: return value
  for digits in range(6, 10):
    short = float(f"{value:.{digits}g}")
    try:
      if pack("<f", short) == bits: return short
    except OverflowError: continue # rounded past FLT_MAX, as 3.403e+38 is for 3.4028235e+38
  return value

#-------------------------------------------------------------------------------------------- Field

class Field:
  """
  One field of a `Struct`: a number, an array of them, a string, bytes or a nested struct.
  A number travels as `value * scale + offset`.
  """
  def __init__(
    self,
    type:"Type|Struct",
    name:str,
    unit:str = "",
    *,
    length:int = 1,
    scale:float = 1,
    offset:float = 0,
    default:Any = None,
    doc:str = "",
  ) -> None:
    """
    Args:
      type: A `Type`, or a `Struct` nested here as in C, its value a dict of its own
      name: Key of the field in the record's dict
      unit: Documentation only, e.g. "V", "Hz"
      length: 1 = scalar, >1 = fixed-size array; string and bytes size themselves
      scale: Raw counts per unit of a number, `100` stores 23.45 as 2345
      default: Encoded where the record lacks the field, `None` = the field is required
      doc: Documentation only, the note of the C field
    """
    if not isinstance(type, (Type, Struct)):
      raise TypeError(f"Field '{name}' takes a Type or a Struct, got {type!r}")
    if isinstance(type, Struct) and (type.crc or type.align > 1):
      raise ValueError(f"Struct '{type.name}' nests by its members only: no crc or align")
    _check_count(length, f"Length of field '{name}'")
    if not isinstance(scale, Real):
      raise TypeError(f"Field '{name}' scales by a number, not {scale!r}")
    if not scale: raise ValueError(f"Field '{name}' cannot scale by 0: a read divides by it")
    if not isinstance(offset, Real):
      raise TypeError(f"Field '{name}' shifts by a number, not {offset!r}")
    if length > 1 and type in (Type.string, Type.bytes):
      raise ValueError(f"Field '{name}' of {type.name} sizes itself: no length")
    if (scale != 1 or offset) and not (isinstance(type, Type) and type.size):
      raise ValueError(f"Field '{name}' of {type.name} holds no number to scale or shift")
    self.type: Type|Struct = type
    self.name: str = name
    self.unit: str = unit
    self.length: int = length
    self.scale: float = scale
    self.offset: float = offset
    self.default: Any = default
    self.doc: str = doc

  @property
  def is_array(self) -> bool:
    """`True` for `length` > 1; length 1 is a scalar, not a one-element array."""
    return self.length > 1

  @property
  def size(self) -> int|None:
    """Bytes on the wire, `None` when the value decides: string, bytes, a struct holding one."""
    size = self.type.size
    return None if size is None else size * self.length

  def _raw(self, value:float) -> float:
    """The number the wire holds, before its bits: scaled and shifted."""
    return value * self.scale + self.offset

  def _value(self, raw:float) -> float:
    """The number the field means: shift and scale undone."""
    if self.offset: raw -= self.offset
    if self.scale != 1: raw /= self.scale
    return raw

  @property
  def _plain(self) -> bool:
    """`True` where `_value` gives the raw number back as it is, so a read can skip it."""
    return not self.offset and self.scale == 1

  def __repr__(self) -> str:
    unit = f", {self.unit!r}" if self.unit else ""
    length = f", length={self.length}" if self.is_array else ""
    return f"Field({self.type.name}, {self.name!r}{unit}{length})"

#----------------------------------------------------------------------------------------- Bitfield

class Bitfield:
  """
  Named bit groups packed into one unsigned integer, the first group in the lowest bits.

  Example:
    status = Bitfield("status", [("enabled", 1), ("error", 1), ("mode", 3)]) # 5 bits → uint8
  """
  def __init__(
    self,
    name:str,
    bits:list[tuple[str, int]],
    type:Type|None = None,
    *,
    doc:str = "",
  ) -> None:
    """
    Args:
      bits: `(bit_name, bit_width)` pairs, the lowest bits first
      type: Unsigned integer the bits pack into, by default the narrowest that holds them
      doc: Documentation only, the note of the C member
    """
    groups = dict(bits)
    if not groups: raise ValueError(f"Bitfield '{name}' needs a bit group")
    if len(groups) < len(bits): raise ValueError(f"Duplicate bit name in bitfield '{name}'")
    for bit, width in groups.items(): _check_count(width, f"Width of '{bit}' in bitfield '{name}'")
    if type is not None and not isinstance(type, Type):
      raise TypeError(f"Bitfield '{name}' packs into a Type, got {type!r}")
    total = sum(groups.values())
    if total <= 8: narrowest = Type.uint8
    elif total <= 16: narrowest = Type.uint16
    elif total <= 32: narrowest = Type.uint32
    else: narrowest = Type.uint64
    kind = type or narrowest
    if not kind.name.startswith("uint") or total > 8 * calcsize(kind.value):
      raise ValueError(f"Bitfield '{name}' needs an unsigned integer of {total} bits or more")
    self.name: str = name
    self.bits: dict[str, int] = groups
    self.type: Type = kind
    self.doc: str = doc

  @property
  def size(self) -> int:
    """Bytes of the integer the bits pack into."""
    return calcsize(self.type.value)

  def encode(self, values:dict[str, int]) -> int:
    """
    Named bit values packed into one integer, a name missing from `values` packing as 0.
    A name the bitfield lacks and a value outside its bits are refused:
    a typo would pack its bit as 0 and -1 would pack as all ones, both without a word.
    """
    if not isinstance(values, dict):
      raise TypeError(f"Bitfield '{self.name}' encodes a dict, got {type(values).__name__}")
    unknown = values.keys() - self.bits.keys()
    if unknown: raise KeyError(f"Bitfield '{self.name}' has no {', '.join(sorted(unknown))}")
    packed = at = 0
    for bit, width in self.bits.items():
      value, mask = values.get(bit, 0), (1 << width) - 1
      if not isinstance(value, Integral):
        raise TypeError(f"Bit '{bit}' takes an integer, got {type(value).__name__}")
      if not 0 <= value <= mask: raise ValueError(f"Bit '{bit}' value {value} outside 0 to {mask}")
      packed |= value << at
      at += width
    return packed

  def decode(self, packed:int) -> dict[str, int]:
    """One integer unpacked into named bit values."""
    values, at = {}, 0
    for bit, width in self.bits.items():
      values[bit] = (packed >> at) & ((1 << width) - 1)
      at += width
    return values

  def __repr__(self) -> str:
    return f"Bitfield({self.name!r}, {list(self.bits.items())!r})"

#------------------------------------------------------------------------------------------ Padding

class Padding:
  """Run of zero bytes for alignment, skipped on decode."""
  def __init__(self, size:int) -> None:
    _check_count(size, "Size of a padding")
    self.size: int = size

  def __repr__(self) -> str:
    return f"Padding({self.size})"

#------------------------------------------------------------------------------------------- Struct

class _Step(NamedTuple):
  """A member of a run: how many of the run's values it takes, and how they become its value."""
  name: str
  length: int # an array's length, else 1
  value: Callable|None # raw → value, `None` where they are one
  inner: "_Run|None" # a nested struct's run, which takes its values

class _Run:
  """Members of fixed size side by side: one `struct` call reads them, `build` lays them out."""
  def __init__(self, members:list, endian:Endian) -> None:
    fmt, steps = "", []
    for member in members:
      if isinstance(member, Padding):
        fmt += f"{member.size}x"
      elif isinstance(member, Bitfield):
        fmt += member.type.value
        steps.append(_Step(member.name, 1, member.decode, None))
      elif isinstance(member.type, Struct):
        inner = cast(_Run, member.type._parts[0]) # a struct of fixed size is one run
        fmt += inner.format * member.length
        steps.append(_Step(member.name, member.length, None, inner))
      else:
        fmt += f"{member.length}{member.type.value}"
        steps.append(_Step(member.name, member.length, self._reader(member), None))
    self.members: tuple = tuple(members) # in wire order, padding included
    self.steps: tuple[_Step, ...] = tuple(steps)
    self.format: str = fmt # without the byte order, so a host struct can take it in
    self.packer: Packer = Packer(endian.value + fmt)

  @staticmethod
  def _reader(field:Field) -> Callable|None:
    """Raw → value: a float32 first the shortest decimal of its bits, then the field's own."""
    if field.type != Type.float: return None if field._plain else field._value
    return _float32 if field._plain else lambda raw: field._value(_float32(raw))

  def build(self, values:tuple, at:int, record:dict, raw:bool) -> int:
    """The run's values from `values[at:]` into `record` → the index behind them."""
    for step in self.steps:
      if step.inner:
        items: list = []
        for _ in range(step.length):
          item: dict[str, Any] = {}
          at = step.inner.build(values, at, item, raw)
          items.append(item)
      else:
        items = list(values[at:at + step.length])
        if step.value and not raw: items = [step.value(value) for value in items]
        at += step.length
      record[step.name] = items if step.length > 1 else items[0]
    return at

class Struct:
  """
  One record of the wire: fields, bitfields and padding in their order, a dict in and out.

  Its byte order is its records': a nested struct shares it, a `Message` takes it.
  `crc` is the record's own tail, a `crc` member at the end of the C struct:
  it travels with the record everywhere, a block of a `Message` included.
  Integrity of a whole message is the envelope's job, see `Frame`.
  """
  def __init__(
    self,
    name:str,
    *members:Field|Bitfield|Padding,
    endian:Endian = Endian.little,
    crc:CRC|None = None,
    align:int = 1,
  ) -> None:
    """
    Args:
      name: Key of its blocks in a `Message`, base of its C type
      members: In wire order; a field's or a bitfield's name is its key in the record, one each
      crc: Appended to every record, behind its alignment padding
      align: Pad each record up to this byte multiple, 1 = none
    """
    if not name: raise ValueError("A struct needs a name: it keys its blocks and names its C type")
    if not members: raise ValueError(f"Struct '{name}' needs a member: no record is empty")
    _check_count(align, f"Alignment of struct '{name}'")
    if not isinstance(endian, Endian):
      raise TypeError(f"Struct '{name}' takes its byte order as an Endian, got {endian!r}")
    if crc is not None and not isinstance(crc, CRC):
      raise TypeError(f"Struct '{name}' takes a CRC, got {crc!r}")
    names = set()
    for member in members:
      if not isinstance(member, (Field, Bitfield, Padding)):
        got = type(member).__name__
        raise TypeError(f"Struct '{name}' takes a Field, Bitfield or Padding, got {got}")
      if isinstance(member, Padding): continue
      if not member.name: raise ValueError(f"Struct '{name}' has a member with no name")
      if member.name in names:
        raise ValueError(f"Struct '{name}' names two members '{member.name}'")
      names.add(member.name)
      if isinstance(member.type, Struct) and member.type.endian != endian:
        raise ValueError(f"Struct '{member.type.name}' nests in '{name}' of another byte order")
    if crc and "crc" in names:
      raise ValueError(f"Struct '{name}' keeps the name 'crc' for its crc tail")
    self.name: str = name
    self.members: tuple[Field|Bitfield|Padding, ...] = members
    self.endian: Endian = endian
    self.crc: CRC|None = crc
    self.align: int = align
    self._keys: frozenset = frozenset(names)
    self._parts: list[_Run|Field] = self._compile()
    for member in members: # a default the field cannot hold fails here, not when it is missed
      if isinstance(member, Field) and member.default is not None:
        self._encode_field(member, member.default)

  def _compile(self) -> list[_Run|Field]:
    """The members in parts: a run of fixed size read in one call, each varying field alone."""
    parts: list[_Run|Field] = []
    run: list = []
    for member in self.members:
      if member.size is not None:
        run.append(member)
        continue
      if run: parts.append(_Run(run, self.endian))
      parts.append(member)
      run = []
    if run: parts.append(_Run(run, self.endian))
    return parts

  def _where(self, name:str) -> str:
    """How an error names a member: `'temp' of 'state'`."""
    return f"'{name}' of '{self.name}'"

  def _pack(self, kind:Type, name:str, raw:float) -> bytes:
    """
    One raw number in the bits of `kind`, an integer rounded to the nearest whole.
    Truncated, `2.3` at scale 100 would go out as 229: in floating point it is 229.99999999999997.
    A number `kind` cannot hold, `inf` or `nan` for an integer among them, is refused by name.
    """
    try:
      if kind.is_integer: raw = int(round(raw))
      return pack(self.endian.value + kind.value, raw)
    except (PackError, OverflowError, ValueError) as e:
      raise ValueError(f"{self._where(name)}: {e}") from None

  def _encode_field(self, field:Field, value:Any) -> bytes:
    """One field's bytes: a string, bytes, numbers or nested records."""
    if field.type == Type.string:
      if not isinstance(value, str):
        raise TypeError(f"{self._where(field.name)} takes str, got {type(value).__name__}")
      if "\0" in value:
        raise ValueError(f"{self._where(field.name)} holds a NUL, its end on the wire")
      try: return value.encode("utf-8") + b"\0"
      except UnicodeEncodeError as e:
        raise ValueError(f"{self._where(field.name)} holds no UTF-8: {e.reason}") from None
    if field.type == Type.bytes:
      if not isinstance(value, (bytes, bytearray)):
        raise TypeError(f"{self._where(field.name)} takes bytes, got {type(value).__name__}")
      return self._pack(Type.uint16, field.name, len(value)) + value
    if field.is_array:
      if not isinstance(value, (list, tuple)):
        got = type(value).__name__
        raise TypeError(f"{self._where(field.name)} takes a list or tuple, got {got}")
      if len(value) != field.length:
        raise ValueError(f"{self._where(field.name)} takes {field.length} items, got {len(value)}")
    elif isinstance(value, (list, tuple)):
      raise TypeError(f"{self._where(field.name)} takes one value, got {type(value).__name__}")
    values = value if field.is_array else [value]
    if isinstance(field.type, Struct): return b"".join(field.type.encode(v) for v in values)
    data = b""
    for v in values:
      try: raw = field._raw(v)
      except TypeError: # what the scale cannot multiply is no number
        got = type(v).__name__
        raise TypeError(f"{self._where(field.name)} takes a number, got {got}") from None
      data += self._pack(field.type, field.name, raw)
    return data

  def _decode_field(self, field:Field, data:bytes, at:int, raw:bool) -> tuple[Any, int]:
    """A field of varying size at `at` → `(value, offset behind it)`."""
    if isinstance(field.type, Struct): # one holding a string or bytes
      items = []
      for _ in range(field.length):
        item, at = field.type._read(data, at, raw)
        items.append(item)
      return (items if field.is_array else items[0]), at
    if field.type == Type.string:
      end = data.find(0, at)
      if end < 0: raise ValueError(f"{self._where(field.name)} has no NUL to end it")
      try: return data[at:end].decode("utf-8"), end + 1
      except UnicodeDecodeError as e:
        raise ValueError(f"{self._where(field.name)} holds no UTF-8: {e.reason}") from None
    if at + 2 > len(data): raise ValueError(f"{self._where(field.name)} is cut short")
    size = unpack_from(self.endian.value + "H", data, at)[0]
    at += 2
    if at + size > len(data): raise ValueError(f"{self._where(field.name)} is cut short")
    return data[at:at + size], at + size

  def _cut(self, members:tuple, have:int) -> ValueError|None:
    """The error naming the first member `have` bytes of `members` cut short, else `None`."""
    end = 0
    for member in members:
      size = member.size
      if end + size > have and not isinstance(member, Padding):
        cut = ValueError(f"{self._where(member.name)} is cut short")
        if isinstance(member, Field) and isinstance(member.type, Struct): # inside one of its items
          inner = member.type._cut(member.type.members, (have - end) % (size // member.length))
          return inner or cut
        return cut
      end += size
    return None

  def _read(self, data:bytes, at:int, raw:bool) -> tuple[dict[str, Any], int]:
    """One record at `at` → `(record, offset behind it)`, its `crc` verified."""
    start = at
    record: dict[str, Any] = {}
    for part in self._parts:
      if isinstance(part, _Run):
        if at + part.packer.size > len(data):
          cut = self._cut(part.members, len(data) - at)
          raise cut or ValueError(f"Struct '{self.name}' is cut short in its padding")
        part.build(part.packer.unpack_from(data, at), 0, record, raw)
        at += part.packer.size
      else:
        record[part.name], at = self._decode_field(part, data, at, raw)
    at += -(at - start) % self.align # the alignment padding `encode` adds
    if at > len(data): raise ValueError(f"Struct '{self.name}' is cut short in its padding")
    if self.crc:
      n = self.crc.size
      crc = data[at:at + n]
      if len(crc) < n or self.crc.to_int(crc) != self.crc.checksum(data[start:at]):
        raise ValueError(f"Struct '{self.name}' fails its CRC check")
      at += n
    return record, at

  def encode(self, record:dict) -> bytes:
    """One record on the wire: its members, the alignment padding, then its `crc`."""
    if not isinstance(record, dict):
      raise TypeError(f"Struct '{self.name}' encodes a dict, got {type(record).__name__}")
    unknown = record.keys() - self._keys # a typo would leave its field at the default, unsaid
    if unknown: raise KeyError(f"Struct '{self.name}' has no {', '.join(sorted(unknown))}")
    data = b""
    for member in self.members:
      if isinstance(member, Padding):
        data += bytes(member.size)
        continue
      if member.name in record: value = record[member.name]
      elif isinstance(member, Field) and member.default is not None: value = member.default
      else: raise KeyError(f"{self._where(member.name)} is missing from the record")
      if isinstance(member, Bitfield):
        data += self._pack(member.type, member.name, member.encode(value))
      else:
        data += self._encode_field(member, value)
    data += bytes(-len(data) % self.align)
    return self.crc.encode(data) if self.crc else data

  def decode(self, data:bytes, raw:bool=False) -> dict[str, Any]:
    """
    Exactly one record; bytes left behind it are refused, `records` reads a run of them.
    `raw` gives the numbers the wire holds: before `scale` and `offset`, a bitfield as one integer.
    """
    record, end = self._read(data, 0, raw)
    if end != len(data):
      raise ValueError(f"Struct '{self.name}' leaves {len(data) - end}B behind one record")
    return record

  def records(self, data:bytes, raw:bool=False) -> list[dict[str, Any]]:
    """
    Every record of `data`, back to back, as a list even when there is one.
    `raw` as in `decode`.
    """
    out, at = [], 0
    while at < len(data): # every member takes a byte or more, so every record does
      record, at = self._read(data, at, raw)
      out.append(record)
    return out

  @property
  def size(self) -> int|None:
    """Bytes of one record, alignment tail and `crc` included; `None` when it varies."""
    total = 0
    for member in self.members:
      if member.size is None: return None
      total += member.size
    return total + -total % self.align + (self.crc.size if self.crc else 0)

  def dtype(self) -> Any:
    """
    numpy dtype of one record, every byte of it: padding, the alignment tail and `crc` included.
    Raw values, before `scale` and `offset`: `np.frombuffer(data, s.dtype())` reads `encode`.
    A string or bytes varies in size, so it is refused.
    """
    try: import numpy as np
    except ModuleNotFoundError as e:
      if not absent(e, "numpy"): raise
      raise MissingExtra("Install with: pip install xaeian[cstruct]") from e
    names, formats, offsets, at = [], [], [], 0
    for member in self.members:
      if isinstance(member, Padding):
        at += member.size # a gap of the dtype
        continue
      if member.size is None:
        raise ValueError(f"{self._where(member.name)} varies in size: no dtype holds it")
      if isinstance(member.type, Struct): kind = member.type.dtype()
      else: kind = self.endian.value + member.type.value
      count = member.length if isinstance(member, Field) else 1
      names.append(member.name)
      formats.append((kind, (count,)) if count > 1 else kind)
      offsets.append(at)
      at += member.size
    at += -at % self.align
    if self.crc:
      names.append("crc")
      formats.append(f">u{self.crc.size}") # big-endian whatever the record's order
      offsets.append(at)
      at += self.crc.size
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": at})

  def export_c_header(self, path:str|None=None, prefix:str="", extern:dict|None=None) -> str:
    """
    C header mirroring this record: its typedef, nested ones first, every size and offset asserted.
    `path` is the file's logical path, its first line and its guard.
    `prefix` and `extern` work as in `Message.export_c_header`.
    """
    if self.endian == Endian.big:
      raise ValueError(f"Struct '{self.name}' is big-endian: a C struct holds the target's order")
    header = _CHeader(prefix, extern)
    header.collect(self)
    return header.render(path, _guard(path, self.name))

  def __repr__(self) -> str:
    return f"Struct({self.name!r})"

#--------------------------------------------------------------------------------------------- Wire

class Message:
  """
  Body of a frame: blocks of records under codes, each one `| code u16 | size u16 | records |`.
  The code is the message's own: it picks the struct, so two layouts are two codes.
  A block is read out of exactly its `size` bytes, so a header that lies is refused
  rather than left to shift everything after it. Integrity belongs to `Frame`, the envelope.
  Bytes that do not read raise `ValueError`, an unknown code included.
  """
  BLOCK_HEAD = 4 # code and size

  def __init__(self, structs:dict[int, Struct]) -> None:
    """
    Args:
      structs: Block code → its struct; names unique, one byte order for all, the message's own
    """
    self.structs: dict[int, Struct] = dict(structs)
    self._codes: dict[str, int] = {}
    for code, struct in self.structs.items():
      if not isinstance(struct, Struct):
        raise TypeError(f"Message takes a Struct for code {code!r}, got {struct!r}")
      if not isinstance(code, Integral):
        raise TypeError(f"Code {code!r} of '{struct.name}' is no integer")
      if not 0 <= code <= 0xFFFF: raise ValueError(f"Code {code} of '{struct.name}' is no uint16")
      if struct.name in self._codes:
        raise ValueError(f"Two structs named '{struct.name}' in one message")
      self._codes[struct.name] = code
    orders = {struct.endian for struct in self.structs.values()}
    if len(orders) > 1:
      raise ValueError("A message has one byte order: its structs mix big and little")
    self.endian: Endian = orders.pop() if orders else Endian.little

  def encode(self, data:dict[str, list[dict]]) -> bytes:
    """`{struct_name: [records]}` into one body, a block per name."""
    if not isinstance(data, dict):
      raise TypeError(f"A message encodes a dict of record lists, got {type(data).__name__}")
    body = b""
    for name, records in data.items():
      if name not in self._codes: raise KeyError(f"Message has no struct '{name}'")
      if not isinstance(records, (list, tuple)):
        raise TypeError(f"Records of '{name}' go in a list, got {type(records).__name__}")
      code = self._codes[name]
      payload = b"".join(self.structs[code].encode(record) for record in records)
      if len(payload) > 0xFFFF:
        raise ValueError(f"Block of '{name}' holds {len(payload)}B, its uint16 size counts 65535")
      body += pack(self.endian.value + "HH", code, len(payload)) + payload
    return body

  def decode(self, body:bytes, raw:bool=False) -> dict[str, list[dict]]:
    """A body → `{struct_name: [records]}`; `raw` as in `Struct.decode`."""
    data: dict[str, list[dict]] = {}
    at = 0
    while at < len(body):
      if at + self.BLOCK_HEAD > len(body): raise ValueError("Block header is cut short")
      code, size = unpack_from(self.endian.value + "HH", body, at)
      at += self.BLOCK_HEAD
      if code not in self.structs: raise ValueError(f"Message has no block code {code}")
      if at + size > len(body):
        raise ValueError(f"Block declares {size}B, {len(body) - at}B left in the message")
      struct = self.structs[code]
      data.setdefault(struct.name, []).extend(struct.records(body[at:at + size], raw))
      at += size
    return data

  def export_c_header(self, path:str|None=None, prefix:str="", extern:dict|None=None) -> str:
    """
    C header of the whole body: block codes, the block header, every struct and its checks.
    `prefix` names the module the C way: `REC` gives `REC_CODE_SAMPLE` and `REC_Sample_t`.
    `extern` maps a struct to the `(type, header)` already defining it in C:
    that header is included and the type checked, never defined twice.
    """
    if not prefix: raise ValueError("A message header names its codes after a module: pass prefix")
    if self.endian == Endian.big:
      raise ValueError("The message is big-endian: a C struct holds the target's order")
    header = _CHeader(prefix, extern)
    for struct in self.structs.values(): header.collect(struct)
    return header.render(path, _guard(path, prefix), self)

class Frame:
  """
  Envelope of one body on a raw byte link: `| AA 55 | len u16 | body | crc |`.
  `len` counts body and CRC, the CRC covers the body: the mirror of `FRAME_t` in C.
  The body is bytes, a `Message`'s for one; the caller joins the two layers,
  so a body its message cannot read stops nothing behind it.

  `feed` walks a stream and yields every frame that verifies.
  The sync pair can occur inside data,
  so a frame that fails is dropped from the byte behind its first sync byte
  and the hunt starts there, not behind the whole frame.
  A false pair with a plausible length holds the frames behind it until its bytes are in,
  so `limit` also bounds that delay.
  """
  SYNC = b"\xAA\x55"
  FRAME_HEAD = 4 # sync pair and length

  def __init__(
    self,
    *,
    crc:CRC|None = crc32_iso,
    limit:int = 1024,
    endian:Endian = Endian.little,
  ) -> None:
    """
    Args:
      crc: Appended behind the body, `None` = none
      limit: Longest body accepted [B], at most 65535 with the crc; a longer `len` is noise
      endian: Order of the length field, the envelope's own
    """
    if crc is not None and not isinstance(crc, CRC):
      raise TypeError(f"A frame takes a CRC, got {crc!r}")
    if not isinstance(endian, Endian):
      raise TypeError(f"A frame takes its byte order as an Endian, got {endian!r}")
    if not 0 <= limit <= 0xFFFF - (crc.size if crc else 0):
      raise ValueError(f"A body of {limit}B and its crc do not fit the uint16 length")
    self.crc: CRC|None = crc
    self.limit: int = limit
    self.endian: Endian = endian
    self._len = endian.value + "H"
    self.errors: int = 0 # frames dropped on length or CRC
    self._buf = bytearray()

  @property
  def pending(self) -> int:
    """Bytes held back: a frame still on its way, or a sync pair split by the chunk."""
    return len(self._buf)

  def encode(self, body:bytes) -> bytes:
    """
    One body framed for the wire.

    A body over `limit` raises: the far end would drop it as nonsense and count an error,
    so this is the one place that can still say what went wrong.
    """
    if len(body) > self.limit:
      raise ValueError(f"Body of {len(body)}B over the {self.limit}B limit")
    if self.crc: body = self.crc.encode(body)
    return self.SYNC + pack(self._len, len(body)) + body

  def feed(self, data:bytes) -> Iterator[bytes]:
    """Take a stretch of the stream, yield the body of every complete frame in it."""
    self._buf += data
    tail = self.crc.size if self.crc else 0
    while True:
      start = self._buf.find(self.SYNC)
      if start < 0:
        # a lone first sync byte at the end may be a pair the chunk cut in half
        keep = 1 if self._buf.endswith(self.SYNC[:1]) else 0
        del self._buf[:len(self._buf) - keep]
        return
      del self._buf[:start]
      if len(self._buf) < self.FRAME_HEAD: return
      length = unpack_from(self._len, self._buf, 2)[0]
      total = self.FRAME_HEAD + length
      if tail <= length <= self.limit + tail:
        if len(self._buf) < total: return # the rest is still on the wire
        framed = bytes(self._buf[self.FRAME_HEAD:total])
        body = self.crc.decode(framed) if self.crc else framed
        if body is not None:
          del self._buf[:total]
          yield body
          continue
      self.errors += 1
      del self._buf[:1] # the pair was data, so the hunt goes on from behind its first byte

  def reset(self) -> None:
    """Drop what is under assembly, the link is gone."""
    self._buf.clear()

#----------------------------------------------------------------------------------------- C header

_C_NAME = re.compile(r"(?!_[A-Z_])[A-Za-z_][A-Za-z0-9_]*") # `_X` and `__x` are the compiler's
_C_KEYWORDS = frozenset(( # C11, C23 that GCC takes by default since 15, GNU `asm`
  "alignas alignof asm auto bool break case char const constexpr continue default do double else "
  "enum extern false float for goto if inline int long nullptr register restrict return short "
  "signed sizeof static static_assert struct switch thread_local true typedef typeof "
  "typeof_unqual union unsigned void volatile while"
).split())
_C_MACROS = re.compile( # what `<stddef.h>` and `<stdint.h>` define without arguments
  r"NULL|(U?INT(_LEAST|_FAST)?(8|16|32|64)|U?INT(PTR|MAX)"
  r"|PTRDIFF|SIZE|SIG_ATOMIC|WCHAR|WINT)_(MIN|MAX|WIDTH)",
)
_C_TYPES = re.compile( # the types they define, so a struct of the same name is a second one
  r"(u?int(_least|_fast)?(8|16|32|64)|u?int(ptr|max)|size|ptrdiff|wchar|max_align|nullptr)_t",
)
_WIDTH = 99 # the longest line `cstyle` takes

def _c_name(name:str) -> bool:
  """`True` for an identifier C takes as written: no keyword, nothing reserved or defined."""
  if name in _C_KEYWORDS or _C_MACROS.fullmatch(name): return False
  return bool(_C_NAME.fullmatch(name))

def _separator(name:str="") -> str:
  """A `cstyle` separator: a whole line, the name at its end."""
  label = f" {name}" if name else ""
  return "//" + "-" * (_WIDTH - 2 - len(label)) + label

def _guard(path:str|None, name:str) -> str:
  """Include guard from the file's name, else from `name`: `diag/rec_wire.h` → `REC_WIRE_H_`."""
  file = path.replace("\\", "/").rsplit("/", 1)[-1] if path else f"{name}.h"
  guard = re.sub(r"[^A-Za-z0-9]", "_", file).upper() + "_"
  if not _c_name(guard): raise ValueError(f"No include guard comes from '{file}'")
  return guard

def _assert(test:str, says:str) -> str:
  """
  One `_Static_assert`, its message saying what the wire holds.
  Past the width of `cstyle` the message goes on a line of its own, and the test too
  when its own line runs past it.
  """
  line = f'_Static_assert({test}, "{says} on the wire");'
  if len(line) <= _WIDTH: return line
  head = f"_Static_assert({test},"
  if len(head) <= _WIDTH: return f'{head}\n  "{says} on the wire");'
  return f'_Static_assert(\n  {test},\n  "{says} on the wire");'

class _Row(NamedTuple):
  """One member of a C struct: its declaration and note, its name, and where it sits."""
  decl: str
  note: str
  name: str
  offset: int
  align: int

class _CHeader:
  """
  C mirror of the wire: a typedef per struct, nested ones first, every size and offset asserted.

  `prefix` names the module the C way: `REC` gives `REC_Sample_t` and `REC_CODE_SAMPLE`.
  `extern` maps a struct to the `(type, header)` already defining it in C:
  that header is included and the type checked, never defined twice.
  """
  def __init__(self, prefix:str, extern:dict|None) -> None:
    self.prefix = prefix
    self.extern: dict[Struct, tuple[str, str]] = extern or {}
    self.block_type = f"{prefix}_Block_t" # header of every block of a `Message`
    self.defined: list[Struct] = [] # typedefs written here, a nested one before its user
    self.included: list[Struct] = [] # from `extern`, checked only
    names = [kind for kind, _ in self.extern.values()] + ([prefix] if prefix else [])
    bad = [name for name in names if not _c_name(name)]
    if bad: raise ValueError(f"No C names: {', '.join(bad)}")

  def collect(self, struct:Struct) -> None:
    """Take `struct` and the structs nested in it, each once."""
    if struct in self.defined or struct in self.included: return
    self._refuse(struct)
    if struct in self.extern:
      self.included.append(struct)
      return
    for member in struct.members:
      if isinstance(member, Field) and isinstance(member.type, Struct): self.collect(member.type)
    self.defined.append(struct)

  def _refuse(self, struct:Struct) -> None:
    """Refuse what no C struct can mirror, before a line is written."""
    names = [struct.name]
    for member in struct.members:
      if isinstance(member, Field): names.append(member.name)
      elif isinstance(member, Bitfield): names += [member.name, *member.bits]
    bad = [name for name in names if not _c_name(name)]
    if bad: raise ValueError(f"No C names in '{struct.name}': {', '.join(bad)}")
    last = len(struct.members) - 1
    for i, member in enumerate(struct.members):
      if not isinstance(member, Field) or member.size is not None: continue
      where = struct._where(member.name)
      if i < last or isinstance(member.type, Struct):
        raise ValueError(f"{where} varies in size: C takes only a last string or bytes")
      if i == 0 and member.type == Type.string:
        raise ValueError(f"{where} stands alone: C wants a member before a flexible array")
    rows = self.members(struct)
    members = [row.name for row in rows] # padding and lengths named here too
    twice = sorted({name for name in members if members.count(name) > 1})
    if twice: raise ValueError(f"C members of '{struct.name}' share a name: {', '.join(twice)}")
    for row in rows: # a note breaks where its author breaks it, so a line too long is theirs
      if any(len(f"  // {line}") > _WIDTH for line in row.note.splitlines()):
        where = struct._where(row.name)
        raise ValueError(f"{where} has a note line past {_WIDTH} in C: break it with \\n")

  def code(self, struct:Struct) -> str:
    """Define of the block code of `struct`: `REC_CODE_SAMPLE`."""
    return f"{self.prefix}_CODE_{struct.name.upper()}"

  @staticmethod
  def c_type(kind:Type) -> str:
    """C type of a number: `uint16` is `uint16_t`, `float` and `double` keep their names."""
    return f"{kind.name}_t" if kind.is_integer else kind.name

  def name(self, struct:Struct, bitfield:str="") -> str:
    """C type of `struct` or its bitfield: `REC_State_t`, `REC_StateFlags_t`, `state_flags_t`."""
    if struct in self.extern and not bitfield: return self.extern[struct][0]
    words = f"{struct.name}_{bitfield}" if bitfield else struct.name
    if not self.prefix: return f"{words}_t"
    # an acronym keeps its capitals: `FOC_dump` is `FOCDump`, never `FocDump`
    camel = "".join(word[:1].upper() + word[1:] for word in words.split("_"))
    return f"{self.prefix}_{camel}_t"

  @staticmethod
  def note(field:Field) -> str:
    """`doc`, then `[unit]` only where C holds the value in it: scaled, it holds raw counts."""
    unit = f"[{field.unit}]" if field.unit and field._plain else ""
    return " ".join(part for part in (field.doc, unit) if part)

  def members(self, struct:Struct) -> list[_Row]:
    """A row per C member: fields, bitfields and padding, then the alignment tail and `crc`."""
    rows: list[_Row] = []
    at = pads = 0
    for member in struct.members:
      if isinstance(member, Bitfield):
        kind = self.name(struct, member.name)
        rows.append(_Row(f"{kind} {member.name};", member.doc, member.name, at, member.size))
        at += member.size
      elif isinstance(member, Padding):
        pads += 1
        rows.append(_Row(f"uint8_t _pad{pads}[{member.size}];", "", f"_pad{pads}", at, 1))
        at += member.size
      elif member.type == Type.string:
        rows.append(_Row(f"char {member.name}[];", member.doc, member.name, at, 1))
      elif member.type == Type.bytes:
        rows.append(_Row(f"uint16_t {member.name}_len;", "", f"{member.name}_len", at, 2))
        rows.append(_Row(f"uint8_t {member.name}[];", member.doc, member.name, at + 2, 1))
      else:
        if isinstance(member.type, Struct): kind = self.name(member.type)
        else: kind = self.c_type(member.type)
        dims = f"[{member.length}]" if member.is_array else ""
        note, align = self.note(member), self.alignment(member.type)
        rows.append(_Row(f"{kind} {member.name}{dims};", note, member.name, at, align))
        at += member.size or 0
    if struct.size is not None:
      tail = -at % struct.align
      if tail: rows.append(_Row(f"uint8_t _align[{tail}];", "", "_align", at, 1))
      if struct.crc:
        rows.append(_Row(f"uint8_t crc[{struct.crc.size}];", "big-endian", "crc", at + tail, 1))
    return rows

  def alignment(self, kind:Type|Struct) -> int:
    """C alignment of `kind`: a number its size, a natural struct its strictest member, else 1."""
    if isinstance(kind, Type): return kind.size or 1
    if not self.natural(kind): return 1
    return max((row.align for row in self.members(kind)), default=1)

  def natural(self, struct:Struct) -> bool:
    """Every member at a multiple of its alignment, the record at a multiple of the strictest."""
    rows = self.members(struct)
    if any(row.offset % row.align for row in rows): return False
    strictest = max((row.align for row in rows), default=1)
    return struct.size is None or struct.size % strictest == 0

  def bitfields(self, struct:Struct) -> list[str]:
    """A typedef per bitfield, one base type each, so every compiler lays it out alike."""
    lines = []
    for member in struct.members:
      if not isinstance(member, Bitfield): continue
      kind = self.c_type(member.type)
      lines.append("typedef struct {")
      lines += [f"  {kind} {bit} : {width};" for bit, width in member.bits.items()]
      lines += [f"}} {self.name(struct, member.name)};", ""]
    return lines

  def typedef(self, struct:Struct) -> list[str]:
    """The struct itself, packed only where its layout is not the natural one."""
    rows = self.members(struct)
    # A run of notes shares one column, two spaces past the longest line that carries one;
    # a line without a note never pushes it, nor one too long for every note to fit the width.
    # A note of several lines, or one that cannot trail at all, goes above its member,
    # and a note standing alone takes one space: a column of one is padding.
    trail = [row for row in rows
      if row.note and "\n" not in row.note and 4 + len(row.decl) + 3 + len(row.note) <= _WIDTH]
    while trail:
      column = 4 + max(len(row.decl) for row in trail)
      if all(column + 3 + len(row.note) <= _WIDTH for row in trail): break
      trail.remove(max(trail, key=lambda row: len(row.decl)))
    trailing = {row.name for row in trail}
    alone = len(trailing) == 1
    packed = "" if self.natural(struct) else " __attribute__((packed))"
    lines = [f"typedef struct{packed} {{"]
    for row in rows:
      decl = f"  {row.decl}"
      if row.name in trailing:
        lines.append(f"{decl} // {row.note}" if alone else f"{decl.ljust(column)}// {row.note}")
        continue
      lines += [f"  // {line}".rstrip() for line in row.note.splitlines()] # the author's breaks
      lines.append(decl)
    if struct.size is None and (struct.align > 1 or struct.crc):
      lines.append("  // variable size: alignment padding and crc follow the record on the wire")
    lines.append(f"}} {self.name(struct)};")
    return lines

  def checks(self, struct:Struct) -> list[str]:
    """
    `_Static_assert` on the size of `struct` and its bitfields, and on every member's offset.
    A type from `extern` is checked by the names the schema gives it: its filler is its own.
    """
    name, extern = self.name(struct), struct in self.extern
    given = {member.name for member in struct.members if not isinstance(member, Padding)}
    lines = []
    if not extern:
      for member in struct.members:
        if not isinstance(member, Bitfield): continue
        kind = self.name(struct, member.name)
        lines.append(_assert(f"sizeof({kind}) == {member.size}", f"{kind} is {member.size}B"))
    if struct.size is not None:
      lines.append(_assert(f"sizeof({name}) == {struct.size}", f"{name} is {struct.size}B"))
    for row in self.members(struct):
      if extern and row.name not in given: continue
      test = f"offsetof({name}, {row.name}) == {row.offset}"
      lines.append(_assert(test, f"{name}.{row.name} at {row.offset}"))
    return lines

  def block(self) -> list[str]:
    """Header in front of every block of a `Message`."""
    return [
      "typedef struct {",
      f"  uint16_t code;  // `{self.prefix}_CODE_*` of the records behind",
      "  uint16_t size;  // bytes of the records, the header not counted",
      f"}} {self.block_type};",
    ]

  def defines(self, message:Message|None) -> list[str]:
    """Every name the header defines or checks: codes, the block, struct and bitfield types."""
    names = [self.name(struct) for struct in self.included]
    if message:
      names.append(self.block_type)
      names += [self.code(struct) for struct in message.structs.values()]
    for struct in self.defined:
      names.append(self.name(struct))
      for member in struct.members:
        if isinstance(member, Bitfield): names.append(self.name(struct, member.name))
    return names

  def render(self, path:str|None, guard:str, message:Message|None=None) -> str:
    """The header in `cstyle` order: path, guard, includes, constants, types, structs, checks."""
    names = self.defines(message) # the includes have defined their own types once already
    twice = sorted({name for name in names if names.count(name) > 1 or _C_TYPES.fullmatch(name)})
    if twice: raise ValueError(f"The header would define {', '.join(twice)} twice")
    out = [f"// {path}", ""] if path else []
    out += ["// Generated by `xaeian.cstruct`: edit the schema, not this file", ""]
    out += [f"#ifndef {guard}", f"#define {guard}", ""]
    out += ["#include <stddef.h>", "#include <stdint.h>", ""]
    headers = sorted({self.extern[struct][1] for struct in self.included})
    if headers: out += [f'#include "{header}"' for header in headers] + [""]
    checks = []
    if message:
      out += [_separator("Constants"), ""]
      out += [f"#define {self.code(struct)} {code}" for code, struct in message.structs.items()]
      out.append("")
      block, size = self.block_type, Message.BLOCK_HEAD
      checks.append(_assert(f"sizeof({block}) == {size}", f"{block} is {size}B"))
    types = [*self.block(), ""] if message else []
    for struct in self.defined: types += self.bitfields(struct)
    if types: out += [_separator("Types"), "", *types]
    out += [_separator("Structure"), ""]
    for struct in self.defined: out += [*self.typedef(struct), ""]
    for struct in self.included + self.defined: checks += self.checks(struct)
    out += [_separator("Checks"), "", *checks, "", _separator(), "#endif", ""]
    return "\n".join(out)

#-------------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  sensor = Struct("sensor",
    Field(Type.uint32, "timestamp", "s"),
    Bitfield("flags", [("enabled", 1), ("error", 1), ("mode", 6)]),
    Field(Type.float, "temperature", "°C"),
    crc=crc32_iso,
  )
  data = {
    "timestamp": 1234567890,
    "flags": {"enabled": 1, "error": 0, "mode": 5},
    "temperature": 23.5,
  }
  encoded = sensor.encode(data)
  decoded = sensor.decode(encoded)
  print("data:", data)
  print("encoded:", encoded.hex(" "))
  print("decoded:", decoded)
  print()
  print("C header:")
  print(sensor.export_c_header())
