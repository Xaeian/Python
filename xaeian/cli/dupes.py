# xaeian/cli/dupes.py

"""Duplicate file finder - content hashing, optionally reaching inside ZIP archives."""

import os, sys, hashlib, zipfile
from collections import defaultdict
from ..files import FILE, JSON
from ..log import Print
from ..colors import Color as c

p = Print()

#---------------------------------------------------------------------------------------- Internals

def _hash_bytes(data:bytes, algo:str="sha256") -> str:
  return hashlib.new(algo, data).hexdigest()

def _hash_zip_entry(zip_path:str, info:zipfile.ZipInfo, algo:str="sha256") -> str|None:
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      return _hash_bytes(zf.read(info), algo)
  except Exception:
    return None

def _scan_zip(zip_path:str, min_size:int, items:dict):
  """Append ZIP entries to the size-keyed `items` dict; unreadable archives are skipped."""
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      for info in zf.infolist():
        if info.is_dir() or info.file_size < min_size: continue
        ref = f"zip://{zip_path}::{info.filename}"
        items[info.file_size].append(("zip", zip_path, info, ref))
  except Exception:
    pass

def _short(ref:str, root:str) -> str:
  """Shorten a `find_dupes` ref for printing; a ZIP entry keeps its `::entry` suffix."""
  if not ref.startswith("zip://"): return os.path.relpath(ref, root)
  archive, _, entry = ref.removeprefix("zip://").partition("::")
  return f"{os.path.relpath(archive, root)}::{entry}"

def _is_zip(path:str) -> bool:
  if not path.lower().endswith(".zip"): return False
  try: return zipfile.is_zipfile(path)
  except Exception: return False

from ._args import _fmt_size

#---------------------------------------------------------------------------------------------- API

def find_dupes(
  root:str,
  algo:str = "sha256",
  min_size:int = 1,
  zips:bool = False,
  follow_symlinks:bool = False,
) -> list[dict]:
  """
  Find duplicate files under `root` by content hash.

  Groups by size first, hashes only size-collisions. Unreadable files and archives are skipped.

  Args:
    algo: Any `hashlib` name (sha256, md5, sha1).
    min_size: Skip files below N bytes.
    zips: Hash entries inside .zip archives instead of the archive itself.
    follow_symlinks: Walk into symlinked directories, so link and target report as duplicates.

  Returns:
    Dicts with keys: size, hash, count, paths - sorted by size ascending.
    A ZIP entry appears as `zip://<archive>::<entry>`.
  """
  root = os.path.abspath(root)
  if not os.path.isdir(root):
    raise FileNotFoundError(f"Directory not found: {root}")
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
  groups = []
  for size, items in by_size.items():
    if len(items) < 2: continue
    by_hash = defaultdict(list)
    for kind, handle, info, ref in items:
      try:
        if kind == "file": digest = FILE.hash(handle, algo=algo)
        elif kind == "zip": digest = _hash_zip_entry(handle, info, algo)
        else: continue
        if digest: by_hash[digest].append(ref)
      except Exception:
        continue
    for digest, refs in by_hash.items():
      if len(refs) >= 2:
        groups.append({"size": size, "hash": digest, "count": len(refs), "paths": sorted(refs)})
  groups.sort(key=lambda g: g["size"])
  return groups

#---------------------------------------------------------------------------------------------- CLI

EXAMPLES = """
examples:
  xn dupes photos/            Find duplicates
  xn dupes docs/ --zips       Include ZIP contents
  xn dupes . --min-size 1024  Skip files < 1 kB
  xn dupes . --algo md5       Use MD5 (faster)
  xn dupes . -o report.json   Save JSON report
"""

def main():
  from ._args import _make_parser, _add_help
  parser = _make_parser("Find duplicate files by content hash", EXAMPLES)
  parser.add_argument("root", help="Directory to scan")
  parser.add_argument("--algo", default="sha256", metavar="ALG",
    choices=["sha256", "md5", "sha1"], help="Hash algorithm (default: sha256)")
  parser.add_argument("--min-size", type=int, default=1, metavar="N",
    help="Ignore files < N bytes (default: 1)")
  parser.add_argument("--zips", action="store_true", help="Scan inside .zip archives")
  parser.add_argument("--follow-symlinks", action="store_true", help="Follow symbolic links")
  parser.add_argument("-o", "--output", default=None, metavar="PATH",
    help="Save JSON report to file")
  _add_help(parser)
  args = parser.parse_args()
  root = os.path.abspath(args.root)
  if not os.path.isdir(root):
    p.err(f"Directory {c.ORANGE}{root}{c.END} not found")
    sys.exit(1)
  p.inf(f"Scanning {c.ORANGE}{root}{c.END} "
    f"{c.GREY}({args.algo}, min {_fmt_size(args.min_size)}"
    f"{', +zips' if args.zips else ''}){c.END}")
  try:
    groups = find_dupes(root, args.algo, args.min_size, args.zips, args.follow_symlinks)
  except Exception as e:
    p.err(f"Scan failed | {e}")
    sys.exit(1)
  if not groups:
    p.ok("No duplicates found")
  else:
    total_files = sum(g["count"] for g in groups)
    wasted = sum((g["count"] - 1) * g["size"] for g in groups)
    p.wrn(f"Found {c.TEAL}{len(groups)}{c.END} duplicate groups, "
      f"{c.TEAL}{total_files}{c.END} files, "
      f"{c.ORANGE}{_fmt_size(wasted)}{c.END} wasted")
    print()
    for i, g in enumerate(groups, 1):
      p.inf(f"[{c.GOLD}{i}{c.END}] {c.CYAN}{_fmt_size(g['size'])}{c.END} "
        f"x{g['count']} {c.GREY}{g['hash'][:16]}...{c.END}")
      for path in g["paths"]:
        p.gap(f"{c.GREY}{_short(path, root)}{c.END}")
  if args.output:
    JSON.save_pretty(args.output, {"root": root, "zips": args.zips, "groups": groups})
    p.ok(f"Saved {c.TEAL}{args.output}{c.END}")

if __name__ == "__main__":
  main()