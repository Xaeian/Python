# xaeian/cli/host.py

"""SSH host keys recorded by `SFTP`: list them, or drop one after a server rebuild."""

import sys
from ..log import Print
from ..colors import Color as c
from .args import make_parser, add_help

p = Print()

EXAMPLES = """
Examples:
  xn host                          List recorded hosts
  xn host 10.0.0.1                 Show what is recorded for one host
  xn host 10.0.0.1 --drop          Drop it, its key is recorded again on next connect
  xn host 10.0.0.1 --drop -p 2222  Drop an entry recorded on a non-default port
"""

#--------------------------------------------------------------------------------------------- List

def _list() -> int:
  from ..net.sftp import SFTP, _known_hosts
  hosts = SFTP.known()
  if not hosts:
    p.inf(f"No hosts recorded yet {c.GREY}({_known_hosts()}){c.END}")
    return 0
  p.inf(f"Recorded {c.LIME}{len(hosts)}{c.END} hosts {c.GREY}({_known_hosts()}){c.END}")
  for host, kind in hosts:
    p.dot(f"{c.TURQUS}{host}{c.END} {c.GREY}{kind}{c.END}")
  return 0

#--------------------------------------------------------------------------------------------- Show

def _show(host:str, port:int) -> int:
  """What the trust store holds for one host, and the command that takes it back out."""
  from ..net.sftp import SFTP
  kind = SFTP.recorded(host, port)
  if not kind:
    p.wrn(f"Not recorded: {c.TURQUS}{host}{c.END}")
    return 1
  p.inf(f"{c.TURQUS}{host}{c.END} {c.GREY}{kind}{c.END}")
  p.tip(f"Drop it with: {c.YELLOW}xn{c.END} host {host} {c.GREY}--drop{c.END}")
  return 0

#----------------------------------------------------------------------------------------- Commands

def main() -> None:
  parser = make_parser("List or drop SSH host keys recorded by `SFTP`", EXAMPLES)
  parser.add_argument("host", nargs="?", default=None, help="Host to show (omit to list all)")
  parser.add_argument("--drop", action="store_true",
    help="Remove the host's recorded key, so the next connect records it anew")
  parser.add_argument("-p", "--port", type=int, default=22, metavar="N",
    help="Port the entry was recorded under (default: 22)")
  add_help(parser)
  args = parser.parse_args()
  try:
    from ..net.sftp import SFTP
  except ImportError as e:
    p.err(f"{e}")
    sys.exit(1)
  if args.host is None:
    sys.exit(_list())
  if not args.drop:
    sys.exit(_show(args.host, args.port))
  if SFTP.forget(args.host, args.port):
    p.ok(f"Dropped {c.TURQUS}{args.host}{c.END}, its key is recorded again on next connect")
    sys.exit(0)
  p.wrn(f"Not recorded: {c.TURQUS}{args.host}{c.END}")
  sys.exit(1)

if __name__ == "__main__":
  main()
