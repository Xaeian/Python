# xaeian/cli/release.py

"""
`xn release` - a release lands on `main`, else `master`: tagged and published.

From another branch it merges that branch in, a commit built from refs,
and one atomic push moves target and tag together.
On `main` or `master` itself it tags what it holds on origin.
Tag and merge are signed when `user.signingkey` is set, otherwise unsigned.
Version and text come from the first entry of `changes.md`, else `changelog.md`, unless given.
Every check runs before anything leaves this machine; the working tree is never touched.
Exit 0: released, 1: nothing changed, 2: pushed, GitHub Release missing.
"""

import argparse, hashlib, json, re, sys, tomllib
from dataclasses import dataclass
from .. import __version__
from ..log import Print
from ..colors import fmt_cmd
from . import _git
from .args import make_parser, add_help
from ._git import CommandError, git, gh, sha, tree, branch, config, fail, github
from ._git import fmt_branch, fmt_release, fmt_sha, fmt_file

p = Print()

EXAMPLES = """
examples:
  xn release                   # version and text from changes.md
  xn release 1.2.0             # this version, text from changes.md
  xn release -n note.md        # version from changes.md, text from note.md
  xn release 1.2.0 -n note.md  # both given
  xn release --dry-run         # run checks, print record only
"""

TARGETS = ("main", "master") # releases land there, `main` first
CHANGES = ("changes.md", "changelog.md")

VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
HEADING = re.compile(r"(#{2,}) +(.*)")
ENTRY = re.compile(r"[`\[]?(v?\d+\.\d+\.\d+)[`\]]?\s*(.*)") # `1.2.0 Title` of a heading

@dataclass
class Release:
  """What one run releases, settled before anything is written."""
  version: str       # `X.Y.Z`, without `v` the tag may carry
  tag: str
  name: str          # `Xaeian` of `Xaeian 1.2.0`
  target: str        # `main` or `master`, where it lands
  commit: str        # what the active branch holds on origin: the released tree
  base: str          # commit of target to merge onto, "" when branch is target
  last: str          # commit of previous release, "" for first
  text: str          # note, else changes entry, else ""
  signed: bool       # `user.signingkey` is set
  checks: list[str]
  ci: str            # `green <run ids>` or `skipped`

  @property
  def title(self) -> str:
    """`Xaeian 1.2.0`: the name of the GitHub Release and the first line of the record."""
    return f"{self.name} {self.version}"

#------------------------------------------------------------------------------------------- Inputs

def read_note(path:str) -> str:
  """Release text of `path` as written, line ends as LF, blank edges trimmed."""
  try:
    with open(path, encoding="utf-8") as f: return f.read().strip()
  except OSError as e:
    fail(f"Cannot read note {fmt_file(path)} | {e}")

def release_name(given:str|None) -> str:
  """`Xaeian` of previous release `Xaeian 1.1.1`; `--name` gives it the first time."""
  if given: return given
  listed = json.loads(gh("release", "list", "--limit", "1", "--exclude-drafts", "--json", "name"))
  name = re.sub(r"\s*v?\d+\.\d+\.\d+\S*$", "", listed[0]["name"]).strip() if listed else ""
  if not name: fail(f"Release name unknown, no previous release: pass {fmt_cmd('--name')}")
  return name

#------------------------------------------------------------------------------------------- Checks

def pick_target() -> tuple[str, str]:
  """`main` on origin, else `master`, with the commit it holds."""
  for target in TARGETS:
    commit = sha(f"origin/{target}")
    if commit: return target, commit
  fail(f"No {fmt_branch('main')} or {fmt_branch('master')} branch on origin")

def check_pure(base:str, commit:str, source:str, target:str) -> None:
  """
  `target` holds nothing `source` lacks.

  A merge takes the tree of `source` whole:
  a change made on `target` alone, such as a hotfix, would vanish without a word.
  """
  try:
    fork = git("merge-base", base, commit)
  except CommandError:
    fail(f"{fmt_branch(target)} and {fmt_branch(source)} share no history")
  if tree(fork) != tree(base):
    merge = fmt_cmd(f"git merge origin/{target}")
    fail(f"{fmt_branch(target)} has changes {fmt_branch(source)} lacks: merge with {merge}")

def check_tag(tag:str, version:str, commit:str) -> str:
  """
  Commit of previous release, "" for first, once `commit` and `version` are both new.

  Tags are read from origin, the record of what is released: a local one may lag or differ.
  New means no release tag on `commit` yet, no tag of `version` with `v` or without,
  `version` above every earlier one, and no local `tag` in the way.
  """
  tags = {} # version, its tag and commit under it, an annotated tag peeled by `^{}`
  for line in git("ls-remote", "--tags", "origin").splitlines():
    at, ref = line.split("\t")
    name = ref.removeprefix("refs/tags/").removesuffix("^{}")
    m = VERSION.fullmatch(name)
    if m: tags[tuple(int(n) for n in m.groups())] = (name, at)
  done = [name for name, at in tags.values() if at == commit]
  if done:
    fail(f"Nothing to release: {fmt_sha(commit)} already released as {fmt_release(done[0])}")
  want = tuple(int(n) for n in version.split("."))
  if want in tags: fail(f"Tag {fmt_release(tags[want][0])} already exists on origin")
  if tags and want < max(tags):
    last = fmt_release(tags[max(tags)][0])
    fail(f"Version {fmt_release(version)} lower than last release {last}")
  if sha(f"refs/tags/{tag}"):
    drop = fmt_cmd(f"git tag -d {tag}")
    fail(f"Tag {fmt_release(tag)} exists locally but not on origin: remove it with {drop}")
  return tags[max(tags)][1] if tags else ""

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
  Version as written, title and list of the first entry in changes file `name`.

  An entry opens with a heading from `##` down, `## X.Y.Z Title` or `### X.Y.Z Title`,
  backticks and `v` optional, and runs to the next heading of its level or above.
  """
  heads = [] # line, level and text of each heading
  for i, line in enumerate(lines):
    m = HEADING.fullmatch(line)
    if m: heads.append((i, len(m.group(1)), m.group(2).strip()))
  if not heads: fail(f"{fmt_file(name)} has no version entry")
  start, level, head = heads[0]
  m = ENTRY.match(head)
  if not m: fail(f'{fmt_file(name)} starts with "{head}", not a version')
  end = next((i for i, depth, _ in heads[1:] if depth <= level), len(lines))
  items = "\n".join(lines[start + 1:end]).strip()
  if not items: fail(f"{fmt_file(name)} entry {fmt_release(m.group(1))} is empty")
  return m.group(1), m.group(2).strip(), items

def code_version(commit:str) -> str|None:
  """`project.version` of `pyproject.toml` on released commit, `None` without one."""
  try:
    text = git("show", f"{commit}:pyproject.toml")
  except CommandError:
    return None
  return tomllib.loads(text).get("project", {}).get("version")

def ci_runs(commit:str) -> str:
  """IDs of CI test runs on `commit`, all passed; anything else exits."""
  runs = json.loads(gh("run", "list", "--commit", commit,
    "--json", "status,conclusion,databaseId,url"))
  at = fmt_sha(commit)
  if not runs: fail(f"No CI tests on commit {at} yet: wait for them, or pass {fmt_cmd('--no-ci')}")
  if any(run["status"] != "completed" for run in runs):
    fail(f"CI tests still running on commit {at}: release again once they pass")
  red = [run for run in runs if run["conclusion"] != "success"]
  if red: fail(f"CI tests failed on commit {at}: {red[0]['url']}")
  return ",".join(str(run["databaseId"]) for run in runs)

def prepare(args:argparse.Namespace) -> Release:
  """Every check in order; the first refusal exits with nothing changed."""
  github()
  name = release_name(args.name)
  source = branch() or fail("Detached HEAD: switch to a branch to release")
  # `--prune`: a branch gone from origin is gone here too
  # `--no-tags`: tags are read from origin as they are, so a local one that differs blocks nothing
  try:
    git("fetch", "--prune", "--no-tags", "origin")
  except CommandError as e:
    fail(f"Fetch from origin failed | {e}")
  commit = sha(f"origin/{source}") or fail(f"{fmt_branch(source)} is not on origin: push it first")
  if sha("HEAD") != commit:
    fail(f"Local {fmt_branch(source)} differs from origin: push or pull it first")
  if git("status", "--porcelain"): p.inf("Uncommitted changes left out of release")
  target, base = (source, "") if source in TARGETS else pick_target()
  if base:
    check_pure(base, commit, source, target)
    if tree(commit) == tree(base):
      fail(f"Nothing to release: {fmt_branch(source)} has nothing new for {fmt_branch(target)}")
  file, lines = changes_file(commit) or ("", [])
  written, title, items = changelog(file, lines) if file else ("", "", "")
  files = " or ".join(map(fmt_file, CHANGES))
  tag = args.version or written
  if not tag: fail(f"No {files} on commit: pass version")
  m = VERSION.fullmatch(tag)
  if not m: fail(f"Version {fmt_release(tag)} is not X.Y.Z")
  version = ".".join(m.groups())
  if written and written.removeprefix("v") != version:
    fail(f"{fmt_file(file)} starts with {fmt_release(written)}, not {fmt_release(version)}")
  last = check_tag(tag, version, commit)
  declared = code_version(commit)
  if declared and declared.removeprefix("v") != version:
    fail(f"{fmt_file('pyproject.toml')} says {fmt_release(declared)}, not {fmt_release(version)}")
  if args.note: text = read_note(args.note)
  elif file: text = f"**{title}**\n{items}" if title else items
  else: text = ""
  merged = ["target-pure", "ahead"] if base else []
  checks = [*merged, "unreleased", "version",
    "changelog" if file else "changelog:none",
    "code-version" if declared else "code-version:none",
    "ci:skipped" if args.no_ci else "ci"]
  ci = "skipped" if args.no_ci else f"green {ci_runs(commit)}"
  signed = bool(config("user.signingkey"))
  # last, once nothing can refuse: a warning ahead of a refusal is only noise
  if not args.note and not file: p.wrn(f"Release without text: no note, {files}")
  if not signed: p.inf("Release without signature: no user.signingkey in git config")
  return Release(version=version, tag=tag, name=name, target=target, commit=commit, base=base,
    last=last, text=text, signed=signed, checks=checks, ci=ci)

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
  """Message of tag and merge: release text, commits since last release, trailers."""
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
  return f"{rel.title}\n\n{text}Commits:\n{commits}\n\n{trailers}"

#------------------------------------------------------------------------------------------ Publish

def merge(rel:Release, data:bytes) -> str:
  """Merge commit of branch onto target, built from refs and self-checked."""
  sign = ["-S"] if rel.signed else []
  new = git("commit-tree", "-p", rel.base, "-p", rel.commit, *sign, "-F", "-",
    f"{rel.commit}^{{tree}}", data=data)
  parents = git("rev-list", "--parents", "-n", "1", new).split()[1:]
  unsigned = rel.signed and "\ngpgsig " not in git("cat-file", "commit", new)
  if parents != [rel.base, rel.commit] or tree(new) != tree(rel.commit) or unsigned:
    fail("Merge commit failed its self-check, nothing pushed")
  return new

def publish(rel:Release, message:str) -> None:
  """Merge commit when there is a branch to merge, tag, one atomic push, GitHub Release."""
  data = message.encode("utf-8")
  head = merge(rel, data) if rel.base else rel.commit
  # `strip`, the default, would cut every line opening with `#`, a `#12` of a note among them
  git("tag", "-s" if rel.signed else "-a", "--cleanup=whitespace", "-F", "-", rel.tag, head,
    data=data)
  moved = [f"{head}:refs/heads/{rel.target}"] if rel.base else []
  try:
    git("push", "--atomic", "origin", *moved, f"refs/tags/{rel.tag}")
  except CommandError as e:
    git("tag", "-d", rel.tag)
    fail(f"Push rejected, origin unchanged | {e}")
  p.ok(f"Tag {fmt_release(rel.tag)} on {fmt_branch(rel.target)} at {fmt_sha(head)}")
  if rel.base and sha(f"refs/heads/{rel.target}"):
    try:
      git("fetch", ".", f"refs/remotes/origin/{rel.target}:refs/heads/{rel.target}")
    except CommandError:
      p.inf(f"Local {fmt_branch(rel.target)} not updated: run {fmt_cmd('git pull')} on it")
  try:
    url = gh("release", "create", rel.tag, "--verify-tag", "--title", rel.title,
      "--notes-file", "-", data=rel.text.encode("utf-8"))
  except CommandError as e:
    path = git("rev-parse", "--git-path", "xn-release.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f: f.write(rel.text)
    p.err(f"{fmt_release(rel.title)} pushed, GitHub Release failed | {e}")
    finish = f'gh release create {rel.tag} --verify-tag --title "{rel.title}" --notes-file {path}'
    p.tip(f"Finish with: {fmt_cmd(finish)}")
    sys.exit(2)
  p.ok(f"Released {fmt_release(rel.title)}: {url}")

#--------------------------------------------------------------------------------------------- Main

def main() -> None:
  parser = make_parser("Merge the active branch into main, or tag main itself, then publish",
    EXAMPLES)
  parser.add_argument("version", nargs="?", default=None,
    help="X.Y.Z, else the first entry of changes.md; a leading v stays in the tag")
  parser.add_argument("-n", "--note", default=None, metavar="PATH",
    help="Release text, else changes.md entry")
  parser.add_argument("--name", default=None,
    help="Release name, needed only when the repo has no release yet")
  parser.add_argument("--dry-run", action="store_true",
    help="Run every check and print the record, change nothing")
  parser.add_argument("--no-ci", action="store_true",
    help="Release without waiting for CI tests, recorded as such")
  add_help(parser)
  args = parser.parse_args()
  try:
    rel = prepare(args)
    message = record(rel)
    if args.dry_run:
      p.ok(f"Checks passed: {', '.join(rel.checks)}")
      p.inf(f"Dry run, nothing changed. Record of {fmt_release(rel.title)}:")
      print(f"\n{message}")
      return
    publish(rel, message)
  except CommandError as e:
    fail(str(e))

if __name__ == "__main__":
  main()
