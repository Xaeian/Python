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

## `commit`: Signed commit and push

```sh
xn commit -m "fix: Timeout"
```

Adds everything changed on the active branch, commits it and pushes it to the branch it tracks.
A branch tracking no remote one keeps the commit here.
The commit is signed when git signs commits anyway (`commit.gpgsign`).
With nothing changed, commits waiting on a tracking branch go out.

Refused before anything is staged:

- a secret by its name: `.env*` but `.env.example`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`
- a file over 5MB
- a merge, rebase, cherry-pick or revert in progress, or an unmerged path

## `release`: Merge, tag and publish

```sh
xn release 1.2.0 -n note.md
xn release 1.2.0 -n note.md --dry-run
```

On `develop`, or any branch besides `main` and `master`, merges it into `main`, else `master`.
The merge is a signed commit built from refs, and one atomic push moves `main` and the tag.
On `main` or `master` itself, tags what the branch holds on origin, with no merge.
Then `gh` publishes the GitHub Release. The working tree is never touched.

Checked before anything leaves the machine:

- the local branch matches origin, and its commit is not released yet
- when merging, `main` holds nothing the branch lacks: after a hotfix, merge `origin/main` into the branch first
- the first entry of `changes.md` is the version, with `v` or without
- `pyproject.toml`, when there is one, says the same version
- no tag of the version exists, and the version is above every earlier tag
- CI finished green on the released commit, unless `--no-ci`, which the record keeps

The release is named after the previous one: `Xaeian 1.1.1` → `Xaeian 1.2.0`.
`--name` gives the name the first time.
Its text is the title and list of the `changes.md` entry, followed by the note:

```md
Refs: #12, #15
Verification:
- bench BT-04 PASS
Known issues: none
```

The signed tag carries the record, and so does the merge commit when there is one.
The record holds the text, the commits since the release before, and trailers.
The trailers name the checks, the CI runs, the tool with a hash of its own code, and the approver.

> [!NOTE]
> Exit `2` means the release is on origin but the GitHub Release failed.
> The notes wait in `.git/xn-release.md`, with the command to finish printed.

Requires `gh`, logged in.