# xaeian/cli/commit.py

"""
`xn commit` - everything changed on the active branch, committed and pushed.

A branch tracking no remote one keeps the commit here.
Signed when git signs commits anyway (`commit.gpgsign`), as a plain `git commit` would be.
"""

import fnmatch, os, sys
from ..log import Print
from ..colors import Color as c
from .args import make_parser, add_help
from ._git import CommandError, git, sha, branch, fail

p = Print()

EXAMPLES = """
examples:
  xn commit -m "fix: Timeout"  # add, commit and push everything changed on this branch
"""

SECRETS = (".env*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*")
SIZE_MAX_MB = 5
COLORS = {"new": c.CREAM, "changed": c.GREY, "deleted": c.SALMON} # of each word `label` gives

# marker in the git directory of each operation that can be left half done
BUSY = (
  ("merge", "MERGE_HEAD"),
  ("rebase", "rebase-merge"),
  ("rebase", "rebase-apply"),
  ("cherry-pick", "CHERRY_PICK_HEAD"),
  ("revert", "REVERT_HEAD"),
)

#------------------------------------------------------------------------------------------- Checks

def preflight() -> str:
  """The active branch, once a commit may go on it; any refusal exits."""
  name = branch()
  if name is None: fail("Detached HEAD: switch to a branch first")
  for operation, mark in BUSY:
    if os.path.exists(git("rev-parse", "--git-path", mark)):
      fail(f"A {operation} is in progress: finish or abort it first")
  if git("diff", "--name-only", "--diff-filter=U"): fail("Unmerged paths: resolve them first")
  return name

def changes() -> list[tuple[str, str]]:
  """
  Status `XY` and path of each change, staged or not, new files included.

  `-z` gives every path as git stores it, unquoted.
  Without renames a move is a removal and an addition, each path with a status of its own.
  """
  fields = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
  return [(field[:2], field[3:]) for field in fields.split("\0") if field]

def refused(paths:list[str]) -> list[str]:
  """Paths no commit takes: a secret by its name or a file over `SIZE_MAX_MB`; a removal passes."""
  out = []
  for path in paths:
    if not os.path.isfile(path): continue
    name = os.path.basename(path).lower() # the same answer on every system
    secret = name != ".env.example" and any(fnmatch.fnmatchcase(name, s) for s in SECRETS)
    if secret or os.path.getsize(path) > SIZE_MAX_MB * 1024**2: out.append(path)
  return out

def ahead() -> bool:
  """Commits of the active branch its upstream lacks."""
  return git("rev-list", "--count", "@{upstream}..HEAD") != "0"

def label(status:str) -> str:
  """`deleted`, `new` or `changed`, the word for an `XY` code of `git status`."""
  if "D" in status: return "deleted"
  if "?" in status or "A" in status: return "new"
  return "changed"

#------------------------------------------------------------------------------------------- Commit

def push(name:str) -> None:
  """Push the branch to the one it tracks; a refusal keeps the commit here."""
  try:
    git("-c", "push.default=upstream", "push") # `simple` refuses a tracked branch of another name
  except CommandError as e:
    p.err(f"Push of {c.SKY}{name}{c.END} refused, the commit stays here | {e}")
    p.tip(f"Take the remote in with {c.YELLOW}git pull --rebase{c.END}, "
      f"then {c.YELLOW}git push{c.END}")
    sys.exit(1)
  p.ok(f"Pushed {c.SKY}{name}{c.END}")

def commit(message:str) -> None:
  """
  Stage what changed, commit, then push when the branch tracks a remote one.

  With nothing changed, commits waiting on a tracking branch go out.
  """
  name = preflight()
  tracked = sha("@{upstream}") is not None
  entries = changes()
  if not entries:
    if tracked and ahead(): push(name)
    else: p.inf(f"Nothing to commit on {c.SKY}{name}{c.END}")
    return
  out = refused([path for _, path in entries])
  if out:
    p.err(f"Nothing committed: a secret, or a file over {SIZE_MAX_MB}MB")
    for path in out: p.dot(f"{c.ORANGE}{path}{c.END}")
    p.tip(f"If it belongs in the repo, commit it with plain {c.YELLOW}git{c.END}")
    sys.exit(1)
  for status, path in entries:
    word = label(status)
    p.dot(f"{path} {COLORS[word]}{word}{c.END}")
  # Exactly the paths checked: a file that appeared since stays out.
  # A staged path is in already, and a staged removal is no path `git add` can match.
  # No `-A`: with an empty list it would take the whole tree.
  todo = [path for status, path in entries if status[1] != " "]
  listing = "\0".join(todo).encode("utf-8", "surrogateescape")
  git("--literal-pathspecs", "add", "--pathspec-from-file=-", "--pathspec-file-nul", data=listing)
  git("commit", "-F", "-", data=message.encode("utf-8"))
  short = git("rev-parse", "--short", "HEAD")
  p.ok(f"Committed {c.GOLD}{short}{c.END} on {c.SKY}{name}{c.END}")
  if tracked: push(name)
  else: p.inf(f"{c.SKY}{name}{c.END} tracks no remote branch: nothing pushed")

#--------------------------------------------------------------------------------------------- Main

def main() -> None:
  parser = make_parser("Commit everything changed on the active branch, then push it", EXAMPLES)
  parser.add_argument("-m", "--message", required=True, metavar="TEXT", help="Commit message")
  add_help(parser)
  args = parser.parse_args()
  try:
    os.chdir(git("rev-parse", "--show-toplevel"))
    commit(args.message)
  except CommandError as e:
    fail(str(e))

if __name__ == "__main__":
  main()
