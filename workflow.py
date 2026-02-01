"""
Auto-generate GitHub Actions workflow for PyPI publishing.

Usage:
  python gen_workflow.py <package_dir> [-o .github/workflows/publish.yml]
"""

import ast, sys
from pathlib import Path
from xaeian import FILE, DIR

#------------------------------------------------------------------------------------- Analysis

def get_meta(pkg_dir:Path) -> dict:
  """Extract __repo__, __python__ from __init__.py."""
  meta = {"repo": "", "python": ">=3.10"}
  init = pkg_dir / "__init__.py"
  if not init.exists(): return meta
  try:
    tree = ast.parse(FILE.load(str(init)))
    for node in ast.walk(tree):
      if isinstance(node, ast.Assign):
        for t in node.targets:
          if not isinstance(t, ast.Name): continue
          if isinstance(node.value, ast.Constant):
            val = str(node.value.value)
            if t.id == "__repo__": meta["repo"] = val
            elif t.id == "__python__": meta["python"] = val
  except Exception: pass
  return meta

#------------------------------------------------------------------------------------- Generate

def generate_workflow(meta:dict) -> str:
  """Generate publish.yml content."""
  python_ver = meta["python"].replace(">=", "").replace(">", "")
  return f'''name: Publish PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "{python_ver}"
      - run: pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
'''

#----------------------------------------------------------------------------------------- Main

def main():
  import argparse
  parser = argparse.ArgumentParser(description="Generate GitHub workflow for PyPI")
  parser.add_argument("package", help="Package directory")
  parser.add_argument("-o", "--output", help="Output file (default: .github/workflows/publish.yml)")
  args = parser.parse_args()

  pkg_dir = Path(args.package).resolve()
  if not pkg_dir.is_dir():
    print(f"Error: {pkg_dir} is not a directory")
    sys.exit(1)

  meta = get_meta(pkg_dir)
  python_ver = meta["python"].replace(">=", "").replace(">", "")
  print(f"Python: {python_ver}")
  if meta["repo"]: print(f"Repo: {meta['repo']}")

  workflow = generate_workflow(meta)
  if args.output:
    out = args.output
  else:
    out = str(pkg_dir.parent / ".github" / "workflows" / "publish.yml")
  DIR.ensure(str(Path(out).parent))
  FILE.save(out, workflow)
  print(f"Generated: {out}")

if __name__ == "__main__":
  main()