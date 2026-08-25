# xaeian/cli/__init__.py

"""
Command-line utility scripts, dispatched as `xn <command> [args]` (see `xaeian.__main__`).

Commands: `tree`, `dupes`, `wifi`, `fonts`, `host`, `min`, `meta`, `ico`.

Paths taken from the command line go through `PATH`, so `~` and `$VAR` resolve.
Plain `os.path` stays inside directory walks, where the paths are already absolute.
"""
