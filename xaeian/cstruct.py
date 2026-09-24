# xaeian/cstruct.py

"""
Binary struct serialization for C-like structures.

Numeric, string and byte fields, fixed arrays, bitfields, padding, optionals and tagged variants,
with scale/offset transforms, a CRC per record and schema export to C headers or Markdown.

Three layers put records on a wire:
`Struct` is one record, `Message` multiplexes blocks of several structs into one body,
`Frame` is the envelope that gives a raw byte stream its boundaries and integrity.
The mirror of `FRAME_t` in C.

Example:
  >>> from xaeian.cstruct import Struct, Field, Type, Endian
  >>> from xaeian.crc import crc32_iso
  >>> xyz = Struct(endian=Endian.little, crc=crc32_iso)
  >>> xyz.add(
  ...   Field(Type.uint16, "x"),
  ...   Field(Type.uint16, "y"),
  ...   Field(Type.uint16, "z"),
  ... )
  >>> message = xyz.encode({"x": 1, "y": 2, "z": 3})
  >>> data = xyz.decode(message)
  >>> data
  {'x': 1, 'y': 2, 'z': 3}
"""

from struct import pack, unpack_from, calcsize
from enum import Enum
from typing import Callable, Any, Generic, Iterator, TypeVar, overload
from numbers import Real

from .crc import CRC, crc32_iso

class Type(Enum):
  """Field data types; value is the `struct` format char, except `string`, `bytes`, `pad`."""
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
  string = "str"  # null-terminated UTF-8 string
  bytes = "byte"  # length-prefixed (uint16) byte array
  pad = "pad"     # padding bytes (ignored on decode)

  @property
  def size(self) -> int:
    """Size in bytes for fixed-size types, 0 for variable-size."""
    if self.value in ("str", "byte", "pad"): return 0
    return calcsize(self.value)

  @property
  def is_integer(self) -> bool:
    """True for the integer types, whose values get truncated before packing."""
    return self.value not in ("f", "d", "str", "byte", "pad")

  @property
  def is_float(self) -> bool:
    """True for float and double, the types decoding rounds to `precision`."""
    return self.value in ("f", "d")

  @property
  def c_type(self) -> str:
    """C type name for schema export."""
    mapping = {
      "B": "uint8_t", "b": "int8_t",
      "H": "uint16_t", "h": "int16_t",
      "I": "uint32_t", "i": "int32_t",
      "Q": "uint64_t", "q": "int64_t",
      "f": "float", "d": "double",
      "str": "char*", "byte": "uint8_t*", "pad": "uint8_t",
    }
    return mapping.get(self.value, "unknown")

def type_size(ctype:Type) -> int:
  """Size in bytes, 0 for variable-size types."""
  return ctype.size

class Endian(Enum):
  """Byte order for binary encoding/decoding."""
  little = "<"
  big = ">"
  native = "="
  network = "!"

#-------------------------------------------------------------------------------------------- Field

class Field:
  """
  Single field within a Struct.

  Encode: raw = encoder((value * scale) + offset)
  Decode: value = decoder((raw - offset) / scale)
  """
  _auto_id = 0

  def __init__(
    self,
    ctype:Type,
    name:str = "",
    unit:str = "",
    length:int = 1,
    scale:float = 1,
    point_shift:int = 0,
    offset:float = 0,
    encoder:Callable[[Real], Real]|None = None,
    decoder:Callable[[Real], Real]|None = None,
    precision:int = 3,
    optional:bool = False,
    default:Any = None,
  ) -> None:
    """
    Args:
      name: Auto-generated if empty
      unit: Documentation only, e.g. "V", "Hz"
      length: 1 = scalar, >1 = fixed-size array, ignored by string and bytes
      point_shift: Honored only when scale == 1, then scale = 10 ** point_shift
      precision: Decimal places when rounding decoded floats
      optional: Missing key falls back to `default` instead of raising
    """
    self.type: Type = ctype
    if not name:
      name = f"_field_{Field._auto_id}"
      Field._auto_id += 1
    self.name: str = name
    self.unit: str = unit
    self.length: int = length
    if scale == 1 and point_shift != 0: scale = 10 ** point_shift
    self.scale: float = scale
    self.offset: float = offset
    self.encoder: Callable[[Real], Real]|None = encoder
    self.decoder: Callable[[Real], Real]|None = decoder
    self.precision: int = precision
    self.optional: bool = optional
    self.default: Any = default

  @property
  def is_array(self) -> bool:
    """True for `length` > 1; length 1 is a scalar, not a one-element array."""
    return self.length > 1

  @property
  def is_variable_size(self) -> bool:
    """True for string and bytes, whose encoded size depends on the value."""
    return self.type.value in ("str", "byte")

  def encode_value(self, value:Real, for_pack:bool=True) -> Real:
    """Encode transform; `for_pack` truncates integer types to int."""
    if self.scale != 1: value *= self.scale
    if self.offset: value += self.offset
    if self.encoder: value = self.encoder(value)
    if for_pack and self.type.is_integer: value = int(value)
    return value

  def decode_value(self, value:Real) -> Real:
    """Decode transform, rounding float types to `precision` places."""
    if self.offset: value -= self.offset
    if self.scale != 1: value /= self.scale
    if self.decoder: value = self.decoder(value)
    if self.type.is_float: value = round(value, self.precision)
    return value

  def __str__(self) -> str:
    return f"Field {self.name}[{self.unit}]" if self.unit else f"Field {self.name}"

  def __repr__(self) -> str:
    parts = [f"Field({self.type.name!r}, {self.name!r}"]
    if self.unit: parts.append(f", unit={self.unit!r}")
    if self.length > 1: parts.append(f", length={self.length}")
    if self.scale != 1: parts.append(f", scale={self.scale}")
    parts.append(")")
    return "".join(parts)

#----------------------------------------------------------------------------------------- Bitfield

class Bitfield:
  """
  Named bit groups packed into a single uint8/16/32/64, first group in the lowest bits.

  Example:
    flags = Bitfield("status", [
      ("enabled", 1),
      ("error", 1),
      ("mode", 3),
      ("reserved", 3),
    ]) # 8 bits total → uint8
  """
  def __init__(self, name:str, bits:list[tuple[str, int]], base_type:Type|None=None) -> None:
    """
    Args:
      bits: (bit_name, bit_width) pairs
      base_type: Overrides the width picked from the total bit count
    """
    self.name = name
    self.bits = bits
    self.bit_names = [b[0] for b in bits]
    self.bit_widths = {b[0]: b[1] for b in bits}
    total_bits = sum(b[1] for b in bits)
    if base_type: self.base_type = base_type
    elif total_bits <= 8: self.base_type = Type.uint8
    elif total_bits <= 16: self.base_type = Type.uint16
    elif total_bits <= 32: self.base_type = Type.uint32
    else: self.base_type = Type.uint64
    self.total_bits = total_bits
    self._offsets = {}
    self._masks = {}
    pos = 0
    for bit_name, width in bits:
      self._offsets[bit_name] = pos
      self._masks[bit_name] = (1 << width) - 1
      pos += width

  def encode(self, values:dict[str, int]) -> int:
    """Pack named bit values into one integer, a name missing from `values` packing as 0."""
    result = 0
    for bit_name in self.bit_names:
      value = values.get(bit_name, 0)
      mask = self._masks[bit_name]
      if value > mask: raise ValueError(f"Bit '{bit_name}' value {value} exceeds max {mask}")
      result |= (value & mask) << self._offsets[bit_name]
    return result

  def decode(self, packed:int) -> dict[str, int]:
    """Unpack an integer into named bit values."""
    result = {}
    for bit_name in self.bit_names:
      mask = self._masks[bit_name]
      offset = self._offsets[bit_name]
      result[bit_name] = (packed >> offset) & mask
    return result

  @property
  def size(self) -> int:
    """Size of the packed base type in bytes, not bits."""
    return self.base_type.size

  def __str__(self) -> str:
    return f"Bitfield {self.name} ({self.total_bits} bits)"

#------------------------------------------------------------------------------------------ Padding

class Padding:
  """Fixed run of filler bytes for alignment, skipped on decode."""
  def __init__(self, size:int, fill:int=0x00) -> None:
    self.name = f"_pad_{size}"
    self.size = size
    self.fill = fill
    self.type = Type.pad

  def encode(self) -> bytes:
    """Filler bytes emitted in place of this padding."""
    return bytes([self.fill] * self.size)

  def __str__(self) -> str:
    return f"Padding({self.size})"

#------------------------------------------------------------------------------------------ Variant

class Variant:
  """
  Tagged union: the value of the `selector` field picks which field layout is active.
  The selector field must be added to the Struct before the variant.

  Example:
    Variant("payload", "type", {
      0: [Field(Type.uint32, "value_a")],
      1: [Field(Type.float, "value_b"), Field(Type.float, "extra")],
      2: [Field(Type.string, "text")],
    })
  """
  def __init__(self, name:str, selector:str, variants:dict[int, list[Field]]) -> None:
    self.name = name
    self.selector = selector
    self.variants = variants
    self.type = None

  def get_fields(self, selector_value:int) -> list[Field]:
    """Field layout for a selector value, empty for an unknown one."""
    return self.variants.get(selector_value, [])

  def __str__(self) -> str:
    return f"Variant {self.name} (selector={self.selector}, {len(self.variants)} variants)"

#------------------------------------------------------------------------------------------- Struct

class Struct:
  """
  Binary struct composed of Fields, usable standalone or as a block of a Message.

  `crc` is the record's own tail, a `crc` member at the end of the C struct:
  it travels with the record everywhere, a block of a `Message` included.
  Integrity of a whole message is the envelope's job, see `Frame`.
  """
  _auto_id = 0
  _codes: dict[int, str] = {}

  def __init__(
    self,
    code:int|None = None,
    name:str|None = None,
    endian:Endian|None = None,
    crc:CRC|None = None,
    align:int = 1,
  ) -> None:
    """
    Args:
      code: Unique across all Struct instances, required for a Message block
      name: Auto-generated if empty
      endian: Defaults to little
      crc: Appended to every record, behind its alignment padding
      align: Pad each record up to this byte multiple, 1 = none
    """
    if code is not None:
      existing = Struct._codes.get(code)
      if existing is not None and existing != name:
        raise ValueError(
          f"Code {code} already used by struct '{existing}', "
          f"cannot assign to '{name}'"
        )
      if name: Struct._codes[code] = name
    if not name:
      name = f"_struct_{Struct._auto_id}"
      Struct._auto_id += 1
    self.code: int|None = code
    self.name: str = name
    self.endian: Endian|None = endian
    self.crc: CRC|None = crc
    self.align: int = align
    self.fields: list[Field] = []
    self.fields_by_name: dict[str, Field] = {}
    self._bitfields: dict[str, Bitfield] = {}
    self._unions: dict[str, Variant] = {}
    self._paddings: list[Padding] = []
    self._members: list = [] # declaration order, drives encode/decode

  def add(self, *members) -> "Struct":
    """Add fields, bitfields, padding or variants, chainable."""
    for member in members:
      if isinstance(member, Field):
        if member.name in self.fields_by_name:
          raise ValueError(f"Duplicate field name: {member.name}")
        self.fields.append(member)
        self.fields_by_name[member.name] = member
        self._members.append(member)
      elif isinstance(member, Bitfield):
        self._bitfields[member.name] = member
        self._members.append(member)
      elif isinstance(member, Padding):
        self._paddings.append(member)
        self._members.append(member)
      elif isinstance(member, Variant):
        self._unions[member.name] = member
        self._members.append(member)
      else:
        raise TypeError(f"Unknown member type: {type(member)}")
    return self

  def get_field(self, name:str) -> Field|None:
    """Field by name."""
    return self.fields_by_name.get(name)

  def _get_endian(self, endian:Endian|None) -> Endian:
    """Resolve endianness: parameter > instance > default (little)."""
    if endian is not None: return endian
    if self.endian is not None: return self.endian
    return Endian.little

  def _encode_field(self, field:Field, value:Any, endian:Endian) -> bytes:
    if field.type == Type.string:
      if not isinstance(value, str):
        raise TypeError(f"Field '{field.name}' expects str, got {type(value).__name__}")
      return value.encode("utf-8") + b"\0"
    if field.type == Type.bytes:
      if not isinstance(value, (bytes, bytearray)):
        raise TypeError(f"Field '{field.name}' expects bytes, got {type(value).__name__}")
      return pack(endian.value + Type.uint16.value, len(value)) + value
    if field.is_array:
      if not isinstance(value, (list, tuple)):
        raise TypeError(f"Field '{field.name}' expects list/tuple, got {type(value).__name__}")
      if len(value) != field.length:
        raise ValueError(f"Field '{field.name}' expects {field.length} elements, got {len(value)}")
      result = b""
      for v in value:
        encoded = field.encode_value(v)
        result += pack(endian.value + field.type.value, encoded)
      return result
    if isinstance(value, (list, tuple)):
      raise TypeError(f"Field '{field.name}' expects scalar, got {type(value).__name__}")
    encoded = field.encode_value(value)
    return pack(endian.value + field.type.value, encoded)

  def _decode_field(self, field:Field, msg:bytes, offset:int, endian:Endian) -> tuple[Any, int]:
    """Decode one field → (value, next_offset)."""
    if field.type == Type.string:
      end = msg.find(0, offset)
      if end < 0: raise ValueError(f"Unterminated string in field '{field.name}'")
      return msg[offset:end].decode("utf-8"), end + 1
    if field.type == Type.bytes:
      if offset + 2 > len(msg):
        raise ValueError(f"Incomplete length prefix for field '{field.name}'")
      size = unpack_from(endian.value + Type.uint16.value, msg, offset)[0]
      offset += 2
      if offset + size > len(msg):
        raise ValueError(f"Incomplete data for field '{field.name}'")
      data = msg[offset:offset + size]
      return data, offset + size
    if field.is_array:
      values = []
      for _ in range(field.length):
        if offset + field.type.size > len(msg):
          raise ValueError(f"Incomplete array data for field '{field.name}'")
        raw = unpack_from(endian.value + field.type.value, msg, offset)[0]
        values.append(field.decode_value(raw))
        offset += field.type.size
      return values, offset
    if offset + field.type.size > len(msg):
      raise ValueError(f"Incomplete data for field '{field.name}'")
    raw = unpack_from(endian.value + field.type.value, msg, offset)[0]
    value = field.decode_value(raw)
    return value, offset + field.type.size

  def _encode_single(self, data:dict, endian:Endian|None=None) -> bytes:
    """Encode one record: members, alignment padding, `crc`."""
    endian = self._get_endian(endian)
    message = b""
    for member in self._members:
      if isinstance(member, Field):
        if member.name in data: value = data[member.name]
        elif member.optional: value = member.default
        else: raise KeyError(f"Field '{member.name}' not found in data for struct '{self.name}'")
        message += self._encode_field(member, value, endian)
      elif isinstance(member, Bitfield):
        if member.name not in data:
          raise KeyError(f"Bitfield '{member.name}' not found in data for struct '{self.name}'")
        packed = member.encode(data[member.name])
        message += pack(endian.value + member.base_type.value, packed)
      elif isinstance(member, Padding):
        message += member.encode()
      elif isinstance(member, Variant):
        selector_value = data.get(member.selector)
        if selector_value is None:
          raise KeyError(f"Variant selector '{member.selector}' not found")
        union_fields = member.get_fields(selector_value)
        union_data = data.get(member.name, {})
        for field in union_fields:
          if field.name in union_data: value = union_data[field.name]
          elif field.optional: value = field.default
          else: raise KeyError(f"Variant field '{field.name}' not found in '{member.name}'")
          message += self._encode_field(field, value, endian)
    if self.align > 1:
      remainder = len(message) % self.align
      if remainder: message += b"\x00" * (self.align - remainder)
    if self.crc: message = self.crc.encode(message)
    return message

  def _decode_single(self, msg:bytes, endian:Endian|None=None) -> tuple[dict, int]:
    """Decode one record → (data, bytes_consumed), its `crc` verified."""
    endian = self._get_endian(endian)
    data = {}
    offset = 0
    for member in self._members:
      if isinstance(member, Field):
        value, offset = self._decode_field(member, msg, offset, endian)
        data[member.name] = value
      elif isinstance(member, Bitfield):
        if offset + member.size > len(msg):
          raise ValueError(f"Incomplete data for bitfield '{member.name}'")
        packed = unpack_from(endian.value + member.base_type.value, msg, offset)[0]
        data[member.name] = member.decode(packed)
        offset += member.size
      elif isinstance(member, Padding):
        offset += member.size
      elif isinstance(member, Variant):
        selector_value = data.get(member.selector)
        if selector_value is None:
          raise KeyError(f"Variant selector '{member.selector}' not found")
        union_fields = member.get_fields(selector_value)
        union_data = {}
        for field in union_fields:
          value, offset = self._decode_field(field, msg, offset, endian)
          union_data[field.name] = value
        data[member.name] = union_data
    # mirrors the alignment padding added by _encode_single
    if self.align > 1:
      remainder = offset % self.align
      if remainder: offset += self.align - remainder
    if offset > len(msg): # padding and alignment skip bytes without reading them
      raise ValueError(f"Incomplete data for struct '{self.name}': {len(msg)} of {offset} bytes")
    if self.crc:
      n = self.crc.width // 8
      crc = msg[offset:offset + n]
      if len(crc) < n or self.crc.to_int(crc) != self.crc.checksum(msg[:offset]):
        raise ValueError(f"CRC check failed for struct '{self.name}'")
      offset += n
    return data, offset

  def encode(self, data_list:list[dict]|dict, endian:Endian|None=None) -> bytes:
    """Encode one record or a list of records, each with its `crc`."""
    if isinstance(data_list, dict): data_list = [data_list]
    return b"".join(self._encode_single(data, endian) for data in data_list)

  def decode(self, message:bytes, endian:Endian|None=None) -> list[dict[str, Any]]|dict[str, Any]:
    """Decode every record in the message, a bare dict when there is exactly one."""
    data_list = self.records(message, endian)
    return data_list[0] if len(data_list) == 1 else data_list

  def records(self, payload:bytes, endian:Endian|None=None) -> list[dict[str, Any]]:
    """Every record of `payload`, as a list even when there is one."""
    data_list = []
    while payload:
      data, offset = self._decode_single(payload, endian)
      if offset <= 0:
        raise ValueError(f"Struct '{self.name}' consumes no bytes, cannot decode a stream")
      data_list.append(data)
      payload = payload[offset:]
    return data_list

  def block(self, records:list[dict]|dict, endian:Endian|None=None) -> bytes:
    """
    Records behind their block header `| code u16 | size u16 |` for a `Message`.
    `size` counts the record bytes only; `code` is required.
    """
    if self.code is None: raise ValueError(f"Struct '{self.name}' needs a code for a block")
    if isinstance(records, dict): records = [records]
    endian = self._get_endian(endian)
    payload = b"".join(self._encode_single(record, endian) for record in records)
    return pack(endian.value + "HH", self.code, len(payload)) + payload

  def _fixed_size(self) -> int|None:
    """Bytes of one record before padding and `crc`; `None` when a member has no fixed size."""
    total = 0
    for member in self._members:
      if isinstance(member, Field):
        if member.type.size == 0: return None
        total += member.type.size * (member.length if member.is_array else 1)
      elif isinstance(member, (Bitfield, Padding)):
        total += member.size
      else:
        return None # a variant is as long as its selected branch
    return total

  def export_c_header(self, guard:str|None=None) -> str:
    """
    Export as a C header, `guard` defaulting to `_NAME_H_`.

    The struct mirrors the wire: alignment padding and the `crc` tail are members too,
    the tail as bytes because it travels big-endian whatever the struct's own order.
    A record of variable size cannot place them, so it says so in a comment.
    """
    if guard is None: guard = f"_{self.name.upper()}_H_"
    lines = [
      f"#ifndef {guard}",
      f"#define {guard}",
      "",
      "#include <stdint.h>",
      "",
    ]
    for bf in self._bitfields.values():
      lines.append("typedef struct {")
      for bit_name, width in bf.bits:
        lines.append(f"  {bf.base_type.c_type} {bit_name} : {width};")
      lines.append(f"}} {self.name}_{bf.name}_t;")
      lines.append("")
    lines.append("typedef struct __attribute__((packed)) {")
    for member in self._members:
      if isinstance(member, Field):
        if member.is_array:
          lines.append(f"  {member.type.c_type} {member.name}[{member.length}];")
        elif member.type == Type.string:
          lines.append(f"  char {member.name}[];  // null-terminated")
        elif member.type == Type.bytes:
          lines.append(f"  uint16_t {member.name}_len;")
          lines.append(f"  uint8_t {member.name}[];")
        else:
          comment = f"  // [{member.unit}]" if member.unit else ""
          lines.append(f"  {member.type.c_type} {member.name};{comment}")
      elif isinstance(member, Bitfield):
        lines.append(f"  {self.name}_{member.name}_t {member.name};")
      elif isinstance(member, Padding):
        lines.append(f"  uint8_t _pad[{member.size}];")
      elif isinstance(member, Variant):
        lines.append(f"  // Variant '{member.name}' - selector: {member.selector}")
        lines.append("  union {")
        for variant_id, variant_fields in member.variants.items():
          lines.append(f"    struct {{ // variant {variant_id}")
          for field in variant_fields:
            lines.append(f"      {field.type.c_type} {field.name};")
          lines.append("    };")
        lines.append(f"  }} {member.name};")
    fixed = self._fixed_size()
    if fixed is None:
      if self.align > 1 or self.crc:
        lines.append("  // variable size: alignment padding and crc follow the record on the wire")
    else:
      pad = -fixed % self.align
      if pad: lines.append(f"  uint8_t _align[{pad}];")
      if self.crc: lines.append(f"  uint8_t crc[{self.crc.width // 8}]; // big-endian")
    lines.append(f"}} {self.name}_t;")
    lines.append("")
    lines.append(f"#endif // {guard}")
    return "\n".join(lines)

  def export_doc(self) -> str:
    """Export as a Markdown field table."""
    lines = [f"# Struct: {self.name}", ""]
    if self.code is not None:
      lines.append(f"**Code:** 0x{self.code:04X}")
      lines.append("")
    lines.append("## Fields")
    lines.append("")
    lines.append("| Name | Type | Unit | Description |")
    lines.append("|------|------|------|-------------|")
    for member in self._members:
      if isinstance(member, Field):
        type_str = member.type.name
        if member.is_array: type_str += f"[{member.length}]"
        unit = member.unit or "-"
        desc = ""
        if member.scale != 1: desc += f"scale={member.scale} "
        if member.offset: desc += f"offset={member.offset} "
        if member.optional: desc += "optional "
        lines.append(f"| {member.name} | {type_str} | {unit} | {desc.strip() or '-'} |")
      elif isinstance(member, Bitfield):
        bits_desc = ", ".join([f"{n}:{w}" for n, w in member.bits])
        lines.append(f"| {member.name} | bitfield | - | {bits_desc} |")
      elif isinstance(member, Padding):
        lines.append(f"| _padding_ | pad[{member.size}] | - | alignment |")
      elif isinstance(member, Variant):
        lines.append(f"| {member.name} | variant | - | selector={member.selector} |")
    return "\n".join(lines)

  def __iter__(self) -> Iterator[Field]:
    return iter(self.fields)

  def __len__(self) -> int:
    return len(self.fields)

  def __getitem__(self, key:int|str) -> Field:
    if isinstance(key, int): return self.fields[key]
    return self.fields_by_name[key]

  def __str__(self) -> str:
    if self.code is not None: return f"Struct {self.code}:{self.name}"
    return f"Struct {self.name}"

  def __repr__(self) -> str:
    return f"Struct(code={self.code!r}, name={self.name!r}, fields={len(self.fields)})"

#--------------------------------------------------------------------------------------------- Wire

class Message:
  """
  Body of a frame: blocks of several structs, each one `| code u16 | size u16 | records |`.
  A block is read out of exactly its `size` bytes, so a header that lies is refused
  rather than left to shift everything after it. Integrity belongs to `Frame`, the envelope.
  """
  BLOCK_HEAD = 4 # code and size

  def __init__(self, *structs:Struct, endian:Endian|None=Endian.little) -> None:
    """
    Args:
      structs: Each must have a `code` set
      endian: Applied to block headers and to every payload, overriding per-struct endian
    """
    self.structs: tuple[Struct, ...] = structs
    self.structs_by_code: dict[int, Struct] = {}
    self.structs_by_name: dict[str, Struct] = {}
    for struct in self.structs:
      if struct.code is None:
        raise ValueError(f"Struct '{struct.name}' must have a code for use in Message")
      self.structs_by_code[struct.code] = struct
      self.structs_by_name[struct.name] = struct
    self.endian: Endian = endian or Endian.little

  def encode(self, data_dict:dict[str, dict|list[dict]]) -> bytes:
    """Encode `{struct_name: record or records}` into one body, a block per name."""
    body = b""
    for struct_name, records in data_dict.items():
      if struct_name not in self.structs_by_name: raise KeyError(f"Unknown struct: {struct_name}")
      body += self.structs_by_name[struct_name].block(records, self.endian)
    return body

  def decode(self, body:bytes) -> dict[str, list[dict]]:
    """Decode a body → `{struct_name: records}`, a list per name even where it holds one."""
    data_dict: dict[str, list[dict]] = {}
    while body:
      if len(body) < self.BLOCK_HEAD: raise ValueError("Incomplete block header")
      code, size = unpack_from(self.endian.value + "HH", body, 0)
      body = body[self.BLOCK_HEAD:]
      if code not in self.structs_by_code: raise KeyError(f"Unknown struct code: {code}")
      if size > len(body):
        raise ValueError(f"Block declares {size} bytes, {len(body)} left in the message")
      struct = self.structs_by_code[code]
      block, body = body[:size], body[size:]
      data_dict.setdefault(struct.name, []).extend(struct.records(block, self.endian))
    return data_dict

  def get_struct(self, tag:int|str) -> Struct:
    """Struct by code (int) or name (str)."""
    if isinstance(tag, int): return self.structs_by_code[tag]
    return self.structs_by_name[tag]

  def __iter__(self) -> Iterator[Struct]:
    return iter(self.structs)

  def __len__(self) -> int:
    return len(self.structs)

  def __getitem__(self, key:int|str) -> Struct:
    return self.get_struct(key)

Body = TypeVar("Body", bytes, dict)
"""What a `Frame` carries: raw bytes, or the dict of a `Message`."""

class Frame(Generic[Body]):
  """
  Envelope of one message on a raw byte link: `| AA 55 | len u16 | body | crc |`.
  `len` counts body and CRC, the CRC covers the body: the mirror of `FRAME_t` in C.

  Given a `Message`, `encode` takes its dict and `feed` yields dicts; bare, both move bytes.
  `Body` follows: `Frame()` is a `Frame[bytes]`, `Frame(message)` a `Frame[dict]`.
  `feed` walks a stream and yields every frame that verifies.
  The sync pair can occur inside data, so a frame that fails is dropped from the byte
  behind its first sync byte and the hunt starts there, not behind the whole frame.
  A false pair with a plausible length holds the frames behind it until its bytes are in,
  so `limit` also bounds that delay.
  """
  SYNC = b"\xAA\x55"
  FRAME_HEAD = 4 # sync pair and length

  @overload
  def __init__(
    self:"Frame[bytes]",
    message:None = None,
    *,
    crc:CRC|None = crc32_iso,
    limit:int = 1024,
    endian:Endian = Endian.little,
  ) -> None: ...
  @overload
  def __init__(
    self:"Frame[dict]",
    message:Message,
    *,
    crc:CRC|None = crc32_iso,
    limit:int = 1024,
    endian:Endian = Endian.little,
  ) -> None: ...
  def __init__(
    self,
    message:Message|None = None,
    *,
    crc:CRC|None = crc32_iso,
    limit:int = 1024,
    endian:Endian = Endian.little,
  ) -> None:
    """
    Args:
      message: What a body is made of; `None` carries raw bytes
      crc: Appended behind the body, `None` = none
      limit: Longest body accepted [B], a longer `len` is structural nonsense
      endian: Byte order of the length field
    """
    self.message: Message|None = message
    self.crc: CRC|None = crc
    self.limit: int = limit
    self.endian: Endian = endian
    self._len = endian.value + "H"
    self.errors: int = 0 # frames dropped on length or CRC
    self._buf = bytearray()

  @property
  def crc_size(self) -> int:
    return self.crc.width // 8 if self.crc else 0

  @property
  def pending(self) -> int:
    """Bytes held back: a frame still on its way, or a sync pair split by the chunk."""
    return len(self._buf)

  def encode(self, data:Body) -> bytes:
    """Frame one message, or raw bytes, for the wire."""
    body = self.message.encode(data) if self.message else data
    if self.crc: body = self.crc.encode(body)
    return self.SYNC + pack(self._len, len(body)) + body

  def feed(self, data:bytes) -> Iterator[Body]:
    """Take a stretch of the stream, yield every complete frame in it: a dict, or raw bytes."""
    self._buf += data
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
      if self.crc_size <= length <= self.limit + self.crc_size:
        if len(self._buf) < total: return # the rest is still on the wire
        body = self._body(bytes(self._buf[self.FRAME_HEAD:total]))
        if body is not None:
          del self._buf[:total]
          yield self.message.decode(body) if self.message else body
          continue
      self.errors += 1
      del self._buf[:1] # the pair was data, so the hunt goes on from behind its first byte

  def _body(self, framed:bytes) -> bytes|None:
    """The body of one candidate frame, `None` when its CRC says the bytes are not one."""
    return self.crc.decode(framed) if self.crc else framed

  def reset(self) -> None:
    """Drop what is under assembly, the link is gone."""
    self._buf.clear()

#-------------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  sensor = Struct(name="sensor", endian=Endian.little, crc=crc32_iso)
  sensor.add(
    Field(Type.uint32, "timestamp", "s"),
    Bitfield("flags", [("enabled", 1), ("error", 1), ("mode", 6)]),
    Field(Type.float, "temperature", "°C"),
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
