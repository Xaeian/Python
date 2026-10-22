# tests/test_xn_git.py

"""
`xn commit` and `xn release` against real git: a clone with a bare origin beside it.

Commits and tags are signed with a throwaway ssh key.
Git sees no global or system config, so a developer setup changes nothing here.
`gh` is a stand-in: logged in, CI green, one earlier release.
"""

import json, os, re, shutil, subprocess, sys
from pathlib import Path
from types import ModuleType
import pytest
from xaeian.cli import commit, release
from xaeian.cli._git import CommandError

if not shutil.which("git"): pytest.skip("git needed", allow_module_level=True)

FIRST = "## `1.0.0` First\n\n- `demo`: start\n"
SECOND = "## `1.1.0` Second\n\n- `demo`: more\n\n"
THIRD = "## `1.2.0` Third\n\n- `demo`: again\n\n"
TEXT = "**Second**\n- `demo`: more" # release text of `1.1.0`, taken from `changes.md`

#-------------------------------------------------------------------------------------------- Setup

class FakeGh:
  """`gh` as `xn release` calls it: logged in, CI green on any commit, one earlier release."""
  def __init__(self):
    self.runs = [{"status": "completed", "conclusion": "success", "databaseId": 101}]
    self.releases = [{"name": "Demo 1.0.0"}]
    self.down = False
    self.title = self.notes = None

  def __call__(self, *args:str, data:bytes=b"") -> str:
    if args[:2] == ("release", "create"):
      if self.down: raise CommandError("HTTP 502: GitHub down")
      self.title = args[args.index("--title") + 1]
      self.notes = data.decode("utf-8")
      return ""
    if args[:2] == ("run", "list"): return json.dumps(self.runs)
    if args[:2] == ("release", "list"): return json.dumps(self.releases)
    if args == ("--version",): return "gh version 2.80.0 (2026-01-01)"
    return "" # `auth status`

class Repo:
  """The clone under test in `root/work` and what drives it; git config comes from it alone."""
  def __init__(self, root:Path, monkeypatch:pytest.MonkeyPatch):
    self.work = root / "work"
    self.origin_path = root / "origin.git"
    self.gh = FakeGh()
    self.monkeypatch = monkeypatch
    (root / "gitconfig").touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(root / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

  def git(self, *args:str) -> str:
    """Stdout of `git args` in the clone; a failure fails the test."""
    done = subprocess.run(["git", *args], cwd=self.work, capture_output=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()

  def origin(self, *args:str) -> str:
    """Stdout of `git args` in the bare origin."""
    return self.git("-C", str(self.origin_path), *args)

  def write(self, path:str, text:str) -> None:
    (self.work / path).write_text(text, encoding="utf-8", newline="\n")

  def set_version(self, version:str) -> None:
    self.write("pyproject.toml", f'[project]\nname = "demo"\nversion = "{version}"\n')

  def commit_all(self, message:str) -> None:
    """Plain `git commit` of everything, unsigned, as a commit not made by `xn` lands."""
    self.git("add", "-A")
    self.git("commit", "-q", "-m", message)

  def merge_into_main(self) -> None:
    """`develop` merged into `main` by hand and pushed, as before a release from `main`."""
    self.git("switch", "-q", "main")
    self.git("merge", "-q", "--no-ff", "--no-edit", "develop")
    self.git("push", "-q")

  def xn(self, module:ModuleType, *args:str) -> int:
    """Exit code of `xn <command> args` run in the clone."""
    self.monkeypatch.setattr(sys, "argv", ["xn", *args])
    try:
      module.main()
    except SystemExit as e:
      return int(e.code or 0)
    return 0

  def xn_commit(self, message:str="fix: Timeout") -> int:
    return self.xn(commit, "-m", message)

  def xn_release(self, *args:str) -> int:
    return self.xn(release, *args)

@pytest.fixture(scope="session")
def key(tmp_path_factory) -> str:
  """Throwaway ed25519 key without a passphrase; every signature of the suite comes from it."""
  if not shutil.which("ssh-keygen"): pytest.skip("ssh-keygen needed to sign")
  path = tmp_path_factory.mktemp("key") / "id_ed25519"
  subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
  return path.as_posix()

@pytest.fixture(scope="session")
def template(tmp_path_factory, key) -> Path:
  """
  `main` released as `1.0.0` and `develop` checked out with entry `1.1.0`, both on origin.

  Built once, copied for every test: origin goes by a relative path, so a copy finds its own.
  """
  root = tmp_path_factory.mktemp("template")
  with pytest.MonkeyPatch.context() as monkeypatch:
    repo = Repo(root, monkeypatch)
    repo.work.mkdir()
    repo.git("init", "-q", "-b", "main")
    repo.git("init", "-q", "--bare", "-b", "main", "../origin.git")
    repo.git("remote", "add", "origin", "../origin.git")
    repo.git("config", "user.name", "Tester")
    repo.git("config", "user.email", "tester@example.com")
    repo.git("config", "gpg.format", "ssh")
    repo.git("config", "user.signingkey", key)
    repo.write("a.txt", "a\n")
    repo.set_version("1.0.0")
    repo.write("changes.md", f"# Changes\n\n{FIRST}")
    repo.commit_all("First")
    repo.git("tag", "1.0.0")
    repo.git("push", "-q", "-u", "origin", "main", "1.0.0")
    repo.git("switch", "-q", "-c", "develop")
    repo.set_version("1.1.0")
    repo.write("changes.md", f"# Changes\n\n{SECOND}{FIRST}")
    repo.commit_all("Second")
    repo.git("push", "-q", "-u", "origin", "develop")
  return root

@pytest.fixture
def repo(template, tmp_path, monkeypatch) -> Repo:
  """A copy of `template` for this test alone, run from its clone on `develop`."""
  shutil.copytree(template, tmp_path, dirs_exist_ok=True)
  repo = Repo(tmp_path, monkeypatch)
  monkeypatch.setattr(release, "gh", repo.gh)
  monkeypatch.chdir(repo.work)
  return repo

@pytest.fixture
def main(repo) -> Repo:
  """`repo` on `main` with `develop` merged by hand, where `1.1.0` waits to be released."""
  repo.merge_into_main()
  return repo

#---------------------------------------------------------------------------------------- xn commit

def a_commit_is_pushed_and_the_branch_stays(repo):
  """No signing set up, as with a plain `git commit`: the commit goes in unsigned."""
  repo.git("config", "--unset", "user.signingkey")
  repo.write("a.txt", "changed\n")
  repo.write("new.txt", "new\n")
  assert repo.xn_commit() == 0
  assert repo.git("log", "-1", "--format=%s") == "fix: Timeout"
  assert "\ngpgsig " not in repo.git("cat-file", "commit", "HEAD")
  assert repo.origin("rev-parse", "develop") == repo.git("rev-parse", "HEAD")
  assert repo.git("branch", "--show-current") == "develop"
  assert repo.git("status", "--porcelain") == ""

def a_commit_is_signed_when_git_signs_commits(repo):
  repo.git("config", "commit.gpgsign", "true")
  repo.write("a.txt", "changed\n")
  assert repo.xn_commit() == 0
  assert "\ngpgsig " in repo.git("cat-file", "commit", "HEAD")

def a_commit_on_main_goes_in_as_on_any_branch(repo):
  repo.git("switch", "-q", "main")
  repo.write("a.txt", "changed\n")
  assert repo.xn_commit() == 0
  assert repo.origin("rev-parse", "main") == repo.git("rev-parse", "HEAD")

def the_list_names_each_file_then_its_change(repo, capsys):
  repo.write("a.txt", "changed\n")
  repo.write("new.txt", "new\n")
  (repo.work / "changes.md").unlink()
  assert repo.xn_commit() == 0
  out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
  assert "a.txt changed" in out
  assert "new.txt new" in out
  assert "changes.md deleted" in out

def a_branch_tracking_nothing_keeps_its_commit_here(repo, capsys):
  repo.git("switch", "-q", "-c", "local")
  repo.write("a.txt", "changed\n")
  assert repo.xn_commit() == 0
  assert repo.git("log", "-1", "--format=%s") == "fix: Timeout"
  assert repo.origin("branch", "--list", "local") == ""
  assert repo.xn_commit() == 0
  out = capsys.readouterr().out
  assert "tracks no remote branch: nothing pushed" in out
  assert "Nothing to commit" in out

def a_branch_tracking_one_of_another_name_pushes_there(repo):
  repo.git("switch", "-q", "-c", "work", "--track", "origin/develop")
  repo.write("a.txt", "changed\n")
  assert repo.xn_commit() == 0
  assert repo.origin("rev-parse", "develop") == repo.git("rev-parse", "HEAD")

def a_staged_removal_and_a_move_go_in(repo):
  """`git add` cannot match a path already gone from the index, so staged changes stay staged."""
  repo.git("rm", "-q", "changes.md")
  repo.git("mv", "a.txt", "b.txt")
  assert repo.xn_commit() == 0
  assert repo.git("ls-tree", "--name-only", "HEAD").split() == ["b.txt", "pyproject.toml"]

@pytest.mark.parametrize("setup, said", [
  (lambda repo: repo.git("switch", "-q", "--detach"), "Detached HEAD"),
  (lambda repo: repo.write(".git/MERGE_HEAD", repo.git("rev-parse", "HEAD")), "A merge is in progress"),
])
def a_branch_not_ready_takes_no_commit(repo, capsys, setup, said):
  repo.write("a.txt", "changed\n")
  setup(repo)
  assert repo.xn_commit() == 1
  assert said in capsys.readouterr().out
  assert repo.git("diff", "--cached", "--name-only") == ""

def a_secret_at_the_root_stops_a_commit_from_a_subdirectory(repo, monkeypatch, capsys):
  """Paths from `git status` count from the root, so `xn commit` checks them from there."""
  (repo.work / "docs").mkdir()
  repo.write(".env", "TOKEN=secret\n")
  monkeypatch.chdir(repo.work / "docs")
  assert repo.xn_commit() == 1
  assert "Nothing committed: a secret" in capsys.readouterr().out

def an_unmerged_path_takes_no_commit(repo, capsys):
  """A conflicted `stash pop` leaves no operation in progress, only the unmerged path."""
  repo.write("a.txt", "mine\n")
  repo.git("stash", "-q")
  repo.write("a.txt", "theirs\n")
  repo.commit_all("Theirs")
  subprocess.run(["git", "stash", "pop", "-q"], cwd=repo.work, capture_output=True) # conflicts
  assert repo.xn_commit() == 1
  assert "Unmerged paths" in capsys.readouterr().out

@pytest.mark.parametrize("name", [".env", "deploy.PEM"])
def a_secret_stops_the_commit_and_the_index_stays(repo, capsys, name):
  repo.write("a.txt", "changed\n")
  repo.write(name, "secret\n")
  assert repo.xn_commit() == 1
  assert name in capsys.readouterr().out
  assert repo.git("diff", "--cached", "--name-only") == ""

def a_template_of_a_secret_goes_in(repo):
  repo.write(".env.example", "TOKEN=\n")
  assert repo.xn_commit() == 0
  assert ".env.example" in repo.git("ls-tree", "--name-only", "HEAD").split()

def a_file_over_the_size_cap_stops_the_commit(repo):
  with open(repo.work / "big.bin", "wb") as f: f.truncate(commit.SIZE_MAX_MB * 1024**2 + 1)
  assert repo.xn_commit() == 1

def a_secret_taken_out_goes(repo):
  """Removing a committed secret is the fix, never refused."""
  repo.write("deploy.pem", "secret\n")
  repo.commit_all("Leak")
  (repo.work / "deploy.pem").unlink()
  assert repo.xn_commit() == 0
  assert "deploy.pem" not in repo.git("ls-tree", "--name-only", "HEAD").split()

def a_file_appearing_after_the_check_stays_out(repo, monkeypatch):
  repo.write("a.txt", "changed\n")
  def late(paths:list[str]) -> list[str]:
    repo.write("late.txt", "late\n")
    return []
  monkeypatch.setattr(commit, "refused", late)
  assert repo.xn_commit() == 0
  assert repo.git("status", "--porcelain") == "?? late.txt"

def with_nothing_changed_a_waiting_commit_goes_out(repo, capsys):
  repo.git("commit", "-q", "--allow-empty", "-m", "Waiting")
  assert repo.xn_commit() == 0
  assert repo.origin("rev-parse", "develop") == repo.git("rev-parse", "HEAD")
  assert repo.xn_commit() == 0
  assert "Nothing to commit" in capsys.readouterr().out

def a_refused_push_keeps_the_commit(repo, capsys):
  repo.git("commit", "-q", "--allow-empty", "-m", "Elsewhere")
  repo.git("push", "-q")
  repo.git("reset", "-q", "--hard", "HEAD~1")
  repo.write("a.txt", "changed\n")
  assert repo.xn_commit() == 1
  assert repo.git("log", "-1", "--format=%s") == "fix: Timeout"
  assert "git pull --rebase" in capsys.readouterr().out

#--------------------------------------------------------------------------------------- xn release

def a_release_from_develop_merges_it_into_main_signed(repo):
  """The merge is built from refs: the work tree, untracked files included, is left alone."""
  base, develop = repo.git("rev-parse", "main"), repo.git("rev-parse", "develop")
  repo.write("scratch.txt", "not released\n")
  assert repo.xn_release("1.1.0") == 0
  merge = repo.origin("rev-parse", "main")
  assert repo.git("rev-list", "--parents", "-n", "1", merge).split()[1:] == [base, develop]
  assert repo.git("rev-parse", f"{merge}^{{tree}}") == repo.git("rev-parse", "develop^{tree}")
  assert "\ngpgsig " in repo.git("cat-file", "commit", merge)
  assert repo.origin("rev-parse", "1.1.0^{commit}") == merge
  assert repo.git("rev-parse", "main") == merge # local `main` follows, it is not checked out
  assert repo.git("status", "--porcelain") == "?? scratch.txt"

def a_release_on_main_tags_it_without_a_merge(main):
  head = main.git("rev-parse", "HEAD")
  assert main.xn_release("1.1.0") == 0
  assert main.origin("rev-parse", "main") == head
  assert main.origin("rev-parse", "1.1.0^{commit}") == head
  trailers = main.origin("tag", "--list", "--format=%(trailers:only)", "1.1.0")
  assert "Release-Checks: unreleased, version, changelog, code-version, ci" in trailers

def a_release_is_tagged_signed_and_published(repo):
  assert repo.xn_release("1.1.0") == 0
  assert "-----BEGIN SSH SIGNATURE-----" in repo.origin("cat-file", "tag", "1.1.0")
  assert (repo.gh.title, repo.gh.notes) == ("Demo 1.1.0", TEXT)

def a_bare_release_takes_version_and_text_from_changes_md(repo):
  assert repo.xn_release() == 0
  assert repo.origin("rev-parse", "1.1.0^{commit}") == repo.origin("rev-parse", "main")
  assert (repo.gh.title, repo.gh.notes) == ("Demo 1.1.0", TEXT)

def changelog_md_stands_in_for_changes_md(repo):
  repo.git("mv", "changes.md", "changelog.md")
  repo.commit_all("Rename")
  repo.git("push", "-q")
  assert repo.xn_release() == 0
  assert (repo.gh.title, repo.gh.notes) == ("Demo 1.1.0", TEXT)

def a_note_is_the_release_text_as_written(repo, tmp_path):
  (tmp_path / "note.md").write_text("Refs:\n#12 boot hangs\n", encoding="utf-8")
  assert repo.xn_release("-n", str(tmp_path / "note.md")) == 0
  assert repo.gh.notes == "Refs:\n#12 boot hangs"
  tag = repo.origin("cat-file", "tag", "1.1.0")
  assert "\n#12 boot hangs\n" in tag # `--cleanup=strip` would cut it

def without_a_changes_file_a_given_version_goes_out_without_text(repo, capsys):
  repo.git("rm", "-q", "changes.md")
  repo.commit_all("No changes file")
  repo.git("push", "-q")
  assert repo.xn_release("1.1.0") == 0
  assert "No release text" in capsys.readouterr().out
  assert repo.gh.notes == ""
  assert "changelog:none" in repo.origin("tag", "--list", "--format=%(trailers:only)", "1.1.0")

def the_record_lists_the_new_commits_and_closes_with_trailers(repo):
  develop = repo.git("rev-parse", "develop")
  assert repo.xn_release("1.1.0") == 0
  assert f"\nCommits:\n{develop} Second\n\n" in repo.origin("log", "-1", "--format=%B", "main")
  trailers = repo.origin("tag", "--list", "--format=%(trailers:only)", "1.1.0")
  assert re.fullmatch(
    r"Release-Version: 1\.1\.0\n"
    r"Release-Checks: target-pure, ahead, unreleased, version, changelog, code-version, ci\n"
    r"Release-CI: green 101\n"
    r"Release-Tool: xaeian \S+ release@[0-9a-f]{12} git \S+ gh 2\.80\.0\n"
    r"Approved-by: Tester <tester@example\.com>",
    trailers,
  )

def a_second_release_takes_only_the_new_commits(repo):
  assert repo.xn_release("1.1.0") == 0
  first = repo.origin("rev-parse", "main")
  repo.set_version("1.2.0")
  repo.write("changes.md", f"# Changes\n\n{THIRD}{SECOND}{FIRST}")
  repo.commit_all("Third")
  repo.git("push", "-q")
  assert repo.xn_release("1.2.0") == 0
  merge, third = repo.origin("rev-parse", "main"), repo.git("rev-parse", "develop")
  assert repo.git("rev-list", "--parents", "-n", "1", merge).split()[1:] == [first, third]
  assert f"\nCommits:\n{third} Third\n\n" in repo.origin("log", "-1", "--format=%B", "main")

def a_release_from_a_subdirectory_keeps_paths_relative_to_it(repo, monkeypatch, capsys):
  """The note is read where it was named, and the notes left behind are shown from there."""
  (repo.work / "docs").mkdir()
  (repo.work / "docs" / "note.md").write_text("Tested on the bench\n", encoding="utf-8")
  monkeypatch.chdir(repo.work / "docs")
  repo.gh.down = True
  assert repo.xn(release, "1.1.0", "-n", "note.md") == 2
  assert "--notes-file ../.git/xn-release.md" in capsys.readouterr().out
  assert os.path.isfile("../.git/xn-release.md")

def a_dry_run_prints_the_record_and_changes_nothing(repo, capsys):
  assert repo.xn_release("1.1.0", "--dry-run") == 0
  assert "Demo 1.1.0" in capsys.readouterr().out
  assert repo.origin("rev-parse", "main") == repo.git("rev-parse", "main")
  assert repo.git("tag", "--list") == "1.0.0"
  assert repo.gh.title is None

def a_skipped_ci_stays_in_the_record(repo, capsys):
  repo.gh.runs = []
  assert repo.xn_release("1.1.0", "--no-ci", "--dry-run") == 0
  out = capsys.readouterr().out
  assert "ci:skipped" in out
  assert "Release-CI: skipped" in out

def a_first_release_needs_a_name(repo, capsys):
  repo.gh.releases = []
  assert repo.xn_release("1.1.0", "--dry-run") == 1
  assert "pass --name" in capsys.readouterr().out
  assert repo.xn_release("1.1.0", "--dry-run", "--name", "Demo") == 0
  assert "Demo 1.1.0" in capsys.readouterr().out

def master_takes_the_release_without_main(repo):
  repo.origin("symbolic-ref", "HEAD", "refs/heads/master")
  repo.git("push", "-q", "origin", "main:master", ":main")
  assert repo.xn_release("1.1.0") == 0
  assert repo.origin("rev-parse", "master^2") == repo.git("rev-parse", "develop")

def a_hotfix_on_main_has_to_be_merged_back_first(repo, capsys):
  repo.git("switch", "-q", "main")
  repo.write("fix.txt", "fix\n")
  repo.commit_all("Hotfix")
  repo.git("push", "-q")
  repo.git("switch", "-q", "develop")
  assert repo.xn_release("1.1.0") == 1
  assert "main has changes the branch lacks" in capsys.readouterr().out
  repo.git("merge", "-q", "--no-edit", "origin/main")
  repo.git("push", "-q")
  assert repo.xn_release("1.1.0") == 0

def a_failed_github_release_leaves_its_notes_to_finish_with(repo, capsys):
  repo.gh.down = True
  assert repo.xn_release("1.1.0") == 2
  assert repo.origin("rev-parse", "1.1.0^{commit}") == repo.origin("rev-parse", "main")
  assert (repo.work / ".git" / "xn-release.md").read_text(encoding="utf-8") == TEXT
  assert "gh release create 1.1.0 --verify-tag" in capsys.readouterr().out

def a_push_race_leaves_origin_without_the_release(repo, monkeypatch, capsys):
  """Origin `main` moves between the checks and the push: the atomic push takes nothing."""
  other = repo.git("commit-tree", "-p", "main", "-m", "Elsewhere", "main^{tree}")
  git = release.git
  def racing(*args:str, data:bytes|None=None) -> str:
    if args[:2] == ("push", "--atomic"):
      repo.git("push", "-q", "origin", f"{other}:refs/heads/main")
    return git(*args, data=data)
  monkeypatch.setattr(release, "git", racing)
  assert repo.xn_release("1.1.0") == 1
  assert "Push refused" in capsys.readouterr().out
  assert repo.origin("rev-parse", "main") == other
  assert repo.origin("tag", "--list") == "1.0.0"
  assert repo.git("tag", "--list") == "1.0.0"

#------------------------------------------------------------------------------ xn release refusals

def a_detached_head_is_refused(repo, capsys):
  repo.git("switch", "-q", "--detach")
  assert repo.xn_release("1.1.0") == 1
  assert "Detached HEAD" in capsys.readouterr().out

def a_released_commit_is_not_released_again(main, capsys):
  assert main.xn_release() == 0
  assert main.xn_release() == 1
  assert "Nothing to release: the commit is 1.1.0 already" in capsys.readouterr().out

def without_main_or_master_nothing_is_released(repo, capsys):
  repo.origin("symbolic-ref", "HEAD", "refs/heads/develop")
  repo.git("push", "-q", "origin", ":main")
  assert repo.xn_release("1.1.0") == 1
  assert "Neither main nor master on origin" in capsys.readouterr().out

def a_local_branch_apart_from_origin_is_refused(repo, capsys):
  repo.git("commit", "-q", "--allow-empty", "-m", "Unpushed")
  assert repo.xn_release("1.1.0") == 1
  assert "Local develop differs from origin" in capsys.readouterr().out

def a_branch_gone_from_origin_is_refused(repo, capsys):
  """Deleted on origin by someone else: the stale `origin/develop` here must not count."""
  repo.origin("update-ref", "-d", "refs/heads/develop")
  assert repo.xn_release("1.1.0") == 1
  assert "develop is not on origin" in capsys.readouterr().out

def a_branch_matching_main_has_nothing_to_release(repo, capsys):
  repo.git("switch", "-q", "-c", "same", "origin/main")
  repo.git("push", "-q", "-u", "origin", "same")
  assert repo.xn_release("1.1.0") == 1
  assert "Nothing to release: same matches main" in capsys.readouterr().out

def without_a_changes_file_the_version_has_to_be_given(repo, capsys):
  repo.git("rm", "-q", "changes.md")
  repo.commit_all("No changes file")
  repo.git("push", "-q")
  assert repo.xn_release() == 1
  assert "No changes.md or changelog.md on the commit: pass the version" in capsys.readouterr().out

def a_given_version_has_to_match_the_changes_entry(repo, capsys):
  repo.set_version("1.2.0")
  repo.commit_all("Bump")
  repo.git("push", "-q")
  assert repo.xn_release("1.2.0") == 1
  assert "changes.md opens with 1.1.0, not 1.2.0" in capsys.readouterr().out

def a_tag_of_the_version_is_refused_with_v_or_without(repo, capsys):
  repo.git("tag", "v1.1.0", "main")
  assert repo.xn_release("1.1.0") == 1
  assert "Tag v1.1.0 exists only here: git tag -d v1.1.0" in capsys.readouterr().out

def a_version_below_the_last_tag_is_refused(repo, capsys):
  repo.write("changes.md", f"# Changes\n\n## `0.9.0` Old\n\n- `demo`: back\n\n{FIRST}")
  repo.commit_all("Old")
  repo.git("push", "-q")
  assert repo.xn_release() == 1
  assert "0.9.0 is below 1.0.0" in capsys.readouterr().out

def a_pyproject_of_another_version_is_refused(repo, capsys):
  repo.write("changes.md", f"# Changes\n\n{THIRD}{SECOND}{FIRST}")
  repo.commit_all("Third")
  repo.git("push", "-q")
  assert repo.xn_release() == 1
  assert "pyproject.toml says 1.1.0, not 1.2.0" in capsys.readouterr().out

#--------------------------------------------------------------------------- Note, CI and code hash

def a_note_is_read_with_lf(tmp_path):
  (tmp_path / "note.md").write_bytes(b"Refs:\r\n#12 boot hangs\r\n\r\n")
  assert release.read_note(str(tmp_path / "note.md")) == "Refs:\n#12 boot hangs"

@pytest.mark.parametrize("runs, said", [
  ([], "No CI run"),
  ([{"status": "in_progress", "conclusion": "", "databaseId": 7}], "CI still running"),
  ([{"status": "completed", "conclusion": "failure", "databaseId": 7}], "CI failed on the commit, run 7"),
])
def ci_short_of_green_is_refused(monkeypatch, capsys, runs, said):
  gh = FakeGh()
  gh.runs = runs
  monkeypatch.setattr(release, "gh", gh)
  with pytest.raises(SystemExit): release.ci_runs("0" * 40)
  assert said in capsys.readouterr().out

def code_hash_reads_crlf_as_lf(tmp_path):
  (tmp_path / "lf.py").write_bytes(b"a = 1\nb = 2\n")
  (tmp_path / "crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
  assert release.code_hash(str(tmp_path / "lf.py")) == release.code_hash(str(tmp_path / "crlf.py"))
