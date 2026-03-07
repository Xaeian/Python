# `xaeian.cli`

Command-line utility scripts. Run with `py -m xaeian.cli.<name>`.

## `tree` — Directory tree

```sh
py -m xaeian.cli.tree .
py -m xaeian.cli.tree src/ -e .py .c
py -m xaeian.cli.tree . -d 2 --size
py -m xaeian.cli.tree . --dirs
py -m xaeian.cli.tree . -o tree.json
```

## `dupes` — Duplicate file finder

```sh
py -m xaeian.cli.dupes photos/
py -m xaeian.cli.dupes docs/ --zips
py -m xaeian.cli.dupes . --min-size 1024
py -m xaeian.cli.dupes . --algo md5 -o report.json
```

## `wifi` — Saved Wi-Fi passwords

```sh
py -m xaeian.cli.wifi
py -m xaeian.cli.wifi -o wifi.json
```

Windows (`netsh`) and Linux (`nmcli` / NetworkManager files).