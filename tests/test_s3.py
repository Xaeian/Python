# tests/test_s3.py

"""
S3 client: what the store answers, and what the translation above it makes of that.

Driven against a literal stand-in for the wire, because the cases that matter are the ones no
live bucket reproduces on demand: a copy that failed inside a 200, a listing that spans pages,
a key that would escape the root once it became a local path.

The stand-in also refuses to let a response go unread. An undrained body poisons a real
connection for whatever asks next, and nothing else in a test would notice.
"""

import hashlib
from datetime import datetime, timezone
from urllib import parse

import pytest

from xaeian.net import s3 as s3mod
from xaeian.net.s3 import S3, UNSIGNED

NS = "http://s3.amazonaws.com/doc/2006-03-01/"
STAMP = "2026-09-09T11:32:05.000Z"
HTTP_STAMP = "Wed, 09 Sep 2026 11:32:05 GMT"

#------------------------------------------------------------------------------- A literal S3 wire

class Response:
  """One answer, and whether anybody read it to the end."""
  def __init__(self, status:int, body:bytes=b"", headers:dict|None=None):
    self.status = status
    self._body = body
    self._headers = {k.lower(): v for k, v in (headers or {}).items()}
    self.drained = not body

  def read(self, want:int=-1) -> bytes:
    if want is None or want < 0:
      data, self._body = self._body, b""
    else:
      data, self._body = self._body[:want], self._body[want:]
    if not self._body: self.drained = True
    return data

  def getheader(self, name:str, default=None):
    return self._headers.get(name.lower(), default)

class Conn:
  """
  Stand-in for `http.client.HTTPSConnection` over a store that is a dict of keys to bytes.

  `deny` bends one key at a time, so a refusal can be aimed at exactly the call under test
  rather than at the whole session.
  """
  def __init__(self, objects=None, bucket="bucket", deny=(), page=1000, copy_fails=False):
    self.objects = dict(objects or {})
    self.bucket = bucket
    self.deny = set(deny)
    self.page = page
    self.copy_fails = copy_fails
    self.calls = []
    self.uploads = {}
    self.aborted = []
    self.closed = False
    self._issued = []
    self._seq = 0

  #--------------------------------------------------------------------------------- The connection

  def request(self, method:str, url:str, body=None, headers=None):
    self.calls.append((method, url))
    self._pending = self._answer(method, url, body, headers or {})

  def getresponse(self) -> Response:
    self._issued.append(self._pending)
    return self._pending

  def close(self):
    self.closed = True

  def undrained(self) -> list:
    return [r for r in self._issued if not r.drained]

  @staticmethod
  def attrs(data:bytes) -> dict:
    return {"content-length": str(len(data)), "last-modified": HTTP_STAMP,
      "etag": f'"{hashlib.md5(data).hexdigest()}"'}

  @staticmethod
  def drain(body) -> bytes:
    """Whatever the client handed as a body, as the bytes the store would have received."""
    if body is None: return b""
    if isinstance(body, bytes): return body
    out = b""
    while chunk := body.read(2**16):
      out += chunk
    return out
  #------------------------------------------------------------------------------------ The answers

  def _answer(self, method, url, body, headers) -> Response:
    parts = parse.urlsplit(url)
    query = {k: v[0] for k, v in parse.parse_qs(parts.query, keep_blank_values=True).items()}
    path = parts.path[len(f"/{self.bucket}/"):] if parts.path.count("/") > 1 else ""
    key = parse.unquote(path)
    if key in self.deny: return Response(403, b"<Error><Code>AccessDenied</Code></Error>")
    if "uploads" in query: return self._start(key)
    if "uploadId" in query: return self._part(method, key, query, body)
    if "delete" in query: return self._delete(body)
    if method == "GET" and query.get("list-type") == "2": return self._list(query)
    if method == "HEAD": return self._head(key)
    if method == "GET": return self._get(key)
    if method == "PUT": return self._put(key, body, headers)
    if method == "DELETE":
      self.objects.pop(key, None)
      return Response(204)
    return Response(400, b"<Error><Code>BadRequest</Code></Error>")

  def _head(self, key) -> Response:
    if not key: return Response(200) # the bucket itself, which `connect` asks about
    if key not in self.objects: return Response(404, b"<Error><Code>NoSuchKey</Code></Error>")
    return Response(200, headers=Conn.attrs(self.objects[key]))

  def _get(self, key) -> Response:
    if key not in self.objects: return Response(404, b"<Error><Code>NoSuchKey</Code></Error>")
    data = self.objects[key]
    return Response(200, data, Conn.attrs(data))

  def _put(self, key, body, headers) -> Response:
    source = headers.get("x-amz-copy-source")
    if source:
      if self.copy_fails:
        return Response(200, b'<?xml version="1.0"?><Error><Code>InternalError</Code>'
          b"<Message>We encountered an internal error</Message></Error>")
      src = parse.unquote(source[len(f"/{self.bucket}/"):])
      if src not in self.objects:
        return Response(404, b"<Error><Code>NoSuchKey</Code></Error>")
      self.objects[key] = self.objects[src]
      return Response(200, f'<?xml version="1.0"?><CopyObjectResult xmlns="{NS}">'
        f"<LastModified>{STAMP}</LastModified></CopyObjectResult>".encode())
    self.objects[key] = Conn.drain(body)
    return Response(200, headers=Conn.attrs(self.objects[key]))

  #-------------------------------------------------------------------------------------- Multipart

  def _start(self, key) -> Response:
    self._seq += 1
    upload = f"upload-{self._seq}"
    self.uploads[upload] = {}
    return Response(200, f'<?xml version="1.0"?><InitiateMultipartUploadResult xmlns="{NS}">'
      f"<UploadId>{upload}</UploadId></InitiateMultipartUploadResult>".encode())

  def _part(self, method, key, query, body) -> Response:
    upload = query["uploadId"]
    if method == "DELETE":
      self.uploads.pop(upload, None)
      self.aborted.append(upload)
      return Response(204)
    if method == "PUT":
      data = Conn.drain(body)
      if self.deny and f"part{query['partNumber']}" in self.deny:
        return Response(403, b"<Error><Code>AccessDenied</Code></Error>")
      self.uploads[upload][int(query["partNumber"])] = data
      return Response(200, headers={"etag": f'"{hashlib.md5(data).hexdigest()}"'})
    parts = self.uploads.pop(upload)
    self.objects[key] = b"".join(parts[n] for n in sorted(parts))
    return Response(200, f'<?xml version="1.0"?><CompleteMultipartUploadResult xmlns="{NS}">'
      f"<ETag>&quot;joined-{len(parts)}&quot;</ETag></CompleteMultipartUploadResult>".encode())

  #---------------------------------------------------------------------------------------- Batches

  def _delete(self, body) -> Response:
    keys = [chunk.split("</Key>")[0] for chunk in body.decode().split("<Key>")[1:]]
    for key in keys:
      if key not in self.deny: self.objects.pop(key, None)
    errors = "".join(f"<Error><Key>{key}</Key><Code>AccessDenied</Code></Error>"
      for key in keys if key in self.deny)
    return Response(200, f'<?xml version="1.0"?><DeleteResult xmlns="{NS}">{errors}'
      "</DeleteResult>".encode())

  def _list(self, query) -> Response:
    prefix = query.get("prefix", "")
    delimiter = query.get("delimiter", "")
    keys = sorted(k for k in self.objects if k.startswith(prefix))
    folders, files = [], []
    for key in keys:
      rest = key[len(prefix):]
      if delimiter and delimiter in rest:
        branch = f"{prefix}{rest.split(delimiter)[0]}/"
        if branch not in folders: folders.append(branch)
      else:
        files.append(key)
    start = int(query.get("continuation-token", 0))
    window = files[start:start + self.page]
    more = start + self.page < len(files)
    body = [f'<?xml version="1.0"?><ListBucketResult xmlns="{NS}">']
    if not start:
      body += [f"<CommonPrefixes><Prefix>{f}</Prefix></CommonPrefixes>" for f in folders]
    for key in window:
      data = self.objects[key]
      body.append(f"<Contents><Key>{key}</Key><Size>{len(data)}</Size>"
        f"<LastModified>{STAMP}</LastModified>"
        f"<ETag>&quot;{hashlib.md5(data).hexdigest()}&quot;</ETag></Contents>")
    if more: body.append(f"<NextContinuationToken>{start + self.page}</NextContinuationToken>")
    body.append("</ListBucketResult>")
    return Response(200, "".join(body).encode())

#------------------------------------------------------------------------------------- The fixtures

@pytest.fixture
def wire():
  """A connected client over a small store, and the wire it is talking to."""
  conn = Conn(objects={
    "cdn/a.txt": b"abc",
    "cdn/img/logo.png": b"png-bytes",
    "cdn/img/": b"",
    "other/x.txt": b"x",
  })
  client = S3("endpoint", "key", "secret", "bucket")
  client._conn = conn
  return client, conn

#-------------------------------------------------------------------------------- What the store is

def a_missing_object_reads_as_absent_not_as_a_fault(wire):
  client, _ = wire
  assert client.stat("cdn/nope.txt") is None
  assert client.exists("cdn/nope.txt") is False

def a_refused_object_is_not_a_missing_one(wire):
  """
  The whole point of the shared faults. A 403 read as "not there" tells an operator to check
  a path that is fine, and hides the credential that is not.
  """
  client, conn = wire
  conn.deny.add("cdn/a.txt")
  with pytest.raises(PermissionError):
    client.get("cdn/a.txt", "unused")

def stat_carries_the_size_the_timestamp_and_the_digest(wire):
  client, _ = wire
  attrs = client.stat("cdn/a.txt")
  assert attrs.st_size == 3
  assert attrs.st_mtime is not None
  assert attrs.etag == hashlib.md5(b"abc").hexdigest()

def a_folder_is_not_a_thing_that_exists(wire):
  """`FTP.exists` and `SFTP.exists` answer True for a directory. A prefix owns no object."""
  client, _ = wire
  assert client.exists("cdn/img") is False

#----------------------------------------------------------------------------------- What it lists

def a_listing_leaves_out_the_folder_markers(wire):
  """A zero-byte key ending in the separator is a folder someone wanted visible, not a file."""
  client, _ = wire
  assert sorted((a.filename, a.is_dir) for a in client.ls("cdn")) == [("a.txt", False),
    ("img", True)]

def a_walk_is_files_only_with_the_path_as_the_name(wire):
  client, _ = wire
  assert sorted(a.filename for a in client.walk("cdn")) == ["a.txt", "img/logo.png"]

def a_listing_follows_the_continuation_token_to_the_end():
  """One page of a thousand is the store's cap, and a walk that stopped there would be a lie."""
  conn = Conn(objects={f"cdn/{n:03}.txt": b"x" for n in range(250)}, page=100)
  client = S3("endpoint", "key", "secret", "bucket")
  client._conn = conn
  assert len(client.walk("cdn")) == 250

def a_walk_leaves_out_a_key_that_would_escape_the_root():
  """
  Object keys are literal: the store never resolves `..`, so it holds one happily and the
  traversal only happens here, the moment the key becomes a local path.
  """
  conn = Conn(objects={"cdn/ok.txt": b"a", "cdn/../../etc/passwd": b"bad"})
  client = S3("endpoint", "key", "secret", "bucket")
  client._conn = conn
  assert [a.filename for a in client.walk("cdn")] == ["ok.txt"]

#---------------------------------------------------------------------------- What it does not lose

def a_copy_that_failed_inside_a_200_is_a_failure(wire):
  """
  The store holds the connection open while it copies, so it answers 200 before it knows how
  it went and puts the failure in the body. `rename` deletes the source next.
  """
  client, conn = wire
  conn.copy_fails = True
  with pytest.raises(OSError):
    client.copy("cdn/a.txt", "cdn/b.txt")

def a_rename_that_could_not_copy_keeps_the_source(wire):
  client, conn = wire
  conn.copy_fails = True
  with pytest.raises(OSError):
    client.rename("cdn/a.txt", "cdn/b.txt")
  assert conn.objects["cdn/a.txt"] == b"abc"

def a_rename_moves_the_object_and_drops_the_original(wire):
  client, conn = wire
  client.rename("cdn/a.txt", "cdn/b.txt")
  assert conn.objects["cdn/b.txt"] == b"abc"
  assert "cdn/a.txt" not in conn.objects

def a_batch_delete_refused_inside_a_200_is_a_failure(wire):
  """
  The status line says nothing here either. A batch answers 200 for a delete it only partly
  carried out and names the keys it would not touch, so a `rmdir` believed on the status
  reports an emptied prefix that is still there, and still billed.
  """
  client, conn = wire
  conn.deny.add("cdn/img/logo.png")
  with pytest.raises(PermissionError):
    client.rmdir("cdn/img")
  assert "cdn/img/logo.png" in conn.objects

def removing_what_is_already_gone_is_the_outcome_asked_for(wire):
  client, _ = wire
  client.remove("cdn/nope.txt")

def every_response_gets_drained(wire):
  """An unread body leaves bytes on the wire that the next request would read as its own."""
  client, conn = wire
  client.stat("cdn/a.txt")
  client.ls("cdn")
  client.walk("cdn")
  client.remove("cdn/a.txt")
  assert conn.undrained() == []

#----------------------------------------------------------------------------------------- Signing

SIGNED = (
  "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20260102/auto/s3/aws4_request, "
  "SignedHeaders=host;x-amz-content-sha256;x-amz-date, "
  "Signature=06858c17e5061639fce86a257c5366b4c589cef1cbb540698712d8e5643be59f"
)

class Frozen(datetime):
  """A clock the signature can be written down against."""
  @classmethod
  def now(cls, tz=None): return datetime(2026, 1, 2, 3, 4, 5, tzinfo=tz or timezone.utc)

@pytest.fixture
def signer(monkeypatch):
  """A client whose requests all carry the same stamp, so the signature is a fixed string."""
  monkeypatch.setattr(s3mod, "datetime", Frozen)
  return S3("ep.example", "AKIAEXAMPLE", "secret", "bkt")

def the_signature_is_the_one_the_store_was_handed_before(signer):
  """
  SigV4 is built by hand here and nothing on the wire checks it, so a real store would be
  the first to find a slip. A regression pin, not a proof of conformance: it says the
  canonical request, the header set and the scope still come out exactly as they came out.
  """
  headers = signer._headers("GET", "/bkt/cdn/a.txt", "list-type=2&prefix=cdn%2F", UNSIGNED, {})
  assert headers["authorization"] == SIGNED
  assert headers["x-amz-date"] == "20260102T030405Z"

def a_header_the_caller_adds_is_signed_with_the_rest(signer):
  """`extra` rides inside SignedHeaders, which is what lets `copy` name its source safely."""
  bare = signer._headers("PUT", "/bkt/k", "", UNSIGNED, {})
  named = signer._headers("PUT", "/bkt/k", "", UNSIGNED, {"x-amz-copy-source": "/bkt/src"})
  assert "x-amz-copy-source" in named["authorization"]
  assert named["authorization"] != bare["authorization"]

#--------------------------------------------------------------------------------------- Multipart

@pytest.fixture
def small_parts(monkeypatch):
  """Multipart limits shrunk to bytes, so the seam can be tested without a 5 GiB file."""
  monkeypatch.setattr(s3mod, "PUT_MAX", 10)
  monkeypatch.setattr(s3mod, "PART_MIN", 4)
  monkeypatch.setattr(s3mod, "PART_COUNT_MAX", 100)

def a_large_upload_goes_up_in_parts_and_arrives_whole(wire, small_parts, tmp_path):
  client, conn = wire
  body = b"0123456789abcde"
  src = tmp_path / "big.bin"
  src.write_bytes(body)
  client.put(str(src), "cdn/big.bin")
  assert conn.objects["cdn/big.bin"] == body
  assert conn.aborted == []

def a_part_that_was_refused_takes_the_whole_upload_back_down(wire, small_parts, tmp_path):
  """
  Parts already stored keep costing until something removes them, and the store removes
  nothing unasked. So a failure has to abort on its way out.
  """
  client, conn = wire
  conn.deny.add("part2")
  src = tmp_path / "big.bin"
  src.write_bytes(b"0123456789abcde")
  with pytest.raises(PermissionError):
    client.put(str(src), "cdn/big.bin")
  assert conn.aborted and "cdn/big.bin" not in conn.objects

def a_part_size_grows_only_where_the_count_would_not_fit():
  assert s3mod._part_size(2**30) == s3mod.PART_MIN
  huge = s3mod.PART_MIN * s3mod.PART_COUNT_MAX * 4
  assert -(-huge // s3mod._part_size(huge)) <= s3mod.PART_COUNT_MAX

#-------------------------------------------------------------------------------------------- Sync

def sync_push_sends_what_is_new_and_skips_what_matches(wire, tmp_path):
  client, conn = wire
  (tmp_path / "a.txt").write_bytes(b"abc") # already there, byte for byte
  (tmp_path / "new.txt").write_bytes(b"fresh")
  actions = client.sync_push(str(tmp_path), "cdn")
  assert sorted(actions) == [("put", "new.txt"), ("skip", "a.txt")]
  assert conn.objects["cdn/new.txt"] == b"fresh"

def sync_push_catches_an_edit_that_kept_the_size(wire, tmp_path):
  """
  The reason the skip reads the ETag. A timestamp says nothing here: `LastModified` is when
  the object landed and no client sets it, so size-only would call this unchanged.
  """
  client, _ = wire
  (tmp_path / "a.txt").write_bytes(b"xyz") # same three bytes, different three bytes
  assert client.sync_push(str(tmp_path), "cdn") == [("put", "a.txt")]

def sync_push_delete_removes_what_the_source_no_longer_has(wire, tmp_path):
  client, conn = wire
  (tmp_path / "a.txt").write_bytes(b"abc")
  actions = client.sync_push(str(tmp_path), "cdn", delete=True)
  assert ("delete", "img/logo.png") in actions
  assert "cdn/img/logo.png" not in conn.objects

def sync_push_delete_stands_down_when_the_source_is_not_there(wire, tmp_path):
  """A missing source would make every object on the far end look deleted."""
  client, conn = wire
  actions = client.sync_push(str(tmp_path / "nothing"), "cdn", delete=True)
  assert not [a for a in actions if a[0] == "delete"]
  assert conn.objects["cdn/a.txt"] == b"abc"

def a_dry_run_plans_the_whole_thing_and_moves_nothing(wire, tmp_path):
  client, conn = wire
  (tmp_path / "new.txt").write_bytes(b"fresh")
  actions = client.sync_push(str(tmp_path), "cdn", delete=True, dry_run=True)
  assert ("put", "new.txt") in actions and ("delete", "a.txt") in actions
  assert "cdn/new.txt" not in conn.objects and conn.objects["cdn/a.txt"] == b"abc"

def a_filter_prunes_a_folder_as_it_does_on_a_file_protocol(wire, tmp_path):
  """
  A flat listing has no directory entries, so a filter written to prune one would never be
  asked about it. Every ancestor is offered as `name` and as `name/`, exactly as FTP offers it.
  """
  client, _ = wire
  actions = client.sync_push(str(tmp_path), "cdn", delete=True, dry_run=True,
    filter=lambda p: p != "img" and p != "img/")
  assert not [a for a in actions if a[1].startswith("img/")]

def sync_pull_writes_what_is_missing_and_leaves_the_rest(wire, tmp_path):
  client, _ = wire
  (tmp_path / "a.txt").write_bytes(b"abc")
  actions = client.sync_pull("cdn", str(tmp_path))
  assert sorted(actions) == [("get", "img/logo.png"), ("skip", "a.txt")]
  assert (tmp_path / "img" / "logo.png").read_bytes() == b"png-bytes"

def sync_pull_fetches_again_when_the_local_copy_was_edited(wire, tmp_path):
  client, _ = wire
  (tmp_path / "a.txt").write_bytes(b"xyz")
  assert ("get", "a.txt") in client.sync_pull("cdn", str(tmp_path))
  assert (tmp_path / "a.txt").read_bytes() == b"abc"

def a_filter_prunes_the_local_side_as_it_prunes_the_remote(wire, tmp_path):
  """
  The remote index is pruned per folder, so a local side that was not would send the excluded
  files on every run and never once read one back as unchanged. The filter names the folder
  only: a flat check would be asked about `vendor/x.txt`, which it has no opinion on.
  """
  client, conn = wire
  (tmp_path / "keep.txt").write_bytes(b"hello")
  (tmp_path / "vendor").mkdir()
  (tmp_path / "vendor" / "x.txt").write_bytes(b"hello")
  actions = client.sync_push(str(tmp_path), "cdn", filter=lambda p: p not in ("vendor", "vendor/"))
  assert ("put", "keep.txt") in actions
  assert not [a for a in actions if a[1].startswith("vendor")]
  assert "cdn/vendor/x.txt" not in conn.objects
