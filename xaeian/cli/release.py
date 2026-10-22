# xaeian/cli/release.py

"""
`xn release` - a release lands on `main`, else `master`: tagged, signed and published.

From another branch it merges that branch in, a commit built from refs and signed,
and one atomic push moves the target and the tag together.
On `main` or `master` itself it tags what the branch holds on origin.
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
  xn release 1.2.0 -n note.md            # merge into main and publish; on main, tag it alone
  xn release 1.2.0 -n note.md --dry-run  # run the checks and print the record only
"""

SECTIONS = ("Refs", "Verification", "Known issues")
VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
ENTRY = re.compile(r"[`\[]?(v?\d+\.\d+\.\d+)[`\]]?\s*(.*)") # `## 1.2.0 Title` of `changes.md`
NOTE_KEY = re.compile(r"(Changes|Refs|Verification|Known issues):(.*)")

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
  title: str         # of the `changes.md` entry, "" without one
  changes: str       # list of the entry, as written
  note: str
  checks: list[str]
  ci: str            # `green <run ids>` or `skipped`

#------------------------------------------------------------------------------------------- Inputs

def read_note(path:str) -> str:
  """
  Release note, checked: `Refs`, `Verification` and `Known issues`, each once and filled in.

  A section opens with `Key:` and holds the rest of that line and the lines below it.
  `Changes` come from `changes.md`, so a note carrying them is refused.
  """
  try:
    with open(path, encoding="utf-8") as f: text = f.read().strip()
  except OSError as e:
    fail(f"Note {path} not readable | {e}")
  found: dict[str, str] = {}
  key = None
  for line in text.split("\n"):
    m = NOTE_KEY.match(line)
    if m:
      key = m.group(1)
      if key in found: fail(f"Note {path} has {key} twice")
      found[key] = m.group(2)
    elif key: found[key] += "\n" + line
    elif line.strip(): fail(f"Note {path} has text before its first section")
  if "Changes" in found: fail(f"Note {path} has Changes, they come from changes.md")
  for key in SECTIONS:
    if not found.get(key, "").strip(): fail(f"Note {path} misses {key}, or it is empty")
  return text

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

def code_version(commit:str) -> str|None:
  """`project.version` of `pyproject.toml` on the released commit, `None` without one."""
  try:
    text = git("show", f"{commit}:pyproject.toml")
  except CommandError:
    return None
  return tomllib.loads(text).get("project", {}).get("version")

def changelog(commit:str, version:str) -> tuple[str, str]:
  """
  Title and list of the `version` entry of `changes.md`, which has to come first.

  An entry opens with `## X.Y.Z Title`, backticks and `v` optional, and runs to the next `## `.
  """
  try:
    lines = git("show", f"{commit}:changes.md").splitlines()
  except CommandError:
    fail("No changes.md on the released commit")
  heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
  if not heads: fail("changes.md has no entry")
  head = lines[heads[0]][3:]
  m = ENTRY.match(head)
  if not m or m.group(1).removeprefix("v") != version:
    fail(f"changes.md opens with {head.strip()}, not {version}")
  end = heads[1] if len(heads) > 1 else len(lines)
  body = "\n".join(lines[heads[0] + 1:end]).strip()
  if not body: fail(f"changes.md entry {version} lists nothing")
  return m.group(2).strip(), body

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
  m = VERSION.fullmatch(args.version)
  if not m: fail(f"Version {args.version} is not X.Y.Z")
  version = ".".join(m.groups())
  note = read_note(args.note)
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
  last = check_tag(version, commit)
  declared = code_version(commit)
  if declared and declared.removeprefix("v") != version:
    fail(f"pyproject.toml says {declared}, not {version}")
  title, changes = changelog(commit, version)
  merged = ["target-pure", "ahead"] if base else []
  checks = ["note", *merged, "unreleased", "version", "changelog",
    "code-version" if declared else "code-version:none",
    "ci:skipped" if args.no_ci else "ci"]
  ci = "skipped" if args.no_ci else f"green {ci_runs(commit)}"
  return Release(version=version, tag=args.version, name=name, target=target, commit=commit,
    base=base, last=last, title=title, changes=changes, note=note, checks=checks, ci=ci)

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

def body(rel:Release) -> str:
  """GitHub Release text: bold title of the `changes.md` entry, its list, then the note."""
  head = f"**{rel.title}**\n" if rel.title else ""
  return f"{head}{rel.changes}\n\n{rel.note}\n"

def record(rel:Release) -> str:
  """Message of the tag and the merge: name, release text, commits since the last, trailers."""
  span = f"{rel.last}..{rel.commit}" if rel.last else rel.commit
  commits = git("log", "--no-merges", "--format=%H %s", span)
  trailers = (
    f"Release-Version: {rel.version}\n"
    f"Release-Checks: {', '.join(rel.checks)}\n"
    f"Release-CI: {rel.ci}\n"
    f"Release-Tool: {tool()}\n"
    f"Approved-by: {config('user.name')} <{config('user.email')}>\n"
  )
  return f"{rel.name} {rel.version}\n\n{body(rel)}\nCommits:\n{commits}\n\n{trailers}"

#------------------------------------------------------------------------------------------ Publish

def merge(rel:Release, data:bytes) -> str:
  """Merge commit of the branch onto the target, built from refs and signed, once it checks out."""
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
  # `strip`, the default, would cut every line opening with `#`, a `#12` of `Refs` among them
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
  title, notes = f"{rel.name} {rel.version}", body(rel)
  try:
    gh("release", "create", rel.tag, "--verify-tag", "--title", title, "--notes-file", "-",
      data=notes.encode("utf-8"))
  except CommandError as e:
    path = git("rev-parse", "--git-path", "xn-release.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f: f.write(notes)
    p.err(f"{title} is on origin, its GitHub Release is not | {e}")
    p.tip(f'Finish with: gh release create {rel.tag} --verify-tag --title "{title}" '
      f"--notes-file {path}")
    sys.exit(2)
  p.ok(f"Released {c.GOLD}{title}{c.END}")

#--------------------------------------------------------------------------------------------- Main

def main() -> None:
  parser = make_parser("Merge the active branch into main, or tag main itself, and publish it",
    EXAMPLES)
  parser.add_argument("version", help="X.Y.Z; a leading v stays in the tag")
  parser.add_argument("-n", "--note", required=True, metavar="PATH",
    help="Note with Refs, Verification and Known issues")
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
