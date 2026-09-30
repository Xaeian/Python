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

## `fonts`: Font file renamer

```sh
xn fonts web/fonts/
xn fonts web/fonts/ --css web/css/fonts.css
xn fonts web/fonts/ --dry-run
```

Rename font files to `{family}-{weight}[-italic].{ext}` convention.
Optionally generates `@font-face` CSS.

## `plot`: CSV waveform

```sh
xn plot log.csv
xn plot log.csv -c vin_V,vout_V
xn plot sweep.csv -x vin_V
xn plot log.csv -o log.png
xn plot log.csv --dark
```

The first column is x: numbers, or ISO time as `CSV.add_row` writes it.
A header carries its unit, `vout_V` or `Vout [V]`, and columns sharing a unit share a panel.
Empty or garbled cells become gaps. A `;` file may use a decimal comma.
Requires `pip install xaeian[plot]`.