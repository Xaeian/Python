"""Multimeter recorder: continuous CSV log + space/enter capture, all-in-one."""

import threading, time
from time import sleep
from xaeian import Color, Time, CSV
from xaeian.serial import Recorder

DATE = Time().to("%Y-%m-%d")
PERIOD_MS = 1000

recs = [
  Recorder("COM7", name="U1", regex=Recorder.SCI_NORM,
    print_file=f"console-{DATE}.ansi", time_format="%H:%M:%S.%f"),
]
stop = threading.Event()

def make_row() -> dict:
  row = {"time": Time().to("%Y-%m-%d %H:%M:%S.%f")}
  for r in recs: row[r.name] = r.value
  return row

def reap():
  while not stop.is_set():
    t0 = time.time()
    if any(r.value is not None for r in recs):
      CSV.add_row(f"series-{DATE}.csv", make_row())
    drift = time.time() - t0
    if stop.wait(max(0, PERIOD_MS / 1000 - drift)): return

def capture():
  if not any(r.value is not None for r in recs):
    print(f"{Color.YELLOW}No measurement, capture skipped{Color.END}")
    return
  for r in recs: r.print(f"{Color.LIME}Captured: {r.value}")
  CSV.add_row(f"capture-{DATE}.csv", make_row())

if __name__ == "__main__":
  import keyboard  # type: ignore
  keyboard.add_hotkey("space", capture)
  keyboard.add_hotkey("enter", capture)
  for r in recs: r.start()
  reaper = threading.Thread(target=reap, daemon=True)
  reaper.start()
  print(f"Recording every {Color.BLUE}{PERIOD_MS}ms{Color.END}")
  print(f"Press {Color.PINK}Space{Color.END}/{Color.PINK}Enter{Color.END} "
    f"to capture, {Color.ORANGE}(Ctrl+C){Color.END} to stop")
  try:
    while True: sleep(0.1)
  except KeyboardInterrupt: pass
  stop.set()
  for r in recs: r.stop()
  reaper.join(timeout=2)
  print(f"Stopped {Color.ORANGE}(Ctrl+C){Color.END}")