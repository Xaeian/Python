# tests/test_net_http.py

"""`download`: a stream into a file, atomic, with progress, against a local HTTP server."""

import threading, urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
import pytest
from xaeian.net import download

BODY = bytes(range(256)) * 4096 * 3 # 3 MiB, past one chunk, so the callback fires more than once

class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
    if self.path != "/tool.bin":
      self.send_error(404)
      return
    self.send_response(200)
    self.send_header("Content-Length", str(len(BODY)))
    self.end_headers()
    self.wfile.write(BODY)

  def log_message(self, *args): pass

@pytest.fixture
def url():
  server = HTTPServer(("127.0.0.1", 0), Handler)
  threading.Thread(target=server.serve_forever, daemon=True).start()
  yield f"http://127.0.0.1:{server.server_port}"
  server.shutdown()

def download_lands_the_bytes_and_reports_progress(tmp_path, url):
  seen = []
  target = tmp_path / "deep" / "tool.bin"
  download(f"{url}/tool.bin", str(target), callback=lambda u, d, t: seen.append((d, t)))
  assert target.read_bytes() == BODY
  assert seen[-1] == (len(BODY), len(BODY)) and len(seen) > 1
  assert list(tmp_path.glob("deep/*.tmp")) == []

def download_leaves_the_old_file_on_an_http_error(tmp_path, url):
  target = tmp_path / "tool.bin"
  target.write_bytes(b"old")
  with pytest.raises(urllib.error.HTTPError):
    download(f"{url}/missing.bin", str(target))
  assert target.read_bytes() == b"old"
