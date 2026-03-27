# xaeian/__main__.py

COMMANDS = {
  "wifi":  "xaeian.cli.wifi",
  "dupes": "xaeian.cli.dupes",
  "tree":  "xaeian.cli.tree",
  "min":   "xaeian.media.min",
  "meta":  "xaeian.media.meta",
  "ico":   "xaeian.media.ico"
}

def main():
  import sys, runpy
  if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
    print("Usage: xn <command> [args...]")
    print("Commands:", ", ".join(COMMANDS))
    sys.exit(0)
  cmd = sys.argv[1]
  module = COMMANDS.get(cmd)
  if not module:
    print(f"Unknown command: {cmd}")
    print("Commands:", ", ".join(COMMANDS))
    sys.exit(1)
  sys.argv = [module] + sys.argv[2:]
  runpy.run_module(module, run_name="__main__", alter_sys=True)

if __name__ == "__main__":
  main()