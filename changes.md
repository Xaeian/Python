# Changes `xaeian`

## `0.9.2` S3

- `net`: `S3` joins `FTP` and `SFTP`, stdlib only: SigV4 by hand, sync exact on the ETag
- `net`: one `filter` prunes one tree, on every client and on both sides of a sync

## `0.9.1` Boot

- `serial`: `Shell.boot` installs a `.bin` or `.hex` image, `Shell.boot_info` reads the slot
- `net`: FTP and SFTP fail alike: missing is `FileNotFoundError`, refused is `PermissionError`
- `cli`: `xn host <ip>` shows an entry, `--drop` removes it

## `0.9.0` Correctness & layers

Breaking: `?` in raw SQL, `shape=` in `DIR` listings, `FILE.exists`/`DIR.exists`, one dict per file from `compress`,
short names on `Print`, `Time` vs `Time`/`datetime`, no walk into a link, optional exports on first use.

- Silent data faults fixed across `db`, `media`, `files`, `cstruct` and `eda`
- One seam for sync and async in `db`, `files` and `net`
- `import xaeian` 1.5s → 120ms, tests 465 → 685

## `0.8.2` CLI host keys

- `cli`: `xn host` lists pinned hosts, `xn host <ip>` drops one after a server rebuild

## `0.8.1` SFTP host keys

- `net`: `SFTP` pins first-contact host keys, so a changed server key aborts

## `0.8.0` Safety audit

Breaking: `FILE.save`/`append` preserve line endings, `split_sql` drops comments,
and `pdf_compress` verifies its output.

- Safer atomic writes, paths, database transactions, file transfers, and media replacement
- Correctness and performance fixes across serial, EDA, strings, time, and checksums

## `0.7.5` FTP & SFTP, SQLite fix

- `db`: async `get_rows`/`get_dicts` commit `RETURNING` writes _(left the WAL lock held, or silently rolled back)_
- `net`: hardened `FTP` and `SFTP`, fixed data loss in `sync_pull(delete=True)`
- `eda`: footprint generator updates
- Added `net` and async SQLite test suites

## `0.7.4` Refactor

- `files`: `INI` accepts `.conf`/`.cfg`, `YAML.save` keeps `.yml`
- Fixed extras: `[serial]`, `[sftp]`, `[yaml]` install their deps again
- Bug fixes across `cstruct`, `db`, `table`, `log`, `xtime`, `media`, `serial`
- Full style pass, dead code removed

## `0.7.3` SFTP, tests

- `net`: `SFTP.exec` `check` flag, `filter` prunes remote dirs
- Added test suite

## `0.7.2` Fixes

- Bug fixes across `files_async`, `xstring`, `xtime`, `cstruct`, `eda`, `dsp`, `net`
- Internal refactor, **no public API changes**

## `0.7.1` Fix

- `serial`: `mbb_load` fix, recorders own their threads
- `eda`: BOM/CPL refinements, 3D render colors

## `0.7.0` Serial submodule

- `serial`: new submodule, replaces `serial_port` and `cbash` _(breaking)_
- `Recorder`, `RecorderPool`: threaded value capture with CSV
- `Shell`: renamed from `CBash`

## `0.6.2` Recorder

- `serial_port`: Recorder bug fix
- `eda`: Minor fixes

## `0.6.1` Remove PDF module

- Extract PDF generation into a separate package
- Minor fixes in `cli/fonts` and `KeyValue` in `db`

## `0.6.0` KiCad, Database key-value & Fixes

- `eda`: Submodules for KiCad footprint and symbol generation and cleanup
- `db`: Key-value store for database backends _(`KeyValue`, `AsyncKeyValue`)_
- `db`: Adding **pool** to asynchronous database SQL controller versions
- `cli/fonts`: Script for converting fonts for web use
- `files`: Added `DIR.unzip` as counterpart to `DIR.zip`
- Bug fixes, immutability hardening, and dependency declarations across existing modules

## `0.5.3` YAML

- `files`: split into subpackage, added YAML namespace
- `log`: `Print.level` property with string setter _(`"DBG"`, `"WRN"`, ...)_

## `0.5.2` Refactor

- `files.py`: many bugs, full refactor

## `0.5.1` FTP

- `net`: FTP client + `Remote()` factory unifying SFTP and FTP
- `net/sftp`: fixed remote paths on Windows

## `0.5.0` SFTP, CLI & scripts

- `sftp`: SFTP/SSH client, push/pull sync, remote exec
- `cli`: `xn` entry point with dispatcher _(`wifi`, `meta`, ...)_
- `toml.py`: `[project.scripts]` from `__scripts__`
- `log`: `Print` and `Logger` compatible as `log=` argument

## `0.4.1` Fix

- `eda`: added `__extras__`, exposed `Simulation`/`parse_output`

## `0.4.0` Plot, DSP & Spice

- `plot`: fluent matplotlib wrapper, stacked panels, twinx, auto datetime
- `dsp`: immutable Signal with SOS filters, FFT, vibration metrics, operators
- `eda/spice`: ngspice runner with template substitution, caching, parallel sweep
- `table`: `markdown()`, `markdown_raw()`

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
