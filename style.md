# Python Style

## Format
- 95 chars max, 2 spaces indent
- Single blank lines only, no double
- No blank after class docstring

## Spacing

```python
if x: # YES
if(x): # NO
if (x): # NO
d["key"] # YES
```
## Type Hints

```python
# Tight single-line
def get(key:str, default:int=0) -> int:

# Spaced multi-line
def connect(
  host: str,
  port: int = 5432,
) -> Connection:

# Use | not Union
def load(path:str) -> dict|None:
```

## Style
```python
# One-liners when short
if not data: return None
if err: raise ValueError("msg")

# Double quotes, f-strings
name = "value"
f"Hello {name}"

# Trailing comma in multi-line
config = {
  "host": "localhost",
  "port": 8080,
}
```

## Naming
```python
snake_case     # variables, functions
PascalCase     # classes
UPPER_CASE     # constants
_prefix        # private
timeout_ms     # unit suffix
```

## Separators
```python
# 95 chars total: # + dashes + space + Name
#-------------------------------------------------------------------------------------- Section
  #------------------------------------------------------------------------------------ Nested
```

## Docstrings
```python
class Foo:
  """Short description."""
  def __init__(self):
    pass

def bar():
  """
  Long description.

  Args:
    x: Input.

  Returns:
    Result.
  """
  pass
```