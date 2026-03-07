# xaeian/cli/dupes.py

"""
Duplicate file finder -- hash-based with optional ZIP scanning.

Uses SHA-256 by default, groups by size first for speed.

Example:
  >>> from xaeian.cli.dupes import find_dupes
  >>> groups = find_dupes("photos/")
  >>> groups = find_dupes("archive/", zips=True, min_size=1024)
"""

import os, hashlib, zipfile
from collections import defaultdict
from xaeian import FILE, JSON, Color, Ico

#----------------------------------------------------------------------------------- Internals

def _hash_bytes(data:bytes, algo:str="sha256") -> str:
  return hashlib.new(algo, data).hexdigest()

def _hash_zip_entry(zip_path:str, info:zipfile.ZipInfo, algo:str="sha256") -> str|None:
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      return _hash_bytes(zf.read(info), algo)
  except Exception:
    return None

def _scan_zip(zip_path:str, min_size:int, items:dict):
  """Scan ZIP contents, add entries to size-grouped items dict."""
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      for info in zf.infolist():
        if info.is_dir() or info.file_size < min_size: continue
        ref = f"zip://{zip_path}::{info.filename}"
        items[info.file_size].append(("zip", zip_path, info, ref))
  except Exception:
    pass

def _is_zip(path:str) -> bool:
  if not path.lower().endswith(".zip"): return False
  try: return zipfile.is_zipfile(path)
  except Exception: return False

def _fmt_size(b:int) -> str:
  if b < 1024: return f"{b} B"
  if b < 1024**2: return f"{b/1024:.1f} kB"
  if b < 1024**3: return f"{b/1024**2:.1f} MB"
  return f"{b/1024**3:.1f} GB"

#----------------------------------------------------------------------------------------- API

def find_dupes(
  root: str,
  algo: str = "sha256",
  min_size: int = 1,
  zips: bool = False,
  follow_symlinks: bool = False,
) -> list[dict]:
  """Find duplicate files by content hash.

  Groups files by size first, then hashes only size-collisions.

  Args:
    root: Directory to scan.
    algo: Hash algorithm (sha256, md5, sha1).
    min_size: Ignore files smaller than N bytes.
    zips: Scan inside .zip archives.
    follow_symlinks: Follow symlinks when walking.

  Returns:
    List of dicts with keys: size, hash, count, paths.
    Sorted by size ascending.
  """
  root = os.path.abspath(root)
  if not os.path.isdir(root):
    raise FileNotFoundError(f"Directory not found: {root}")
  # Phase 1: group by size
  by_size = defaultdict(list)
  for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
    for name in filenames:
      path = os.path.join(dirpath, name)
      try:
        st = os.stat(path) if follow_symlinks else os.lstat(path)
      except Exception:
        continue
      if st.st_size < min_size: continue
      if zips and _is_zip(path):
        _scan_zip(path, min_size, by_size)
      else:
        by_size[st.st_size].append(("file", path, None, path))
  # Phase 2: hash only size-collisions
  groups = []
  for size, items in by_size.items():
    if len(items) < 2: continue
    by_hash = defaultdict(list)
    for kind, handle, info, ref in items:
      try:
        if kind == "file":
          digest = FILE.hash(handle, algo=algo)
        elif kind == "zip":
          digest = _hash_zip_entry(handle, info, algo)
        else:
          continue
        if digest:
          by_hash[digest].append(ref)
      except Exception:
        continue
    for digest, refs in by_hash.items():
      if len(refs) >= 2:
        groups.append({
          "size": size,
          "hash": digest,
          "count": len(refs),
          "paths": sorted(refs),
        })
  groups.sort(key=lambda g: g["size"])
  return groups

#----------------------------------------------------------------------------------------- CLI

EXAMPLES = """
examples:
  py -m xaeian.cli.dupes photos/                   Find duplicates
  py -m xaeian.cli.dupes docs/ --zips              Include ZIP contents
  py -m xaeian.cli.dupes . --min-size 1024         Skip files < 1 kB
  py -m xaeian.cli.dupes . --algo md5              Use MD5 (faster)
  py -m xaeian.cli.dupes . -o report.json          Save JSON report
"""

if __name__ == "__main__":
  import argparse

  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)

  class DupesParser(argparse.ArgumentParser):
    def format_help(self):
      return "\n" + super().format_help().rstrip() + "\n\n"

  p = DupesParser(
    description="Find duplicate files by content hash",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  p.add_argument("root",
    help="Directory to scan")
  p.add_argument("--algo", default="sha256", metavar="ALG",
    choices=["sha256", "md5", "sha1"],
    help="Hash algorithm (default: sha256)")
  p.add_argument("--min-size", type=int, default=1, metavar="N",
    help="Ignore files < N bytes (default: 1)")
  p.add_argument("--zips", action="store_true",
    help="Scan inside .zip archives")
  p.add_argument("--follow-symlinks", action="store_true",
    help="Follow symbolic links")
  p.add_argument("-o", "--output", default=None, metavar="PATH",
    help="Save JSON report to file")
  p.add_argument("-h", "--help", action="help",
    help="Show this help message and exit")

  a = p.parse_args()
  root = os.path.abspath(a.root)
  print(f"{Ico.INF} Scanning {Color.ORANGE}{root}{Color.END}...")
  groups = find_dupes(root, a.algo, a.min_size, a.zips, a.follow_symlinks)
  if not groups:
    print(f"{Ico.OK} No duplicates found")
  else:
    total_files = sum(g["count"] for g in groups)
    wasted = sum((g["count"] - 1) * g["size"] for g in groups)
    print(f"{Ico.OK} Found {Color.TEAL}{len(groups)}{Color.END} duplicate groups, "
          f"{Color.TEAL}{total_files}{Color.END} files, "
          f"{Color.ORANGE}{_fmt_size(wasted)}{Color.END} wasted")
    print()
    for i, g in enumerate(groups, 1):
      print(f"{Ico.INF} [{i}] {Color.CYAN}{_fmt_size(g['size'])}{Color.END} "
            f"x{g['count']} {Color.GREY}{g['hash'][:16]}...{Color.END}")
      for p in g["paths"]:
        display = os.path.relpath(p, root)
        print(f"{Ico.GAP} {Color.GREY}{display}{Color.END}")
  if a.output:
    JSON.save_pretty(a.output, {"root": root, "zips": a.zips, "groups": groups})
    print(f"\n{Ico.OK} Saved {Color.TEAL}{a.output}{Color.END}")