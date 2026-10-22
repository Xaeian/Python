# xaeian/cli/release.py

"""
`xn release` - a release lands on `main`, else `master`: tagged, signed and published.

From another branch it merges that branch in, a commit built from refs and signed,
and one atomic push moves the target and the tag together.
On `main` or `master` itself it tags what the branch holds on origin.
Version and text come from the first entry of `changes.md`, else `changelog.md`, unless given.
Every check runs before anything leaves this machine; the working tree is never touched.
Exit 0: released, 1: nothing changed, 2: pushed, but the GitHub Release is missing.
"""

import argparse, hashlib, json, re, sys, tomllib
from dataclasses import dataclass
from .. import __version__
from ..log import Print
from ..colors import Color as c
from . import _git
from .args import make_parser, add_help
from ._git import CommandError, TARGETS, git, gh, sha, tree, branch, config, fail

p = Print()

EXAMPLES = """
examples:
  xn release                   # version and text from changes.md
  xn release 1.2.0             # this version, text from changes.md
  xn release -n note.md        # version from changes.md, text from note.md
  xn release 1.2.0 -n note.md  # both given
  xn release --dry-run         # run the checks and print the record only
"""

CHANGES = ("changes.md", "changelog.md")
VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
ENTRY = re.compile(r"[`\[]?(v?\d+\.\d+\.\d+)[`\]]?\s*(.*)") # `## 1.2.0 Title` of a changes file

@dataclass
class Release:
  """What one run releases, settled before anything is written."""
  version: str       # `X.Y.Z`, without the `v` the tag may carry
  tag: str
  name: str          # `Xaeian` of `Xaeian 1.2.0`
  target: str        # `main` or `master`, where the release lands
  commit: str        # what the active branch holds on origin, the released tree
  base: str          # commit of the target to merge onto, "" when the branch is the target
  last: str          # tag of the release before, "" for the first
  text: str          # the note, else the changes entry, else ""
  checks: list[str]
  ci: str            # `green <run ids>` or `skipped`

#------------------------------------------------------------------------------------------- Inputs

def read_note(path:str) -> str:
  """Release text of `path` as written, line ends as LF, blank edges trimmed."""
  try:
    with open(path, encoding="utf-8") as f: return f.read().strip()
  except OSError as e:
    fail(f"Note {path} not readable | {e}")

def release_name(given:str|None) -> str:
  """`Xaeian` of the previous release `Xaeian 1.1.1`; `--name` gives it the first time."""
  if given: return given
  listed = json.loads(gh("release", "list", "--limit", "1", "--exclude-drafts", "--json", "name"))
  name = re.sub(r"\s*v?\d+\.\d+\.\d+\S*$", "", listed[0]["name"]).strip() if listed else ""
  if not name: fail("No earlier release to take the name from: pass --name")
  return name

#------------------------------------------------------------------------------------------- Checks

def pick_target() -> tuple[str, str]:
  """`main` on origin, else `master`, with the commit it holds."""
  for target in TARGETS:
    commit = sha(f"origin/{target}")
    if commit: return target, commit
  fail("Neither main nor master on origin")

def check_pure(base:str, commit:str, target:str) -> None:
  """
  The target holds nothing the branch lacks.

  The merge takes the tree of the branch whole:
  a change made on the target alone, such as a hotfix, would vanish without a word.
  """
  try:
    fork = git("merge-base", base, commit)
  except CommandError:
    fail(f"{target} and the branch share no history")
  if tree(fork) != tree(base):
    fail(f"{target} has changes the branch lacks: merge origin/{target} into it first")

def check_tag(version:str, commit:str) -> str:
  """
  Tag of the release before, "" for the first, once `commit` and `version` are both new.

  New means no release tag on `commit` yet, no tag of `version` with `v` or without,
  and `version` above every earlier one.
  """
  tags = {}
  for name in git("tag", "--list").splitlines():
    m = VERSION.fullmatch(name)
    if m: tags[tuple(int(n) for n in m.groups())] = name
  done = [t for t in git("tag", "--points-at", commit).splitlines() if VERSION.fullmatch(t)]
  if done: fail(f"Nothing to release: the commit is {done[0]} already")
  want = tuple(int(n) for n in version.split("."))
  if want in tags:
    old = tags[want]
    here = not git("ls-remote", "--tags", "origin", f"refs/tags/{old}")
    fail(f"Tag {old} exists" + (f" only here: git tag -d {old} drops it" if here else ""))
  if tags and want < max(tags): fail(f"{version} is below {tags[max(tags)]}")
  return tags[max(tags)] if tags else ""

def changes_file(commit:str) -> tuple[str, list[str]]|None:
  """Name and lines of `changes.md` on `commit`, else of `changelog.md`; `None` without either."""
  for name in CHANGES:
    try:
      return name, git("show", f"{commit}:{name}").splitlines()
    except CommandError:
      pass
  return None

def changelog(name:str, lines:list[str]) -> tuple[str, str, str]:
  """
  Version as written, title and list of the first entry of the changes file `name`.

  An entry opens with `## X.Y.Z Title`, backticks and `v` optional, and runs to the next `## `.
  """
  heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
  if not heads: fail(f"{name} has no entry")
  head = lines[heads[0]][3:].strip()
  m = ENTRY.match(head)
  if not m: fail(f"{name} opens with {head}, not a version")
  end = heads[1] if len(heads) > 1 else len(lines)
  items = "\n".join(lines[heads[0] + 1:end]).strip()
  if not items: fail(f"{name} entry {m.group(1)} lists nothing")
  return m.group(1), m.group(2).strip(), items

def code_version(commit:str) -> str|None:
  """`project.version` of `pyproject.toml` on the released commit, `None` without one."""
  try:
    text = git("show", f"{commit}:pyproject.toml")
  except CommandError:
    return None
  return tomllib.loads(text).get("project", {}).get("version")

def ci_runs(commit:str) -> str:
  """IDs of the CI runs on `commit`, each finished green; anything else exits."""
  runs = json.loads(gh("run", "list", "--commit", commit,
    "--json", "status,conclusion,databaseId"))
  if not runs: fail(f"No CI run on {commit[:12]}: wait for CI, or pass --no-ci")
  if any(run["status"] != "completed" for run in runs): fail("CI still running on the commit")
  red = [run for run in runs if run["conclusion"] != "success"]
  if red: fail(f"CI failed on the commit, run {red[0]['databaseId']}")
  return ",".join(str(run["databaseId"]) for run in runs)

def prepare(args:argparse.Namespace) -> Release:
  """Every check in order; the first refusal exits with nothing changed."""
  if not config("user.signingkey"): fail("Signing not set up: no user.signingkey")
  try:
    gh("auth", "status")
  except CommandError as e:
    fail(f"GitHub CLI not ready: install gh, then gh auth login | {e}")
  name = release_name(args.name)
  source = branch() or fail("Detached HEAD: switch to the branch to release")
  git("fetch", "--prune", "origin", "--tags") # a branch gone from origin is gone here too
  commit = sha(f"origin/{source}") or fail(f"{source} is not on origin: push it first")
  if sha("HEAD") != commit: fail(f"Local {source} differs from origin: push or pull it first")
  if git("status", "--porcelain"): p.inf("Uncommitted changes stay out of the release")
  target, base = (source, "") if source in TARGETS else pick_target()
  if base:
    check_pure(base, commit, target)
    if tree(commit) == tree(base): fail(f"Nothing to release: {source} matches {target}")
  file, lines = changes_file(commit) or ("", [])
  written, title, items = changelog(file, lines) if file else ("", "", "")
  tag = args.version or written
  if not tag: fail("No changes.md or changelog.md on the commit: pass the version")
  m = VERSION.fullmatch(tag)
  if not m: fail(f"Version {tag} is not X.Y.Z")
  version = ".".join(m.groups())
  if written and written.removeprefix("v") != version:
    fail(f"{file} opens with {written}, not {version}")
  last = check_tag(version, commit)
  declared = code_version(commit)
  if declared and declared.removeprefix("v") != version:
    fail(f"pyproject.toml says {declared}, not {version}")
  if args.note: text = read_note(args.note)
  elif file: text = f"**{title}**\n{items}" if title else items
  else: text = ""
  merged = ["target-pure", "ahead"] if base else []
  checks = [*merged, "unreleased", "version",
    "changelog" if file else "changelog:none",
    "code-version" if declared else "code-version:none",
    "ci:skipped" if args.no_ci else "ci"]
  ci = "skipped" if args.no_ci else f"green {ci_runs(commit)}"
  # last, once nothing can refuse: a warning ahead of a refusal is only noise
  if not args.note and not file: p.wrn("No release text: no note, no changes.md, no changelog.md")
  return Release(version=version, tag=tag, name=name, target=target, commit=commit, base=base,
    last=last, text=text, checks=checks, ci=ci)

#------------------------------------------------------------------------------------------- Record

def code_hash(*paths:str) -> str:
  """First 12 hex of sha256 over `paths`, line ends read as LF: a checkout and a wheel agree."""
  digest = hashlib.sha256()
  for path in paths:
    with open(path, "rb") as f: digest.update(f.read().replace(b"\r\n", b"\n"))
  return digest.hexdigest()[:12]

def tool() -> str:
  """`Release-Tool`: xaeian version, `release@` hash of the code that releases, git and gh."""
  git_version = git("--version").split()[2]
  gh_version = gh("--version").split()[2]
  return (f"xaeian {__version__} release@{code_hash(__file__, _git.__file__)} "
    f"git {git_version} gh {gh_version}")

def record(rel:Release) -> str:
  """Message of the tag and the merge: release text, commits since the last release, trailers."""
  span = f"{rel.last}..{rel.commit}" if rel.last else rel.commit
  commits = git("log", "--no-merges", "--format=%H %s", span)
  trailers = (
    f"Release-Version: {rel.version}\n"
    f"Release-Checks: {', '.join(rel.checks)}\n"
    f"Release-CI: {rel.ci}\n"
    f"Release-Tool: {tool()}\n"
    f"Approved-by: {config('user.name')} <{config('user.email')}>\n"
  )
  text = f"{rel.text}\n\n" if rel.text else ""
  return f"{rel.name} {rel.version}\n\n{text}Commits:\n{commits}\n\n{trailers}"

#------------------------------------------------------------------------------------------ Publish

def merge(rel:Release, data:bytes) -> str:
  """Merge commit of the branch onto the target, built from refs, signed and self-checked."""
  new = git("commit-tree", "-p", rel.base, "-p", rel.commit, "-S", "-F", "-",
    f"{rel.commit}^{{tree}}", data=data)
  parents = git("rev-list", "--parents", "-n", "1", new).split()[1:]
  signed = "\ngpgsig " in git("cat-file", "commit", new)
  if parents != [rel.base, rel.commit] or tree(new) != tree(rel.commit) or not signed:
    fail("Merge commit failed its own check, nothing pushed")
  return new

def publish(rel:Release, message:str) -> None:
  """Merge commit when there is a branch to merge, signed tag, one atomic push, GitHub Release."""
  data = message.encode("utf-8")
  head = merge(rel, data) if rel.base else rel.commit
  # `strip`, the default, would cut every line opening with `#`, a `#12` of a note among them
  git("tag", "-s", "--cleanup=whitespace", "-F", "-", rel.tag, head, data=data)
  moved = [f"{head}:refs/heads/{rel.target}"] if rel.base else []
  try:
    git("push", "--atomic", "origin", *moved, f"refs/tags/{rel.tag}")
  except CommandError as e:
    git("tag", "-d", rel.tag)
    fail(f"Push refused, origin untouched | {e}")
  p.ok(f"{c.SKY}{rel.target}{c.END} at {c.GOLD}{head[:12]}{c.END}, tag {c.GOLD}{rel.tag}{c.END}")
  if rel.base and sha(f"refs/heads/{rel.target}"):
    try:
      git("fetch", ".", f"refs/remotes/origin/{rel.target}:refs/heads/{rel.target}")
    except CommandError:
      p.inf(f"Local {rel.target} left as it is: checked out, or not a fast-forward")
  title = f"{rel.name} {rel.version}"
  try:
    gh("release", "create", rel.tag, "--verify-tag", "--title", title, "--notes-file", "-",
      data=rel.text.encode("utf-8"))
  except CommandError as e:
    path = git("rev-parse", "--git-path", "xn-release.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f: f.write(rel.text)
    p.err(f"{title} is on origin, its GitHub Release is not | {e}")
    p.tip(f'Finish with: gh release create {rel.tag} --verify-tag --title "{title}" '
      f"--notes-file {path}")
    sys.exit(2)
  p.ok(f"Released {c.GOLD}{title}{c.END}")

#--------------------------------------------------------------------------------------------- Main

def main() -> None:
  parser = make_parser("Merge the active branch into main, or tag main itself, and publish it",
    EXAMPLES)
  parser.add_argument("version", nargs="?", default=None,
    help="X.Y.Z, else the first entry of changes.md; a leading v stays in the tag")
  parser.add_argument("-n", "--note", default=None, metavar="PATH",
    help="Release text, else the changes.md entry")
  parser.add_argument("--name", default=None,
    help="Release name, needed only when the repo has no release yet")
  parser.add_argument("--dry-run", action="store_true",
    help="Run every check and print the record, change nothing")
  parser.add_argument("--no-ci", action="store_true", help="Skip the CI check, recorded as such")
  add_help(parser)
  args = parser.parse_args()
  try:
    rel = prepare(args)
    message = record(rel)
    if args.dry_run:
      p.ok(f"Checks passed: {', '.join(rel.checks)}")
      p.inf(f"Record of {c.GOLD}{rel.name} {rel.version}{c.END}, nothing changed:")
      print(message)
      return
    publish(rel, message)
  except CommandError as e:
    fail(str(e))

if __name__ == "__main__":
  main()
