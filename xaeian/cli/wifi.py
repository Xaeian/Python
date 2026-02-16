# xaeian/scr/wifi.py

"""
Extract saved Wi-Fi network names and passwords.

Supports Windows (netsh) and Linux (nmcli).

Example:
  >>> from xaeian.scr.wifi import wifi_passwords
  >>> for net in wifi_passwords():
  ...   print(net["ssid"], net["password"])
"""

import os, re, subprocess, platform
from xaeian import JSON, Color, Ico

#----------------------------------------------------------------------------------- Internals

def _run(cmd:list[str]) -> str|None:
  try:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None
  except Exception:
    return None

def _windows() -> list[dict]:
  out = _run(["netsh", "wlan", "show", "profiles"])
  if not out: return []
  profiles = re.findall(r":\s*(.+)", out)
  profiles = [p.strip() for p in profiles if p.strip()]
  results = []
  for ssid in profiles:
    detail = _run(["netsh", "wlan", "show", "profile", ssid, "key=clear"])
    password = None
    if detail:
      m = re.search(r"Key Content\s*:\s*(.+)", detail)
      if not m:
        m = re.search(r"Zawarto.{1,5} klucza\s*:\s*(.+)", detail)
      if m:
        password = m.group(1).strip()
    results.append({"ssid": ssid, "password": password})
  return results

def _linux() -> list[dict]:
  conn_dir = "/etc/NetworkManager/system-connections"
  results = []
  out = _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
  if out:
    for line in out.strip().splitlines():
      parts = line.split(":")
      if len(parts) < 2: continue
      name, ctype = parts[0], parts[1]
      if "wireless" not in ctype and "wifi" not in ctype: continue
      detail = _run(["nmcli", "-s", "-t", "-f", "802-11-wireless-security.psk",
        "connection", "show", name])
      password = None
      if detail:
        for dl in detail.strip().splitlines():
          if "psk:" in dl:
            val = dl.split(":", 1)[-1].strip()
            if val and val != "--": password = val
      results.append({"ssid": name, "password": password})
    return results
  if not os.path.isdir(conn_dir): return []
  for fname in os.listdir(conn_dir):
    fpath = os.path.join(conn_dir, fname)
    if not os.path.isfile(fpath): continue
    try:
      with open(fpath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    except PermissionError:
      continue
    if "[wifi]" not in content: continue
    ssid_m = re.search(r"^ssid=(.+)$", content, re.MULTILINE)
    psk_m = re.search(r"^psk=(.+)$", content, re.MULTILINE)
    if ssid_m:
      results.append({
        "ssid": ssid_m.group(1).strip(),
        "password": psk_m.group(1).strip() if psk_m else None,
      })
  return results

#----------------------------------------------------------------------------------------- API

def wifi_passwords() -> list[dict]:
  """Get saved Wi-Fi networks with passwords.

  Returns:
    List of dicts with keys: ssid, password.
    Password is None if not stored or not accessible.
  """
  system = platform.system()
  if system == "Windows": networks = _windows()
  elif system == "Linux": networks = _linux()
  else: raise RuntimeError(f"Unsupported platform: {system}")
  networks.sort(key=lambda n: n["ssid"].lower())
  return networks

#----------------------------------------------------------------------------------------- CLI

EXAMPLES = """
examples:
  py -m xaeian.scr.wifi               List all saved networks + passwords
  py -m xaeian.scr.wifi -o wifi.json  Save report to JSON file
"""

if __name__ == "__main__":
  import argparse

  def fmt(prog):
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=34, width=90)

  class WifiParser(argparse.ArgumentParser):
    def format_help(self):
      return "\n" + super().format_help().rstrip() + "\n\n"

  p = WifiParser(
    description="Extract saved Wi-Fi passwords",
    formatter_class=fmt,
    add_help=False,
    usage=argparse.SUPPRESS,
    epilog=EXAMPLES,
  )
  p.add_argument("-o", "--output", default=None, metavar="PATH",
    help="Save JSON report to file")
  p.add_argument("-h", "--help", action="help",
    help="Show this help message and exit")

  a = p.parse_args()
  print(f"{Ico.INF} Scanning saved Wi-Fi profiles...")
  networks = wifi_passwords()
  if not networks:
    print(f"{Ico.WRN} No saved Wi-Fi networks found")
  else:
    has_pw = sum(1 for n in networks if n["password"])
    print(f"{Ico.INF} Found {Color.TEAL}{len(networks)}{Color.END} networks "
          f"({Color.CYAN}{has_pw}{Color.END} with password)")
    max_ssid = max(len(n["ssid"]) for n in networks)
    for n in networks:
      ssid = n["ssid"].ljust(max_ssid)
      if n["password"]:
        print(f"{Ico.DOT} {Color.CREAM}{ssid}{Color.END}  {n['password']}")
      else:
        print(f"{Ico.DOT} {Color.GREY}{ssid}  (open){Color.END}")
  if a.output:
    JSON.save_pretty(a.output, networks)
    print(f"\n{Ico.OK} Saved {Color.TEAL}{a.output}{Color.END}")