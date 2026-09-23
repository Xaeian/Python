# tests/test_workflows.py

"""
The GitHub Actions workflows, held against their generator.

`workflow.py` owns `.github/workflows`, so a hand edit there is lost on the next run.
These tests fail while the committed files and the generator disagree.

This repo keeps a gate: `--ci` added it once, and every later run keeps it.
A repo without one writes `publish.yml` alone, and publishing then waits for nothing.
"""

from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
if not (REPO / "workflow.py").exists():
  # `publish.yml` copies `tests/` beside the wheel; the generator is a repository tool
  pytest.skip("not a repository checkout", allow_module_level=True)

import workflow

WORKFLOWS = REPO / ".github" / "workflows"

@pytest.fixture
def project():
  return workflow.scan(str(REPO / "xaeian"))

def the_committed_workflows_are_what_the_generator_writes(project):
  """A workflow edited by hand looks fine until someone regenerates and loses the edit."""
  written = {
    "ci.yml": workflow.generate_ci(project),
    "publish.yml": workflow.generate_publish(project, ci=True),
  }
  for name, text in written.items():
    on_disk = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert on_disk == text, f"{name} differs from workflow.py; run `py workflow.py xaeian`"

def both_workflows_say_they_are_generated():
  for name in ("ci.yml", "publish.yml"):
    assert (WORKFLOWS / name).read_text(encoding="utf-8").startswith(workflow.HEADER)

def publishing_waits_for_the_gate_only_when_asked(project):
  """A gate is opt-in: not every repo wants one, and publishing must not name a missing file."""
  gated = workflow.generate_publish(project, ci=True)
  assert "uses: ./.github/workflows/ci.yml" in gated and "needs: ci" in gated
  plain = workflow.generate_publish(project)
  assert "ci.yml" not in plain and "needs:" not in plain

#------------------------------------------------------------------------------------ what it reads

def the_matrix_runs_from_the_declared_floor(project):
  assert project.pythons[0] == "3.12" # `requires-python` in pyproject.toml
  assert project.pythons[-1] == workflow.NEWEST

def a_foreign_package_is_read_from_its_pyproject(tmp_path):
  """A package not built by `toml.py` states its floor where pip reads it, and nowhere else."""
  (tmp_path / "pkg").mkdir()
  (tmp_path / "pkg" / "__init__.py").write_text('__version__ = "1.0"', encoding="utf-8")
  (tmp_path / "pyproject.toml").write_text(
    '[project]\nname = "pkg"\nversion = "1.0"\nrequires-python = ">=3.13"\n',
    encoding="utf-8")
  assert workflow.scan(str(tmp_path / "pkg")).pythons == ["3.13", "3.14"]

def a_server_starts_only_where_a_driver_is_declared(project):
  """`scan` reads the drivers; it does not assume this repo's shape."""
  assert project.services == ["postgres", "mysql"]
  bare = workflow.Project("demo", ["3.12"], cairo=False, services=[], extra="",
    typed=False, tests=True)
  assert workflow.services_block(bare) == ""
  assert "services:" not in workflow.generate_ci(bare)
  assert "mypy" not in workflow.generate_ci(bare)

def a_package_without_tests_gets_no_test_steps():
  """Not every repo has a `tests/`; a suite step there would only fail."""
  bare = workflow.Project("demo", ["3.12"], False, [], "", False, tests=False)
  ci = workflow.generate_ci(bare)
  assert "pytest" not in ci
  assert 'pip install "$(echo dist/*.whl)"' in ci # the wheel still has to install
  assert "cp -r tests" not in workflow.generate_publish(bare)

def the_env_names_follow_the_package(project):
  assert "XAEIAN_TEST_POSTGRES: ci" in workflow.generate_ci(project)
  named = workflow.Project("demo", ["3.12"], False, ["postgres"], "", False, True)
  assert "DEMO_TEST_POSTGRES: ci" in workflow.generate_ci(named)

def a_gate_already_there_survives_a_run_without_the_flag(tmp_path):
  """
  `--ci` is how a gate is added; forgetting it later must not take the gate away.
  A release that ships unchecked because someone regenerated is the failure this guards.
  """
  workflow.generate("xaeian", folder=str(tmp_path))
  assert "needs: ci" not in (tmp_path / "publish.yml").read_text(encoding="utf-8")
  workflow.generate("xaeian", folder=str(tmp_path), ci=True)
  workflow.generate("xaeian", folder=str(tmp_path))
  assert "needs: ci" in (tmp_path / "publish.yml").read_text(encoding="utf-8")
