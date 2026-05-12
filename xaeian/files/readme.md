# `xaeian.files`

File and directory operations with format helpers (JSON, CSV, INI, YAML), path manipulation, context-based root scoping, async variants. Zero dependencies for core; YAML requires `pip install xaeian[yaml]`.

## `FILE`

Read, write, append, hash. Auto-creates parent directories on write.

```py
from xaeian import FILE

FILE.save("data.txt", "Hello!")
FILE.load("data.txt")              # → "Hello!"
FILE.append("data.txt", "\nmore")
FILE.load("data.bin", binary=True) # → bytes
FILE.hash("data.bin", algo="md5")  # → "5d41402abc..."
FILE.exists("data.txt")            # → True
```

## `JSON`

Auto `.json` extension. Three save modes: compact, pretty (human-edited), smart (numeric arrays inline).

```py
from xaeian import JSON

JSON.save("config", {"debug": True, "port": 8080})
JSON.load("config")                   # → dict
JSON.load("missing", otherwise={})    # → {} if not found
JSON.save_pretty("config", cfg)       # indented, sorted (configs)
JSON.save_smart("data", measurements) # compact arrays inline (machine state)
```

## `CSV`

`list[dict]` or column vectors. Optional per-column type casting.

```py
from xaeian import CSV

CSV.save("users", [{"name": "Jan", "age": 30}])
CSV.load("users", types={"age": int})
CSV.load_vectors("sensors", types={"temp": float}) # → {"temp": [...], "ts": [...]}
CSV.add_row("log", {"ts": 1234, "val": 3.14})      # append single row
```

## `INI`

Nested dict with sections.

```py
from xaeian import INI

INI.save("settings", {"main": {"key": "value", "num": 42}})
INI.load("settings") # → {"main": {"key": "value", "num": 42}}
```

## `YAML`

Auto `.yaml`/`.yml` extension. Multi-document support. Requires `pyyaml`.

```py
from xaeian import YAML

YAML.save("config", {"debug": True, "port": 8080})
YAML.load("config")                      # tries .yaml then .yml
YAML.save_pretty("config", cfg, sort_keys=True)
YAML.save_all("fixtures", [doc1, doc2])  # multi-doc with `---`
YAML.load_all("fixtures")                # → [doc1, doc2]
```

## `DIR`

Create, list, zip directories.

```py
from xaeian import DIR

DIR.ensure("data/subdir/")
DIR.file_list("src", exts=[".py"], blacklist=["__pycache__"])
DIR.zip("folder", "archive.zip")
```

## `PATH`

Pure path manipulation, no IO.

```py
from xaeian import PATH

PATH.stem("a/b/file.txt")         # → "file"
PATH.ext("a/b/file.txt")          # → ".txt"
PATH.with_suffix("f.txt", ".md")  # → "f.md"
PATH.resolve("data/cfg")          # → "/home/user/project/data/cfg"
```

## Context-based paths

Scope all operations to a root directory via `Files` instance or `file_context` manager.

```py
from xaeian import Files, file_context

fs = Files(root_path="/app/data")
fs.JSON.load("config")        # → /app/data/config.json
fs.FILE.save("log.txt", "ok") # → /app/data/log.txt

with file_context(root_path="/tmp"):
  FILE.save("temp.txt", "...") # → /tmp/temp.txt
```

## Async

Same API, awaitable.

```py
from xaeian.files_async import FILE, JSON, AsyncFiles

await FILE.load("data.txt")
await JSON.save("config", {"key": "value"})

fs = AsyncFiles(root_path="/app/data")
await fs.FILE.load("test.txt")
```