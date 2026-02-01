# xaeian/cstruct.py

"""
Binary struct serialization for C-like structures.

Provides encoding/decoding of binary data with support for:
- Numeric types: `int8`-`int64`, `uint8`-`uint64`, `float`, `double`
- Strings (null-terminated) and byte arrays (length-prefixed)
- Fixed-size arrays
- Scaling, offset, and custom encode/decode transforms
- CRC checksums and CRC-based authentication
- Framing protocol for multiple struct types
- Bitfields for compact flag storage
- Padding and alignment
- Optional fields and variants (tagged unions)
- Schema export (C headers, Markdown documentation)

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
from typing import Callable, Any
from numbers import Real

from .crc import CRC, crc32_iso

class Type(Enum):
  """
  Supported data types for struct fields.

  Values are format characters for `struct` module
  (except `string`, `bytes`, `pad`).

  Example:
    >>> Type.uint16.size
    2
    >>> Type.float.c_type
    'float'
  """
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
  string = "str"   # null-terminated UTF-8 string
  bytes = "byte"   # length-prefixed (uint16) byte array
  pad = "pad"      # padding bytes (ignored on decode)

  @property
  def size(self) -> int:
    """Size in bytes for fixed-size types, 0 for variable-size."""
    if self.value in ("str", "byte", "pad"): return 0
    return calcsize(self.value)

  @property
  def is_integer(self) -> bool:
    return self.value not in ("f", "d", "str", "byte", "pad")

  @property
  def is_float(self) -> bool:
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
      "str": "char*", "byte": "uint8_t*", "pad": "uint8_t"
    }
    return mapping.get(self.value, "unknown")

def type_size(ctype:Type) -> int:
  """Return size in bytes for a given type (0 for variable-size)."""
  return ctype.size

class Endian(Enum):
  """Byte order for binary encoding/decoding."""
  little = "<"
  big = ">"
  native = "="
  network = "!"

#---------------------------------------------------------------------------------------- Field

class Field:
  """
  Describes a single field within a Struct.
  Transforms applied during encoding: raw = (value * scale) + offset, then encoder()
  Transforms applied during decoding: value = decoder((raw - offset) / scale)
  """
  _auto_id = 0

  def __init__(
    self,
    ctype: Type,
    name: str = "",
    unit: str = "",
    length: int = 1,
    scale: float = 1,
    point_shift: int = 0,
    offset: float = 0,
    encoder: Callable[[Real], Real]|None = None,
    decoder: Callable[[Real], Real]|None = None,
    precision: int = 3,
    optional: bool = False,
    default: Any = None,
  ) -> None:
    """
    Args:
      ctype: Data type (Type enum)
      name: Field name (auto-generated if empty)
      unit: Unit string for documentation (e.g., "V", "Hz")
      length: Array length (1 = scalar, >1 = fixed-size array)
      scale: Multiply when encoding, divide when decoding
      point_shift: If scale==1, sets scale = 10**point_shift
      offset: Add when encoding, subtract when decoding
      encoder: Custom transform applied after scale/offset during encoding
      decoder: Custom transform applied after scale/offset during decoding
      precision: Decimal places for rounding float values
      optional: If True, field can be missing (uses default value)
      default: Default value when optional field is missing
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
    return self.length > 1

  @property
  def is_variable_size(self) -> bool:
    return self.type.value in ("str", "byte")

  def encode_value(self, value:Real, for_pack:bool=True) -> Real:
    """Apply encoding transforms to a value."""
    if self.scale != 1: value *= self.scale
    if self.offset: value += self.offset
    if self.encoder: value = self.encoder(value)
    if for_pack and self.type.is_integer: value = int(value)
    return value

  def decode_value(self, value:Real) -> Real:
    """Apply decoding transforms to a value."""
    if self.offset: value -= self.offset
    if self.scale != 1: value /= self.scale
    if self.decoder: value = self.decoder(value)
    if self.type.is_float: value = round(value, self.precision)
    return value

  def __str__(self):
    return f"Field {self.name}[{self.unit}]" if self.unit else f"Field {self.name}"

  def __repr__(self):
    parts = [f"Field({self.type.name!r}, {self.name!r}"]
    if self.unit: parts.append(f", unit={self.unit!r}")
    if self.length > 1: parts.append(f", length={self.length}")
    if self.scale != 1: parts.append(f", scale={self.scale}")
    parts.append(")")
    return "".join(parts)

#------------------------------------------------------------------------------------- Bitfield

class Bitfield:
  """
  Packed bitfield for compact flag storage.
  Multiple named bits packed into uint8/16/32.

  Example:
    flags = Bitfield("status", [
      ("enabled", 1),
      ("error", 1),
      ("mode", 3),
      ("reserved", 3),
    ])  # Total 8 bits = uint8
  """
  def __init__(self, name:str, bits:list[tuple[str, int]], base_type:Type=None):
    """
    Args:
      name: Bitfield name
      bits: List of (bit_name, bit_width) tuples
      base_type: Override auto-detected base type (uint8/16/32/64)
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
    # Precompute bit positions
    self._offsets = {}
    self._masks = {}
    pos = 0
    for bit_name, width in bits:
      self._offsets[bit_name] = pos
      self._masks[bit_name] = (1 << width) - 1
      pos += width

  def encode(self, values:dict[str, int]) -> int:
    """Pack bit values into single integer."""
    result = 0
    for bit_name in self.bit_names:
      value = values.get(bit_name, 0)
      mask = self._masks[bit_name]
      if value > mask: raise ValueError(f"Bit '{bit_name}' value {value} exceeds max {mask}")
      result |= (value & mask) << self._offsets[bit_name]
    return result

  def decode(self, packed:int) -> dict[str, int]:
    """Unpack integer into bit values."""
    result = {}
    for bit_name in self.bit_names:
      mask = self._masks[bit_name]
      offset = self._offsets[bit_name]
      result[bit_name] = (packed >> offset) & mask
    return result

  @property
  def size(self) -> int:
    return self.base_type.size

  def __str__(self):
    return f"Bitfield {self.name} ({self.total_bits} bits)"

#-------------------------------------------------------------------------------------- Padding

class Padding:
  """
  Padding for alignment. Ignored on decode.

  Example:
    Padding(4)           # 4 zero bytes
    Padding(4, fill=0xFF) # 4 bytes of 0xFF
  """
  def __init__(self, size:int, fill:int=0x00):
    self.name = f"_pad_{size}"
    self.size = size
    self.fill = fill
    self.type = Type.pad

  def encode(self) -> bytes:
    return bytes([self.fill] * self.size)

  def __str__(self):
    return f"Padding({self.size})"

#-------------------------------------------------------------------------------------- Variant

class Variant:
  """
  Variant type (union) - one of multiple possible field layouts.
  Selector field determines which variant is active.

  Example:
    Variant("payload", "type", {
      0: [Field(Type.uint32, "value_a")],
      1: [Field(Type.float, "value_b"), Field(Type.float, "extra")],
      2: [Field(Type.string, "text")],
    })
  """
  def __init__(self, name:str, selector:str, variants:dict[int, list[Field]]):
    """
    Args:
      name: Variant name
      selector: Name of field that determines variant (must be defined before variant)
      variants: Dict mapping selector values to field lists
    """
    self.name = name
    self.selector = selector
    self.variants = variants
    self.type = None  # marker for Struct to recognize

  def get_fields(self, selector_value:int) -> list[Field]:
    """Get field list for given selector value."""
    return self.variants.get(selector_value, [])

  def __str__(self):
    return f"Variant {self.name} (selector={self.selector}, {len(self.variants)} variants)"

#--------------------------------------------------------------------------------------- Struct

class Struct:
  """
  Binary struct composed of Fields.

  Can be used standalone or as part of a Frame for multi-struct protocols.

  CRC layers (applied in order during encoding, reverse during decoding):
  - crc_frame: Per-record CRC
  - crc_auth: Authentication CRC (use non-standard polynomial as shared secret)
  - crc: Outer CRC for data integrity
  """
  _auto_id = 0
  _codes: dict[int, str] = {}

  def __init__(
    self,
    code: int|None = None,
    name: str|None = None,
    endian: Endian|None = None,
    crc: CRC|None = None,
    crc_frame: CRC|None = None,
    crc_auth: CRC|None = None,
    align: int = 1,
  ) -> None:
    """
    Args:
      code: Unique type code for Frame protocol (optional)
      name: Struct name (auto-generated if empty)
      endian: Default byte order (little-endian if not specified)
      crc: Outer CRC for data integrity
      crc_frame: Per-record CRC
      crc_auth: Authentication CRC (non-standard params as shared secret)
      align: Struct alignment (1 = no alignment, 4 = 32-bit aligned, etc.)
    """
    if code is not None:
      if code in Struct._codes:
        raise ValueError(
          f"Code {code} already used by struct '{Struct._codes[code]}', "
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
    self.crc_frame: CRC|None = crc_frame
    self.crc_auth: CRC|None = crc_auth
    self.align: int = align
    self.fields: list[Field] = []
    self.fields_by_name: dict[str, Field] = {}
    self._bitfields: dict[str, Bitfield] = {}
    self._unions: dict[str, Variant] = {}
    self._paddings: list[Padding] = []
    self._members: list = []  # ordered list of all members

  def add(self, *members) -> "Struct":
    """Add fields, bitfields, padding, or unions. Returns self for chaining."""
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
    """Get field by name, or None if not found."""
    return self.fields_by_name.get(name)

  def _get_endian(self, endian:Endian|None) -> Endian:
    """Resolve endianness: parameter > instance > default (little)."""
    if endian is not None: return endian
    if self.endian is not None: return self.endian
    return Endian.little

  def _encode_field(self, field:Field, value:Any, endian:Endian) -> bytes:
    """Encode a single field value to bytes."""
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
    # Scalar numeric value
    if isinstance(value, (list, tuple)):
      raise TypeError(f"Field '{field.name}' expects scalar, got {type(value).__name__}")
    encoded = field.encode_value(value)
    return pack(endian.value + field.type.value, encoded)

  def _decode_field(self, field:Field, msg:bytes, offset:int, endian:Endian) -> tuple[Any, int]:
    """Decode a single field from bytes. Returns (value, new_offset)."""
    if field.type == Type.string:
      chars = []
      while offset < len(msg) and msg[offset] != 0:
        chars.append(chr(msg[offset]))
        offset += 1
      if offset >= len(msg): raise ValueError(f"Unterminated string in field '{field.name}'")
      offset += 1  # skip null terminator
      return "".join(chars), offset
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
    # Scalar numeric value
    if offset + field.type.size > len(msg):
      raise ValueError(f"Incomplete data for field '{field.name}'")
    raw = unpack_from(endian.value + field.type.value, msg, offset)[0]
    value = field.decode_value(raw)
    return value, offset + field.type.size

  def _encode_single(self, data:dict, endian:Endian|None=None) -> bytes:
    """Encode a single record (without outer CRC layers)."""
    endian = self._get_endian(endian)
    message = b""
    for member in self._members:
      if isinstance(member, Field):
        if member.name not in data:
          if member.optional: value = member.default
          else: raise KeyError(f"Field '{member.name}' not found in data for struct '{self.name}'")
        else:
          value = data[member.name]
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
          if field.name not in union_data:
            if field.optional: value = field.default
            else: raise KeyError(f"Variant field '{field.name}' not found in '{member.name}'")
          else:
            value = union_data[field.name]
          message += self._encode_field(field, value, endian)
    # Apply alignment padding
    if self.align > 1:
      remainder = len(message) % self.align
      if remainder: message += b"\x00" * (self.align - remainder)
    if self.crc_frame: message = self.crc_frame.encode(message)
    return message

  def _decode_single(self, msg:bytes, endian:Endian|None=None) -> tuple[dict, int]:
    """Decode a single record (without outer CRC layers). Returns (data, bytes_consumed)."""
    endian = self._get_endian(endian)
    if self.crc_frame:
      msg = self.crc_frame.decode(msg)
      if msg is None: raise ValueError(f"CRC frame check failed for struct '{self.name}'")
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
        offset += member.size  # skip padding bytes
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
    return data, offset

  def encode(self, data_list:list[dict]|dict, endian:Endian|None=None) -> bytes:
    """
    Encode one or more records with all CRC layers.

    Args:
      data_list: Single dict or list of dicts with field values
      endian: Byte order override

    Returns:
      Encoded bytes with CRC
    """
    if isinstance(data_list, dict): data_list = [data_list]
    message = b""
    for data in data_list: message += self._encode_single(data, endian)
    if self.crc_auth: message = self.crc_auth.encode(message)
    if self.crc: message = self.crc.encode(message)
    return message

  def decode(self, message:bytes, endian:Endian|None=None) -> list[dict]|dict:
    """
    Decode one or more records with all CRC layers.

    Args:
      message: Encoded bytes with CRC
      endian: Byte order override

    Returns:
      Single dict if one record, list of dicts if multiple
    """
    if self.crc:
      message = self.crc.decode(message)
      if message is None: raise ValueError(f"CRC check failed for struct '{self.name}'")
    if self.crc_auth:
      message = self.crc_auth.decode(message)
      if message is None: raise ValueError(f"CRC auth check failed for struct '{self.name}'")
    data_list = []
    while message:
      data, offset = self._decode_single(message, endian)
      data_list.append(data)
      message = message[offset:]
    return data_list[0] if len(data_list) == 1 else data_list

  def export_c_header(self, guard:str=None) -> str:
    """
    Export struct as C header file.

    Args:
      guard: Include guard name (auto-generated if None)
    """
    if guard is None: guard = f"_{self.name.upper()}_H_"
    lines = [
      f"#ifndef {guard}",
      f"#define {guard}",
      "",
      "#include <stdint.h>",
      "",
    ]
    # Bitfield typedefs
    for bf in self._bitfields.values():
      lines.append(f"typedef struct {{")
      for bit_name, width in bf.bits:
        lines.append(f"  {bf.base_type.c_type} {bit_name} : {width};")
      lines.append(f"}} {self.name}_{bf.name}_t;")
      lines.append("")
    # Main struct
    lines.append(f"typedef struct __attribute__((packed)) {{")
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
        lines.append(f"  union {{")
        for variant_id, variant_fields in member.variants.items():
          lines.append(f"    struct {{ // variant {variant_id}")
          for field in variant_fields:
            lines.append(f"      {field.type.c_type} {field.name};")
          lines.append(f"    }};")
        lines.append(f"  }} {member.name};")
    lines.append(f"}} {self.name}_t;")
    lines.append("")
    lines.append(f"#endif // {guard}")
    return "\n".join(lines)

  def export_doc(self) -> str:
    """Export struct as markdown documentation."""
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
        if member.optional: desc += f"optional "
        lines.append(f"| {member.name} | {type_str} | {unit} | {desc.strip() or '-'} |")
      elif isinstance(member, Bitfield):
        bits_desc = ", ".join([f"{n}:{w}" for n, w in member.bits])
        lines.append(f"| {member.name} | bitfield | - | {bits_desc} |")
      elif isinstance(member, Padding):
        lines.append(f"| _padding_ | pad[{member.size}] | - | alignment |")
      elif isinstance(member, Variant):
        lines.append(f"| {member.name} | variant | - | selector={member.selector} |")
    return "\n".join(lines)

  def __iter__(self):
    return iter(self.fields)

  def __len__(self):
    return len(self.fields)

  def __getitem__(self, key:int|str) -> Field:
    if isinstance(key, int): return self.fields[key]
    return self.fields_by_name[key]

  def __str__(self):
    if self.code is not None: return f"Struct {self.code}:{self.name}"
    return f"Struct {self.name}"

  def __repr__(self):
    return f"Struct(code={self.code!r}, name={self.name!r}, fields={len(self.fields)})"

#---------------------------------------------------------------------------------------- Frame

class Frame:
  """
  Frame protocol for multiplexing multiple Struct types.
  Multiple blocks can be concatenated. Outer CRC wraps entire frame.
  | size-uint16 | type-uint16 |
  |          message          |
  |          ...              |
  """
  def __init__(
    self,
    *structs: Struct,
    endian: Endian|None = Endian.little,
    crc: CRC|None = crc32_iso,
    crc_auth: CRC|None = None,
  ) -> None:
    """
    Args:
      structs: Struct definitions (must have code and name set)
      endian: Byte order for frame headers
      crc: Outer CRC for data integrity
      crc_auth: Authentication CRC (non-standard params as shared secret)
    """
    self.structs: tuple[Struct, ...] = structs
    self.structs_by_code: dict[int, Struct] = {}
    self.structs_by_name: dict[str, Struct] = {}
    for struct in self.structs:
      if struct.code is None:
        raise ValueError(f"Struct '{struct.name}' must have a code for use in Frame")
      self.structs_by_code[struct.code] = struct
      self.structs_by_name[struct.name] = struct
    self.endian: Endian = endian or Endian.little
    self.crc: CRC|None = crc
    self.crc_auth: CRC|None = crc_auth

  def encode(self, data_dict:dict[str, dict|list[dict]]) -> bytes:
    """
    Encode multiple struct types into a single frame.

    Args:
      data_dict: Dict mapping struct names to data (dict or list of dicts)

    Returns:
      Encoded frame bytes with headers and CRC
    """
    message = b""
    for struct_name, data_list in data_dict.items():
      if struct_name not in self.structs_by_name:
        raise KeyError(f"Unknown struct: {struct_name}")
      if not isinstance(data_list, list): data_list = [data_list]
      struct = self.structs_by_name[struct_name]
      payload = b"".join([struct._encode_single(data, self.endian) for data in data_list])
      # Frame header: size (uint16) + type code (uint16)
      message += pack(self.endian.value + Type.uint16.value, len(payload))
      message += pack(self.endian.value + Type.uint16.value, struct.code)
      message += payload
    if self.crc_auth: message = self.crc_auth.encode(message)
    if self.crc: message = self.crc.encode(message)
    return message

  def decode(self, frame:bytes) -> dict[str, dict|list[dict]]:
    """
    Decode a frame into multiple struct types.

    Args:
      frame: Encoded frame bytes

    Returns:
      Dict mapping struct names to decoded data
    """
    if self.crc:
      frame = self.crc.decode(frame)
      if frame is None: raise ValueError("CRC check failed in Frame.decode()")
    if self.crc_auth:
      frame = self.crc_auth.decode(frame)
      if frame is None: raise ValueError("CRC auth check failed in Frame.decode()")
    data_dict: dict[str, dict|list[dict]] = {}
    while frame:
      if len(frame) < 4: raise ValueError("Incomplete frame header")
      size = unpack_from(self.endian.value + Type.uint16.value, frame, 0)[0]
      struct_code = unpack_from(self.endian.value + Type.uint16.value, frame, 2)[0]
      frame = frame[4:]
      if struct_code not in self.structs_by_code:
        raise KeyError(f"Unknown struct code: {struct_code}")
      struct = self.structs_by_code[struct_code]
      # Decode all records of this struct type within the block
      remaining = size
      while remaining > 0:
        data, consumed = struct._decode_single(frame, self.endian)
        if struct.name in data_dict:
          existing = data_dict[struct.name]
          if not isinstance(existing, list): data_dict[struct.name] = [existing]
          data_dict[struct.name].append(data)
        else:
          data_dict[struct.name] = data
        frame = frame[consumed:]
        remaining -= consumed
    return data_dict

  def get_struct(self, tag:int|str) -> Struct:
    """Get struct by code (int) or name (str)."""
    if isinstance(tag, int): return self.structs_by_code[tag]
    return self.structs_by_name[tag]

  def __iter__(self):
    return iter(self.structs)

  def __len__(self):
    return len(self.structs)

  def __getitem__(self, key:int|str) -> Struct:
    return self.get_struct(key)

#---------------------------------------------------------------------------------------- Tests

if __name__ == "__main__":
  sensor = Struct(name="sensor", endian=Endian.little, crc=crc32_iso)
  sensor.add(
    Field(Type.uint32, "timestamp", "s"),
    Bitfield("flags", [("enabled", 1), ("error", 1), ("mode", 6)]),
    Field(Type.float, "temperature", "°C"),
  )
  data = {"timestamp": 1234567890, "flags": {"enabled": 1, "error": 0, "mode": 5}, "temperature": 23.5}
  encoded = sensor.encode(data)
  decoded = sensor.decode(encoded)
  print("data:", data)
  print("encoded:", encoded.hex(" "))
  print("decoded:", decoded)
  print()
  print("C header:")
  print(sensor.export_c_header())