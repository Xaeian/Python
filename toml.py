# toml.py

"""
Auto-generate pyproject.toml from package source analysis.
Scans Python files, detects modules, reads __extras__ declarations.

Each module/subpackage declares its own extras via __extras__:
  Tuple form: __extras__ = ("group", ["pkg1", "pkg2"])
  Dict form:  __extras__ = {"group": ["pkg1"], "group-async": ["pkg2"]}

Example:
  >>> from toml import generate
  >>> generate("xaeian")

CLI:
  py toml.py xaeian
  py toml.py xaeian -o pyproject.toml
"""

import ast, sys
from xaeian import FILE, DIR, PATH, Print, Color as c

p = Print()

#------------------------------------------------------------------------------------ Internals

def _parse_extras(node) -> dict[str, list[str]]:
  """Extract extras from AST node value (tuple or dict)."""
  if isinstance(node, ast.Tuple) and len(node.elts) == 2:
    name_node, list_node = node.elts
    if isinstance(name_node, ast.Constant) and isinstance(list_node, ast.List):
      pkgs = [e.value for e in list_node.elts if isinstance(e, ast.Constant)]
      return {str(name_node.value): pkgs}
  elif isinstance(node, ast.Dict):
    result = {}
    for k, v in zip(node.keys, node.values):
      if isinstance(k, ast.Constant) and isinstance(v, ast.List):
        pkgs = [e.value for e in v.elts if isinstance(e, ast.Constant)]
        result[str(k.value)] = pkgs
    return result
  return {}

def _scan_extras_from_file(path:str) -> dict[str, list[str]]:
  """Parse `__extras__` from a Python file."""
  if not PATH.is_file(path): return {}
  try:
    tree = ast.parse(FILE.load(path))
  except Exception:
    return {}
  for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
      for t in node.targets:
        if isinstance(t, ast.Name) and t.id == "__extras__":
          return _parse_extras(node.value)
  return {}

#------------------------------------------------------------------------------------- Analysis

def scan_package(pkg_dir:str) -> tuple[set[str], set[str]]:
  """Return (modules, subpackages) present in package."""
  modules = set()
  subpackages = set()
  for name in DIR.file_list(pkg_dir, local=True):
    if name.endswith(".py") and not name.startswith("__") and "/" not in name:
      modules.add(name.removesuffix(".py"))
  for name in DIR.folder_list(pkg_dir, basename=True):
    if PATH.is_file(PATH.join(pkg_dir, name, "__init__.py")):
      subpackages.add(name)
  return modules, subpackages

def build_extras(pkg_dir:str, modules:set[str], subpackages:set[str]) -> dict[str, list[str]]:
  """Build extras dict by scanning `__extras__` in modules and subpackages."""
  extras: dict[str, set[str]] = {}
  for mod in modules:
    found = _scan_extras_from_file(PATH.join(pkg_dir, f"{mod}.py"))
    for name, pkgs in found.items():
      extras.setdefault(name, set()).update(pkgs)
  for subpkg in subpackages:
    found = _scan_extras_from_file(PATH.join(pkg_dir, subpkg, "__init__.py"))
    for name, pkgs in found.items():
      extras.setdefault(name, set()).update(pkgs)
  if extras:
    all_deps = set()
    for deps in extras.values():
      all_deps.update(deps)
    extras["all"] = all_deps
  return {k: sorted(v) for k, v in extras.items()}

def get_meta(pkg_dir:str) -> dict:
  """Extract metadata from `__init__.py`."""
  meta = {
    "version": "0.1.0",
    "repo": "",
    "python": ">=3.10",
    "description": "",
    "author": "",
    "keywords": [],
    "dependencies": [],
    "scripts": {},
  }
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
            if t.id == "__version__": meta["version"] = val
            elif t.id == "__repo__": meta["repo"] = val
            elif t.id == "__python__": meta["python"] = val
            elif t.id == "__description__": meta["description"] = val
            elif t.id == "__author__": meta["author"] = val
          elif isinstance(node.value, ast.List):
            vals = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
            if t.id == "__keywords__": meta["keywords"] = vals
            elif t.id == "__dependencies__": meta["dependencies"] = vals
          elif isinstance(node.value, ast.Dict) and t.id == "__scripts__":
            meta["scripts"] = {
              k.value: v.value
              for k, v in zip(node.value.keys, node.value.values)
              if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
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
  deps_str = ", ".join(f'"{d}"' for d in meta["dependencies"])
  lines.append(f'dependencies = [{deps_str}]')
  lines.append('')
  if extras:
    lines.append('[project.optional-dependencies]')
    for name in sorted(extras.keys(), key=lambda x: (x == "all", x)):
      dep_str = ", ".join(f'"{d}"' for d in extras[name])
      lines.append(f'{name} = [{dep_str}]')
    lines.append('')
  if meta.get("scripts"):
    lines.append('[project.scripts]')
    for cmd, entry in meta["scripts"].items():
      lines.append(f'{cmd} = "{entry}"')
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

#--------------------------------------------------------------------------------------- Public

def generate(package:str, output:str|None=None):
  """Generate pyproject.toml for given package directory.

  Args:
    package: Package directory path.
    output: Output file path (default: parent/pyproject.toml).
  """
  pkg_dir = PATH.resolve(package)
  if not PATH.is_dir(pkg_dir):
    p.err(f"{c.ORANGE}{pkg_dir}{c.END} is not a directory")
    sys.exit(1)
  pkg_name = PATH.basename(pkg_dir)
  meta = get_meta(pkg_dir)
  modules, subpackages = scan_package(pkg_dir)
  extras = build_extras(pkg_dir, modules, subpackages)
  p.inf(f"Package: {c.TURQUS}{pkg_name}{c.END} {meta['version']}")
  if meta["repo"]:
    p.gap(f"https://github.com/{c.SKY}{meta['repo']}{c.END}")
  p.inf(f"Modules: {c.GREY}{', '.join(sorted(modules))}{c.END}")
  if subpackages:
    p.inf(f"Subpackages: {c.GREY}{', '.join(sorted(subpackages))}{c.END}")
  if meta["dependencies"]:
    p.inf(f"Dependencies: {c.GREY}{', '.join(meta['dependencies'])}{c.END}")
  if extras:
    for name, deps in sorted(extras.items(), key=lambda x: (x[0] == "all", x[0])):
      p.item(f"[{c.SKY}{name}{c.END}]: {c.GREY}{', '.join(deps)}{c.END}")
  if meta.get("scripts"):
    for cmd, entry in meta["scripts"].items():
      p.item(f"Script: {c.TURQUS}{cmd}{c.END} -> {c.GREY}{entry}{c.END}")
  toml = generate_toml(pkg_name, meta, extras)
  out = output or PATH.join(PATH.dirname(pkg_dir), "pyproject.toml")
  FILE.save(out, toml)
  p.ok(f"Generated {c.GREY}{PATH.dirname(out)}/{c.END}{c.ORANGE}{PATH.basename(out)}{c.END}")

#------------------------------------------------------------------------------------------ CLI

EXAMPLES = """
examples:
  py toml.py xaeian              Generate from package dir
  py toml.py xaeian -o out.toml  Custom output path
"""

if __name__ == "__main__":
  import argparse
  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)
  class TomlParser(argparse.ArgumentParser):
    def format_help(self): return "\n" + super().format_help().rstrip() + "\n\n"
  parser = TomlParser(
    description=f"Generate {c.ORANGE}pyproject.toml{c.END} from package source",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  parser.add_argument("package", metavar="PACKAGE", help="Package directory to scan")
  parser.add_argument("-o", "--output", default=None, metavar="PATH",
    help="Output file (default: parent/pyproject.toml)")
  parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")
  args = parser.parse_args()
  generate(args.package, args.output)