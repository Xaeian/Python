# xaeian/cli/tree.py

"""
Directory tree visualizer with filtering and color output.

Example:
  >>> from xaeian.cli.tree import tree
  >>> tree("src/", exts=[".py"], ignore=["__pycache__"])
"""

import os
from xaeian import PATH, JSON, Color, Ico

#----------------------------------------------------------------------------------- Internals

_PIPE   = "│   "
_TEE    = "├── "
_LAST   = "└── "
_BLANK  = "    "

DEFAULT_IGNORE = {
  "__pycache__", ".git", ".svn", ".hg",
  "node_modules", ".tox", ".mypy_cache",
  ".pytest_cache", ".venv", "venv", ".env",
  ".DS_Store", "Thumbs.db",
}

def _fmt_size(b:int) -> str:
  if b < 1024: return f"{b} B"
  if b < 1024**2: return f"{b/1024:.1f}k"
  if b < 1024**3: return f"{b/1024**2:.1f}M"
  return f"{b/1024**3:.1f}G"

def _match_exts(name:str, exts:list[str]|None) -> bool:
  if not exts: return True
  return any(name.lower().endswith(e.lower()) for e in exts)

def _should_ignore(name:str, ignore:set[str]) -> bool:
  return name in ignore or name.startswith(".")

#----------------------------------------------------------------------------------------- API

def tree(
  root: str,
  exts: list[str]|None = None,
  ignore: set[str]|None = None,
  show_hidden: bool = False,
  show_size: bool = False,
  max_depth: int|None = None,
  dirs_only: bool = False,
  color: bool = True,
) -> dict:
  """Draw directory tree and return stats.

  Args:
    root: Root directory path.
    exts: Show only files with these extensions (e.g. [".py", ".c"]).
    ignore: Names to skip (default: __pycache__, .git, node_modules, etc.).
    show_hidden: Show dotfiles/dotdirs when True.
    show_size: Show file sizes.
    max_depth: Max recursion depth (None = unlimited).
    dirs_only: Show only directories.
    color: Use ANSI colors.

  Returns:
    Dict with keys: dirs, files, size, lines.
  """
  root = os.path.abspath(root)
  if not os.path.isdir(root):
    raise FileNotFoundError(f"Directory not found: {root}")
  if ignore is None:
    ignore = DEFAULT_IGNORE.copy()
  stats = {"dirs": 0, "files": 0, "size": 0, "lines": []}

  def _color(text, c):
    return f"{c}{text}{Color.END}" if color else text

  def _walk(dirpath:str, prefix:str, depth:int):
    try:
      entries = sorted(os.listdir(dirpath), key=lambda e: (not os.path.isdir(os.path.join(dirpath, e)), e.lower()))
    except PermissionError:
      stats["lines"].append(f"{prefix}{_LAST}{_color('[permission denied]', Color.RED)}")
      return
    # Filter
    filtered = []
    for name in entries:
      if not show_hidden and _should_ignore(name, ignore): continue
      if show_hidden and name != "." and name != ".." and name in ignore: continue
      full = os.path.join(dirpath, name)
      is_dir = os.path.isdir(full)
      if dirs_only and not is_dir: continue
      if not is_dir and not _match_exts(name, exts): continue
      filtered.append((name, full, is_dir))
    max_name = max((len(n) for n, _, d in filtered if not d), default=0)
    for i, (name, full, is_dir) in enumerate(filtered):
      is_last = (i == len(filtered) - 1)
      connector = _LAST if is_last else _TEE
      if is_dir:
        stats["dirs"] += 1
        label = _color(name + "/", Color.CYAN)
        stats["lines"].append(f"{prefix}{connector}{label}")
        if max_depth is None or depth < max_depth:
          extension = _BLANK if is_last else _PIPE
          _walk(full, prefix + extension, depth + 1)
      else:
        stats["files"] += 1
        try:
          sz = os.path.getsize(full)
        except OSError:
          sz = 0
        stats["size"] += sz
        if show_size:
          padded = name.ljust(max_name)
          size_str = _color(_fmt_size(sz).rjust(6), Color.GREY)
          stats["lines"].append(f"{prefix}{connector}{padded} {size_str}")
        else:
          stats["lines"].append(f"{prefix}{connector}{name}")

  root_label = _color(PATH.basename(root) + "/", Color.TEAL)
  stats["lines"].append(root_label)
  _walk(root, "", 0)
  return stats

#----------------------------------------------------------------------------------------- CLI

EXAMPLES = """
examples:
  py -m xaeian.cli.tree .                          Current directory
  py -m xaeian.cli.tree src/ -e .py .c             Only .py and .c files
  py -m xaeian.cli.tree . -d 2                     Max depth 2
  py -m xaeian.cli.tree . --size                   Show file sizes
  py -m xaeian.cli.tree . --dirs                   Directories only
  py -m xaeian.cli.tree . --hidden                 Include dotfiles
  py -m xaeian.cli.tree . -o tree.json             Save stats to JSON
"""

if __name__ == "__main__":
  import argparse

  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)

  class TreeParser(argparse.ArgumentParser):
    def format_help(self):
      return "\n" + super().format_help().rstrip() + "\n\n"

  p = TreeParser(
    description="Draw directory tree with filtering",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  p.add_argument("root", nargs="?", default=".",
    help="Root directory (default: .)")
  p.add_argument("-e", "--exts", nargs="+", default=None, metavar="EXT",
    help="Filter by extensions (e.g. .py .c .h)")
  p.add_argument("-d", "--depth", type=int, default=None, metavar="N",
    help="Max depth (default: unlimited)")
  p.add_argument("-i", "--ignore", nargs="+", default=None, metavar="NAME",
    help="Additional names to ignore")
  p.add_argument("--size", action="store_true",
    help="Show file sizes")
  p.add_argument("--dirs", action="store_true",
    help="Show directories only")
  p.add_argument("--hidden", action="store_true",
    help="Show hidden files and directories")
  p.add_argument("--no-color", action="store_true",
    help="Disable ANSI colors")
  p.add_argument("-o", "--output", default=None, metavar="PATH",
    help="Save stats to JSON file")
  p.add_argument("-h", "--help", action="help",
    help="Show this help message and exit")

  a = p.parse_args()
  ignore = DEFAULT_IGNORE.copy()
  if a.ignore:
    ignore.update(a.ignore)
  result = tree(
    a.root,
    exts=a.exts,
    ignore=ignore,
    show_hidden=a.hidden,
    show_size=a.size,
    max_depth=a.depth,
    dirs_only=a.dirs,
    color=not a.no_color,
  )
  for line in result["lines"]:
    print(line)
  print()
  print(f"{Ico.INF} {Color.TEAL}{result['dirs']}{Color.END} directories, "
        f"{Color.CYAN}{result['files']}{Color.END} files, "
        f"{Color.GREY}{_fmt_size(result['size']).strip()}{Color.END} total")
  if a.output:
    JSON.save_pretty(a.output, {
      "root": os.path.abspath(a.root),
      "dirs": result["dirs"],
      "files": result["files"],
      "size": result["size"],
    })
    print(f"{Ico.OK} Saved {Color.TEAL}{a.output}{Color.END}")