## Changelog `xaeian`

## `0.3.0` Electronics & fixes

- `elc`: E-series, VConv divider finder, KiCad production export
- `mf/ico.py`: multi-size `.ico` generator
- Fixes: `crc` pretabulated reflectIn, `table.aggregate` type guard, `img_compress` inplace ext change

## `0.2.0` New features

- `files.py`: extended `PATH`, `DIR`, `FILE` & new `CSV.load_vectors(group_by=)`
- `files.py`: `Files(root_path=...)` object, removed `set_context()`
- `mf`: basic **pdf** & **img** operations (media files)
- `pdf`: PDF document generation
- `cli`: utility scripts (dupes, tree, wifi)
- `cbash.py`: `ping(retries=3)` with automatic retry

## `0.1.0` Initial release

- `files`, `files_async`: file operations with context paths
- `xstring`: string utilities, password generation
- `xtime`: datetime parsing and arithmetic
- `colors`, `log`: colored terminal output and logging
- `crc`: CRC-8/16/32
- `cstruct`: binary struct serialization
- `serial_port`, `cbash`: serial communication
- `db`: database abstraction _(SQLite, MySQL, PostgreSQL)_
