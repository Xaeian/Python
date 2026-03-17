# `xaeian.cli`

Command-line utility scripts. Run with `xn <name>`.

## `tree`: Directory tree

```sh
xn tree .
xn tree src/ -e .py .c
xn tree . -d 2 --size
xn tree . --dirs
xn tree . -o tree.json
```

## `dupes`: Duplicate file finder

```sh
xn dupes photos/
xn dupes docs/ --zips
xn dupes . --min-size 1024
xn dupes . --algo md5 -o report.json
```

## `wifi`: Saved Wi-Fi passwords

```sh
xn wifi
xn wifi -o wifi.json
```

Windows (`netsh`) and Linux (`nmcli` / NetworkManager files).