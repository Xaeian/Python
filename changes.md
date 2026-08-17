# Changes `xaeian`

## `0.8.0` Safety audit

Breaking: `FILE.save`/`append` write line ends verbatim, `split_sql` drops comments and keeps
`"identifiers"` whole, `pdf_compress` refuses a PDF it cannot verify _(new `verify=`)_.

- `files`: writes are atomic - savers serialize first, `FILE.save` swaps in a temp file, so a
  failed or interrupted write leaves the previous file intact
- `files`: `PATH.normalize` keeps the UNC `//` root _(shares silently landed on the local drive)_,
  `PATH.real`/`is_under(real=)` resolve symlinks, `FILE.save(chmod=)` for secrets
- `db`: reads commit when they own the connection _(`INSERT ... RETURNING` rolled the row away)_,
  SQLite rolls back DDL, `transaction()` cannot wedge, `KeyValue.updated_at` fits epoch ms
- `net`: `FTP.get` downloads to a temp file, `sync_push(delete=True)` refuses a missing local
  source instead of clearing the remote
- `media`: `img_compress` raises when two sources map to one output, `pdf_compress` verifies the
  page count before replacing anything
- `serial`: `Recorder` no longer fuses adjacent readings, `SerialPort` CRC covers the address byte
- `eda`: `clean_step` writes a valid STEP `FILE_NAME` for zoned timestamps and digit-leading names
- `xstring`: `scan()` tokenizer under `split_str`/`strip_comments`/`split_sql`; `generate_token`
- `xtime`: compound intervals (`"1d 2h30m"`) apply fully; `crc`: `checksum` linear on long input

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
