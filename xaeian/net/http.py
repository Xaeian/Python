# xaeian/net/http.py

"""
Plain HTTP(S) download: the one transfer that needs no client and no login.

`download` streams a URL into a file, atomic beside the target, with a `Progress` callback.
Errors are the stdlib ones, `urllib.error.HTTPError` and `URLError`.

Example:
  >>> from xaeian.net import download
  >>> download(url, "tool.zip")
"""

import urllib.request
from ..files import FILE
from .common import CHUNK, TIMEOUT_S, Progress

def download(url:str, local:str, *, callback:Progress|None=None, timeout:float=TIMEOUT_S) -> None:
  """
  Fetch `url` into `local`.

  `callback` gets `(url, bytes_done, bytes_total)` per chunk,
  total `0` when the server does not say.
  """
  with urllib.request.urlopen(url, timeout=timeout) as resp:
    total = int(resp.getheader("content-length") or 0)
    done = 0
    with FILE.atomic(local) as tmp, open(tmp, "wb") as f:
      while chunk := resp.read(CHUNK):
        f.write(chunk)
        done += len(chunk)
        if callback: callback(url, done, total)
