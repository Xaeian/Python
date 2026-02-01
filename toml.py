"""
Auto-generate pyproject.toml from package source analysis.
Scans Python files, detects modules, generates optional extras.

Usage:
  python gen_toml.py <package_dir> [-o pyproject.toml]
"""

import ast, sys
from pathlib import Path
from xaeian import FILE

#--------------------------------------------------------------------------------------- Config

MODULE_EXTRAS = {
  "xtime": ("time", ["pytz", "tzlocal"]),
  "serial_port": ("serial", ["pyserial"]),
  "cbash": ("serial", ["pyserial"]),
}

SUBPACKAGE_EXTRAS = {
  "db": {
    "db": ["pymysql", "psycopg2-binary"],
    "db-async": ["aiomysql", "asyncpg", "aiosqlite"],
  },
}

#------------------------------------------------------------------------------------- Analysis

def scan_package(pkg_dir:Path) -> tuple[set[str], set[str]]:
  """Return (modules, subpackages) present in package."""
  modules = set()
  subpackages = set()
  for pyfile in pkg_dir.glob("*.py"):
    if not pyfile.stem.startswith("__"):
      modules.add(pyfile.stem)
  for subdir in pkg_dir.iterdir():
    if subdir.is_dir() and (subdir / "__init__.py").exists():
      subpackages.add(subdir.name)
  return modules, subpackages


def build_extras(modules:set[str], subpackages:set[str]) -> dict[str, list[str]]:
  """Build extras dict from present modules and subpackages."""
  extras: dict[str, set[str]] = {}
  for mod in modules:
    if mod in MODULE_EXTRAS:
      extra_name, pkgs = MODULE_EXTRAS[mod]
      if extra_name not in extras:
        extras[extra_name] = set()
      extras[extra_name].update(pkgs)
  for subpkg in subpackages:
    if subpkg in SUBPACKAGE_EXTRAS:
      for extra_name, pkgs in SUBPACKAGE_EXTRAS[subpkg].items():
        if extra_name not in extras:
          extras[extra_name] = set()
        extras[extra_name].update(pkgs)
  if extras:
    all_deps = set()
    for deps in extras.values():
      all_deps.update(deps)
    extras["all"] = all_deps
  return {k: sorted(v) for k, v in extras.items()}


def get_meta(pkg_dir:Path) -> dict:
  """Extract metadata from __init__.py."""
  meta = {
    "version": "0.1.0",
    "repo": "",
    "python": ">=3.10",
    "description": "",
    "author": "",
    "keywords": [],
  }
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
            if t.id == "__version__": meta["version"] = val
            elif t.id == "__repo__": meta["repo"] = val
            elif t.id == "__python__": meta["python"] = val
            elif t.id == "__description__": meta["description"] = val
            elif t.id == "__author__": meta["author"] = val
          elif isinstance(node.value, ast.List) and t.id == "__keywords__":
            meta["keywords"] = [
              e.value for e in node.value.elts
              if isinstance(e, ast.Constant)
            ]
  except Exception: pass
  return meta


#------------------------------------------------------------------------------------- Generate

def generate_toml(pkg_name:str, meta:dict, extras:dict[str, list[str]]) -> str:
  """Generate pyproject.toml content."""
  lines = [
    '[build-system]',
    'requires = ["setuptools>=61.0", "wheel"]',
    'build-backend = "setuptools.build_meta"',
    '',
    '[project]',
    f'name = "{pkg_name}"',
    f'version = "{meta["version"]}"',
    f'description = "{meta["description"]}"',
    'readme = "readme.md"',
    'license = {text = "MIT"}',
    f'requires-python = "{meta["python"]}"',
  ]
  if meta["author"]:
    lines.append(f'authors = [{{name = "{meta["author"]}"}}]')
  if meta["keywords"]:
    kw_str = ", ".join(f'"{k}"' for k in meta["keywords"])
    lines.append(f'keywords = [{kw_str}]')
  lines.append('dependencies = []')
  lines.append('')
  if extras:
    lines.append('[project.optional-dependencies]')
    for name in sorted(extras.keys(), key=lambda x: (x == "all", x)):
      deps_str = ", ".join(f'"{d}"' for d in extras[name])
      lines.append(f'{name} = [{deps_str}]')
    lines.append('')
  lines.append('[project.urls]')
  if meta["repo"]:
    lines.append(f'Repository = "https://github.com/{meta["repo"]}"')
  else:
    lines.append(f'Repository = "https://github.com/.../{pkg_name}"')
  lines.append('')
  lines.append('[tool.setuptools.packages.find]')
  lines.append(f'include = ["{pkg_name}*"]')
  lines.append('')
  return "\n".join(lines)


#----------------------------------------------------------------------------------------- Main

def main():
  import argparse
  parser = argparse.ArgumentParser(description="Generate pyproject.toml")
  parser.add_argument("package", help="Package directory")
  parser.add_argument("-o", "--output", help="Output file (default: parent/pyproject.toml)")
  args = parser.parse_args()

  pkg_dir = Path(args.package).resolve()
  if not pkg_dir.is_dir():
    print(f"Error: {pkg_dir} is not a directory")
    sys.exit(1)

  pkg_name = pkg_dir.name
  meta = get_meta(pkg_dir)
  modules, subpackages = scan_package(pkg_dir)
  extras = build_extras(modules, subpackages)

  print(f"Package: {pkg_name} v{meta['version']}")
  if meta["repo"]: print(f"Repo: github.com/{meta['repo']}")
  print(f"Modules: {', '.join(sorted(modules))}")
  if subpackages: print(f"Subpackages: {', '.join(sorted(subpackages))}")
  if extras:
    print("Extras:")
    for name, deps in sorted(extras.items(), key=lambda x: (x[0] == "all", x[0])):
      print(f"  [{name}]: {', '.join(deps)}")

  toml = generate_toml(pkg_name, meta, extras)
  out = str(args.output) if args.output else str(pkg_dir.parent / "pyproject.toml")
  FILE.save(out, toml)
  print(f"Generated: {out}")


if __name__ == "__main__":
  main()