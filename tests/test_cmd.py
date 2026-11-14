# tests/test_cmd.py

"""Commands run to their end or left running, their output read as text or as bytes."""

import os, platform, signal, sys, time
import pytest
from xaeian.cmd import version, output, run, start, stop

PY = sys.executable
WINDOWS = sys.platform == "win32"

class Child:
  """Small programs for the tests, kept out of reach of `python_functions = ["*"]`."""
  @staticmethod
  def writes(data:bytes) -> list[str]:
    """A Python that writes `data` to stdout as it is."""
    return [PY, "-c", f"import sys; sys.stdout.buffer.write({data!r})"]

  @staticmethod
  def priority(pid:int) -> int:
    """Windows priority class of `pid`, its niceness elsewhere."""
    if sys.platform != "win32": return os.getpriority(os.PRIO_PROCESS, pid)
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid) # query limited information
    return ctypes.windll.kernel32.GetPriorityClass(handle)

  @staticmethod
  def gone(pid:int) -> bool:
    """`True` once the Windows process `pid` has ended."""
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid) # synchronize
    return not handle or ctypes.windll.kernel32.WaitForSingleObject(handle, 5000) == 0

#---------------------------------------------------------------------------------------------- Run

def version_finds_the_number_a_program_prints():
  assert version(PY) == platform.python_version()

def text_replaces_a_byte_that_is_no_utf8():
  """`taskkill` on a Polish Windows answers in cp852: the text survives, not a decode error."""
  said = Child.writes("ż".encode() + b"\xff\n")
  assert run(said).stdout == "ż\ufffd\n" and output(said) == "ż\ufffd"

def binary_keeps_the_bytes():
  assert run(Child.writes(b"\x00\xff"), binary=True).stdout == b"\x00\xff"

@pytest.mark.skipif(not WINDOWS, reason="cmd and its batch files are Windows'")
def a_batch_file_takes_its_arguments_as_text(tmp_path):
  """cmd would read a bare `&` as its own; one `%` or `"` no quote keeps is refused."""
  echo = tmp_path / "echo.cmd"
  echo.write_text("@echo %*\n")
  assert output([str(echo), "a & b", "c&d"]) == '"a & b" "c&d"'
  with pytest.raises(ValueError):
    run([str(echo), "50%"])

#--------------------------------------------------------------------------------------- Background

def a_started_process_talks_through_its_pipes_until_stopped():
  code = "import sys, time; print(sys.stdin.readline().upper(), flush=True); time.sleep(60)"
  proc = start([PY, "-c", code], stdin=True)
  proc.stdin.write(b"hello\n")
  proc.stdin.flush()
  assert proc.stdout.readline().strip() == b"HELLO"
  assert stop(proc) != 0 and proc.poll() is not None

@pytest.mark.parametrize("stderr, out, err", [
  ("pipe", b"out", b"err"),
  ("merge", b"outerr", None),
  ("drop", b"out", None),
])
def stderr_is_its_own_pipe_merged_or_dropped(stderr, out, err):
  code = "import sys; sys.stdout.write('out'); sys.stdout.flush(); sys.stderr.write('err')"
  assert start([PY, "-c", code], stderr=stderr).communicate() == (out, err)

def an_unknown_stderr_is_refused_by_name():
  with pytest.raises(ValueError, match="pipe, merge, drop"):
    start([PY, "-c", "pass"], stderr="null")

def below_runs_under_normal_priority():
  proc = start([PY, "-c", "import time; time.sleep(60)"], below=True)
  try:
    if WINDOWS: assert Child.priority(proc.pid) == 0x4000 # below normal
    else: assert Child.priority(proc.pid) >= 10
  finally:
    stop(proc)

def a_group_takes_a_signal_alone():
  """Sent to the group `start` made, the signal ends the process and passes the tests by."""
  name = "SIGBREAK" if WINDOWS else "SIGTERM"
  code = (f"import signal, sys, time\n"
    f"signal.signal(signal.{name}, lambda *a: (print('caught', flush=True), sys.exit(0)))\n"
    "print('ready', flush=True)\n"
    "while True: time.sleep(0.1)\n") # a short sleep, as a long one hears no Ctrl+Break
  proc = start([PY, "-c", code], group=True)
  assert proc.stdout.readline().strip() == b"ready"
  if WINDOWS: proc.send_signal(signal.CTRL_BREAK_EVENT)
  else: os.killpg(proc.pid, signal.SIGTERM) # the group exists only if `start` made it
  assert proc.wait(timeout=10) == 0 and proc.stdout.read().strip() == b"caught"

@pytest.mark.skipif(not WINDOWS, reason="cmd and its batch files are Windows'")
def stop_ends_what_a_batch_file_started(tmp_path):
  """A `.cmd` runs its Python under cmd: that Python ends with the process `start` gave."""
  pid_file, script = tmp_path / "pid", tmp_path / "sleep.py"
  script.write_text(f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
    "time.sleep(60)\n")
  batch = tmp_path / "sleep.cmd"
  batch.write_text(f'@"{PY}" "{script}"\n')
  proc = start([str(batch)])
  for _ in range(100):
    if pid_file.exists() and pid_file.read_text(): break
    time.sleep(0.1)
  stop(proc)
  assert Child.gone(int(pid_file.read_text()))
