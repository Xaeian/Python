# workflow.py

"""
Auto-generate GitHub Actions workflow for PyPI publishing.

Reads __repo__ and __python__ from package __init__.py,
generates a publish.yml with trusted publishing via OIDC.

Example:
  >>> from workflow import generate
  >>> generate("xaeian")

CLI:
  py workflow.py xaeian
  py workflow.py xaeian -o .github/workflows/publish.yml
"""

import ast, sys
from xaeian import FILE, DIR, PATH, Color, Ico

#------------------------------------------------------------------------------------- Analysis

def get_meta(pkg_dir:str) -> dict:
  """Extract `__repo__`, `__python__` from `__init__.py`."""
  meta = {"repo": "", "python": ">=3.10"}
  init = PATH.join(pkg_dir, "__init__.py")
  if not PATH.is_file(init): return meta
  try:
    tree = ast.parse(FILE.load(init))
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

#-------------------------------------------------------------------------------------- Public

def generate(package:str, output:str|None=None):
  """Generate GitHub Actions workflow for given package.

  Args:
    package: Package directory path.
    output: Output file path (default: .github/workflows/publish.yml).
  """
  pkg_dir = PATH.resolve(package)
  if not PATH.is_dir(pkg_dir):
    print(f"{Ico.ERR} {Color.ORANGE}{pkg_dir}{Color.END} is not a directory")
    sys.exit(1)
  meta = get_meta(pkg_dir)
  python_ver = meta["python"].replace(">=", "").replace(">", "")
  print(f"{Ico.INF} Python: {Color.SKY}{python_ver}{Color.END}")
  if meta["repo"]:
    print(f"{Ico.GAP} https://github.com/{Color.GREY}{meta['repo']}{Color.END}")
  workflow = generate_workflow(meta)
  out = output or PATH.join(PATH.dirname(pkg_dir), ".github", "workflows", "publish.yml")
  DIR.ensure(out)
  FILE.save(out, workflow)
  print(f"{Ico.OK} Generated {Color.ORANGE}{out}{Color.END}")

#----------------------------------------------------------------------------------------- CLI

EXAMPLES = """
examples:
  py workflow.py xaeian                 Generate with defaults
  py workflow.py xaeian -o publish.yml  Custom output path
"""

if __name__ == "__main__":
  import argparse

  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)

  class WorkflowParser(argparse.ArgumentParser):
    def format_help(self):
      return "\n" + super().format_help().rstrip() + "\n\n"

  p = WorkflowParser(
    description="Generate GitHub Actions workflow for PyPI publishing",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  p.add_argument("package", metavar="PACKAGE",
    help="Package directory to scan")
  p.add_argument("-o", "--output", default=None, metavar="PATH",
    help="Output file (default: .github/workflows/publish.yml)")
  p.add_argument("-h", "--help", action="help",
    help="Show this help message and exit")

  a = p.parse_args()
  generate(a.package, a.output)