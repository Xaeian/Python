# xaeian/net/s3.py

"""
S3 client on stdlib `http.client`, mirroring the `FTP` and `SFTP` API so any can stand in.

Requests carry a hand-built SigV4 signature,
so the transport costs no dependency and holds one TLS connection for a whole `sync_push`.
Written for Cloudflare R2 and every other S3-compatible endpoint:
Backblaze B2, Wasabi, MinIO, AWS itself given its real region.

An object store has no directories, only key prefixes,
so `mkdir` does nothing and an empty prefix cannot be told from one that was never there.
What it has instead is a listing carrying size, timestamp and ETag together,
which makes the skip check exact on content where FTP can only compare sizes.

Credentials are named for what S3 calls them,
which is why this is its own class and not a third `Remote` backend:
an access key is not a user and a secret is not a password.

Example:
  >>> with S3("<account>.r2.cloudflarestorage.com", key_id, secret, "assets") as s3:
  ...   s3.sync_push("./dist", "cdn", delete=True)
"""

import os, base64, hashlib, hmac, http.client
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from xml.etree import ElementTree
from xml.sax.saxutils import escape
from ..log import Logger, Print
from ..colors import Color as c
from .common import (
  local_index, Filter, Progress, Action, Attrs, atomic_local, log_sync, pruned, safe_name,
  _gone, _refused,
)

#---------------------------------------------------------------------------------------- Constants

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
# HTTPS already protects the body, so an upload is never digested:
# hashing it would mean reading the file twice, once to sign and once to send.
UNSIGNED = "UNSIGNED-PAYLOAD"

TIMEOUT_S = 30
CHUNK = 2**20 # download and digest read size
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

# ListObjectsV2 page size, and the cap on one DeleteObjects batch
PAGE_MAX = 1000
# S3 refuses a single PUT above this; over it the upload goes multipart
PUT_MAX = 5 * 2**30
# every part but the last must reach this, and no upload may hold more than the count
PART_MIN = 5 * 2**20
PART_COUNT_MAX = 10_000

#------------------------------------------------------------------------------------------ Helpers

def _key(remote:str) -> str:
  """Object key from a path: the store has no root, so a leading separator is not one."""
  return remote.strip("/")

def _prefix(remote:str) -> str:
  """Listing prefix for a folder: the key plus its separator, or empty for the whole bucket."""
  key = _key(remote)
  return f"{key}/" if key else ""

def _marker(key:str) -> bool:
  """
  A key naming a folder rather than bytes.

  S3 has no directories.
  A client that wants one visible writes a zero-byte object whose key ends in the separator.
  Nobody asked for it: no listing reports it, no download opens it.
  """
  return key.endswith("/")

def _quote(key:str) -> str:
  """RFC 3986 path encoding; the separators between key segments stay literal."""
  return quote(key, safe="/")

def _query(params:dict|None) -> str:
  """Canonical query string: sorted, both sides fully percent-encoded."""
  if not params: return ""
  pairs = sorted((quote(k, safe=""), quote(str(v), safe="")) for k, v in params.items())
  return "&".join(f"{k}={v}" for k, v in pairs)

def _sign(key:bytes, msg:str) -> bytes:
  return hmac.new(key, msg.encode(), hashlib.sha256).digest()

def _signing_key(secret:str, date:str, region:str) -> bytes:
  """The date/region/service chain SigV4 derives from the secret."""
  key = _sign(f"AWS4{secret}".encode(), date)
  key = _sign(key, region)
  key = _sign(key, SERVICE)
  return _sign(key, "aws4_request")

def _http_time(value:str|None) -> float|None:
  """Epoch from the HTTP date a `Last-Modified` header carries."""
  return parsedate_to_datetime(value).timestamp() if value else None

def _iso_time(value:str|None) -> float|None:
  """Epoch from the ISO 8601 timestamp a listing carries."""
  return datetime.fromisoformat(value).timestamp() if value else None

def _etag(value:str|None) -> str|None:
  """ETag without the quotes the store wraps it in, `None` when it sent none."""
  return value.strip('"') if value else None

def _md5(path:Path) -> str:
  """Content digest, streamed. An ETag from a single-part upload is exactly this."""
  digest = hashlib.md5(usedforsecurity=False)
  with open(path, "rb") as f:
    while chunk := f.read(CHUNK):
      digest.update(chunk)
  return digest.hexdigest()

def _same(rs:Attrs, path:Path, size:int) -> bool:
  """
  Skip check for an object store: size first, then the content itself.

  `LastModified` is when the object landed and no client can set it,
  so a timestamp says nothing about whether these are the same bytes.
  The ETag does: for a single-part upload it IS the MD5 of the object,
  which catches the same-size edit that FTP without MFMT misses.

  A multipart ETag carries a `-<count>` suffix and digests the part digests,
  which nothing here can reproduce, so those keep the size-only answer and no more.
  """
  if rs.st_size != size: return False
  if not rs.etag or "-" in rs.etag: return True
  return _md5(path) == rs.etag

def _safe_rel(rel:str) -> bool:
  """
  Whether a key's path below the prefix may become a local one.

  Object keys are literal: nothing on the far side resolves `..`,
  so a key holding one is stored happily and only becomes a traversal when it is written to disk.
  Every segment is held to the rule a listed name is held to on the file protocols.
  """
  return bool(rel) and all(safe_name(part) for part in rel.split("/"))

def _part_size(size:int) -> int:
  """
  Part size for a multipart upload: the minimum, raised only where the count would not fit.

  10000 parts of 5 MiB reach 48 GiB, so nothing below that pays for a larger part.
  Above it the part grows to whatever keeps the count inside the limit, rounded up to a whole MiB.
  """
  if size <= PART_MIN * PART_COUNT_MAX: return PART_MIN
  need = -(-size // PART_COUNT_MAX)
  return -(-need // 2**20) * 2**20

def _confirm(body:bytes, expect:str, what:str):
  """
  Believe the body, not the status line.

  S3 holds the connection open while it copies, assembles or deletes,
  so it answers 200 before it knows the outcome and reports the failure inside as `<Error>`.
  Every call that needs this replaces or destroys something on success,
  so a 200 taken at face value is how the only copy of an object gets deleted.

  Returns the parsed body, because a batch reads further into it.
  """
  try:
    result = ElementTree.fromstring(body)
  except ElementTree.ParseError:
    raise OSError(f"{what} answered no XML: {body[:200].decode(errors='replace')}") from None
  if not result.tag.endswith(expect):
    detail = " ".join(node.text or "" for node in result).strip() or result.tag
    raise OSError(f"{what} failed: {detail}")
  return result

def _kept(result, what:str) -> None:
  """
  Keys a `DeleteResult` says it did not remove.

  A batch answers 200 for a delete it only partly carried out,
  and names every key it would not touch.
  Dropped, that is a `sync_push` reporting a removal that never happened.
  A key that was not there is not among them: the store counts that one as removed.
  """
  errors = result.findall(f"{NS}Error")
  if not errors: return
  key = errors[0].findtext(f"{NS}Key", "")
  code = errors[0].findtext(f"{NS}Code", "")
  more = f" and {len(errors) - 1} more" if len(errors) > 1 else ""
  if all(node.findtext(f"{NS}Code") == "AccessDenied" for node in errors):
    raise _refused(f"{key}{more}")
  raise OSError(f"{what} refused {c.GREY}{key}{c.END}{more}: {code}")

def _listed(node, name:str) -> Attrs:
  """One `Contents` node as `Attrs`, with `name` already relative to the listed prefix."""
  mtime = _iso_time(node.findtext(f"{NS}LastModified"))
  return Attrs(
    st_size=int(node.findtext(f"{NS}Size") or 0),
    st_mtime=mtime,
    filename=name,
    etag=_etag(node.findtext(f"{NS}ETag")),
  )

#------------------------------------------------------------------------------------- Request body

class _Body:
  """
  A bounded, counted window over an open file: what one request may read, and how far it got.

  `http.client` reads a file-like body until it answers empty and Content-Length does not stop it,
  so a part handed the bare file would send the whole remainder.
  The count rides along because the only place an upload's progress is visible is right here.
  """
  def __init__(self, file, size:int, report:Callable[[int], None]|None = None) -> None:
    self._file = file
    self._left = size
    self._done = 0
    self._report = report

  def read(self, want:int = -1) -> bytes:
    if self._left <= 0: return b""
    if want is None or want < 0: want = self._left
    data = self._file.read(min(want, self._left))
    self._left -= len(data)
    self._done += len(data)
    if self._report: self._report(self._done)
    return data

#----------------------------------------------------------------------------------------------- S3

class S3:
  """
  S3 client: push/pull sync, server-side copy, multipart upload.

  Accepts `Print`, `Logger`, or any object with `inf/wrn/err/dot` as `log`.

  Args:
    endpoint: Host only, no scheme. R2 is `<account>.r2.cloudflarestorage.com`.
    region: Signed into every request. R2 has none and signs `auto`; AWS needs the bucket's.
  """
  def __init__(
    self,
    endpoint:str,
    key_id:str,
    secret:str,
    bucket:str,
    *,
    region:str = "auto",
    log:Logger|Print|None = None,
  ) -> None:
    self.endpoint = endpoint
    self.bucket = bucket
    self.region = region
    self._key_id = key_id
    self._secret = secret
    self.log = log
    self._conn: http.client.HTTPSConnection|None = None

  def __enter__(self) -> "S3": self.connect(); return self
  def __exit__(self, *_) -> None: self.disconnect()

  #------------------------------------------------------------------------------------- Connection

  def connect(self) -> None:
    """
    Open the HTTPS connection and ask the bucket whether it is there.

    That question costs one round trip,
    and turns a wrong endpoint, a wrong key and a bucket under another account into a failure
    here, where the message can say so, instead of into a failure inside the first transfer.

    A failure here is raised and never also logged: the message carries the whole story,
    so a caller that prints what it catches would otherwise print it twice.
    """
    self._conn = http.client.HTTPSConnection(self.endpoint, timeout=TIMEOUT_S)
    try:
      self._send("HEAD").read()
    except Exception as e:
      self.disconnect()
      raise ConnectionError(
        f"S3 connect failed on {c.TURQUS}{self.endpoint}{c.END}/{self.bucket} | {e}") from e
    if self.log:
      where = f"{c.TURQUS}{self.endpoint}{c.END}/{c.VIOLET}{self.bucket}{c.END}"
      self.log.inf(f"connected {where} region:{c.CYAN}{self.region}{c.END}")

  def disconnect(self) -> None:
    """Close the HTTPS connection."""
    if self._conn:
      try: self._conn.close()
      except Exception: pass # a dead socket must not strand the client
      self._conn = None

  def _require_connected(self):
    if not self._conn: raise RuntimeError("S3 not connected: call connect() first")

  def _reset(self) -> None:
    """
    Drop the connection and open a fresh one.

    A response abandoned part-read leaves the rest of its bytes on the wire,
    where the next request reads them as its own answer.
    Closing is the only way back from that.
    """
    self.disconnect()
    self._conn = http.client.HTTPSConnection(self.endpoint, timeout=TIMEOUT_S)

  #--------------------------------------------------------------------------------------- Requests

  def _headers(self, method:str, uri:str, query:str, payload:str, extra:dict) -> dict:
    """SigV4 over the canonical request; anything in `extra` is signed with the rest."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    headers = {"host": self.endpoint, "x-amz-content-sha256": payload, "x-amz-date": stamp}
    headers |= {name.lower(): value for name, value in extra.items()}
    names = sorted(headers)
    signed = ";".join(names)
    block = "".join(f"{name}:{headers[name]}\n" for name in names)
    canonical = "\n".join([method, uri, query, block, signed, payload])
    scope = f"{date}/{self.region}/{SERVICE}/aws4_request"
    to_sign = "\n".join([ALGORITHM, stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signature = _sign(_signing_key(self._secret, date, self.region), to_sign).hex()
    auth = ", ".join([
      f"Credential={self._key_id}/{scope}",
      f"SignedHeaders={signed}",
      f"Signature={signature}",
    ])
    headers["authorization"] = f"{ALGORITHM} {auth}"
    return headers

  def _send(
    self,
    method:str,
    key:str = "",
    query:dict|None = None,
    body:bytes|_Body|None = None,
    length:int|None = None,
    payload:str = UNSIGNED,
    extra:dict|None = None,
  ) -> http.client.HTTPResponse:
    """
    One signed request, its response left open for the caller to drain.

    Draining is the caller's job and not optional:
    an unread body poisons the connection for whatever asks next.
    A refusal is translated here, so every method answers with the two faults the file clients
    answer with, and nothing below has to read a status code.
    """
    uri = f"/{self.bucket}/{_quote(key)}" if key else f"/{self.bucket}"
    canonical = _query(query)
    headers = self._headers(method, uri, canonical, payload, extra or {})
    # Without an explicit length http.client falls back to chunked encoding,
    # which plain SigV4 does not cover and S3 rejects.
    if length is not None: headers["content-length"] = str(length)
    url = f"{uri}?{canonical}" if canonical else uri
    self._conn.request(method, url, body=body, headers=headers)
    resp = self._conn.getresponse()
    if resp.status < 400: return resp
    detail = resp.read()[:200].decode(errors="replace")
    where = key or self.bucket
    if resp.status == 404: raise _gone(where)
    if resp.status == 403: raise _refused(where)
    raise OSError(f"{method} '{where}' → {resp.status} {detail}")

  #------------------------------------------------------------------------------------ Single file

  def stat(self, remote:str) -> Attrs|None:
    """Attributes via HEAD: `None` when absent, and also for a prefix, which owns no object."""
    self._require_connected()
    key = _key(remote)
    try: resp = self._send("HEAD", key)
    except FileNotFoundError: return None
    try:
      return Attrs(
        st_size=int(resp.getheader("content-length") or 0),
        st_mtime=_http_time(resp.getheader("last-modified")),
        filename=key.rsplit("/", 1)[-1],
        etag=_etag(resp.getheader("etag")),
      )
    finally:
      resp.read()

  def exists(self, remote:str) -> bool:
    """
    Whether an object is there. A folder answers `False`, where `FTP` and `SFTP` say `True`.

    There is nothing else to answer:
    a prefix is not a thing that exists, it is a shape some keys happen to share,
    and it is gone the moment the last of them is deleted.
    """
    return self.stat(remote) is not None

  def put(
    self,
    local:str,
    remote:str,
    *,
    atomic:bool = True,
    preserve_mtime:bool = False,
    callback:Progress|None = None,
    _label:str|None = None,
  ) -> None:
    """
    Upload single file. Over `PUT_MAX` the object goes up in parts instead.

    Args:
      atomic: Accepted and ignored.
        One request lands the whole object,
        and a multipart upload is invisible until it completes,
        so nothing here is ever half-written.
      preserve_mtime: Accepted and ignored.
        `LastModified` is when the object landed and no client sets it;
        `sync_push` skips on the ETag instead, which is exact.
    """
    self._require_connected()
    key = _key(remote)
    size = os.path.getsize(local)
    label = _label or remote
    if size > PUT_MAX:
      self._multipart(local, key, size, label, callback)
    else:
      report = (lambda done: callback(label, done, size)) if callback else None
      with open(local, "rb") as f:
        self._send("PUT", key, body=_Body(f, size, report), length=size).read()
    if self.log: self.log.dot(f"{c.GREY}{local}{c.END} → {c.GREY}{key}{c.END}")

  def get(
    self,
    remote:str,
    local:str,
    *,
    preserve_mtime:bool = False,
    callback:Progress|None = None,
    _label:str|None = None,
  ) -> None:
    """
    Download single file, creating the missing local parent directories.

    The bytes land beside the target and are swapped in on completion,
    so a failed transfer leaves the previous local file untouched.

    Args:
      preserve_mtime: Set local mtime to `LastModified`, when the object landed.
    """
    self._require_connected()
    key = _key(remote)
    label = _label or remote
    resp = self._send("GET", key)
    total = int(resp.getheader("content-length") or 0)
    mtime = _http_time(resp.getheader("last-modified"))
    done = 0
    try:
      with atomic_local(local) as tmp, open(tmp, "wb") as f:
        while chunk := resp.read(CHUNK):
          f.write(chunk)
          done += len(chunk)
          if callback: callback(label, done, total)
    except BaseException:
      self._reset() # the rest of this response is still on the wire
      raise
    if preserve_mtime and mtime is not None: os.utime(local, (mtime, mtime))
    if self.log: self.log.dot(f"{c.GREY}{key}{c.END} → {c.GREY}{local}{c.END}")

  def remove(self, remote:str) -> None:
    """Delete one object. Silent if it was not there: a missing key answers 204."""
    self._require_connected()
    self._send("DELETE", _key(remote)).read()

  def copy(self, src:str, dst:str) -> None:
    """
    Duplicate one object server-side: the bytes never leave the far end.

    The source is named in a signed header,
    so a missing one is the store's own 404 and reads here as `FileNotFoundError`.
    Above 5 GiB the store refuses and says so:
    CopyObject cannot move an object that large, and the multipart copy that can is another call.
    """
    self._require_connected()
    source = f"/{self.bucket}/{_quote(_key(src))}"
    body = self._send("PUT", _key(dst), length=0, extra={"x-amz-copy-source": source}).read()
    _confirm(body, "CopyObjectResult", f"copy '{src}' → '{dst}'")

  def rename(self, src:str, dst:str) -> None:
    """
    Rename/move one object: overwrites target.

    An object store has no rename,
    so this is the server-side copy followed by dropping the original.
    That is the whole reason `copy` reads the body rather than the status line:
    a copy believed on a 200 it had not earned would delete the only copy there was.
    """
    self._require_connected()
    self.copy(src, dst)
    self.remove(src)

  #-------------------------------------------------------------------------------------- Multipart

  def _multipart(self, local:str, key:str, size:int, label:str, callback:Progress|None) -> None:
    """
    Upload one object in parts, and take the upload back down if anything fails.

    An abandoned multipart upload is not free:
    the parts already stored keep costing until something removes them,
    and nothing on the far side does it unasked.
    So the abort sits in a `finally` and swallows its own failure,
    which would otherwise bury the one that caused it.
    """
    part = _part_size(size)
    upload = self._start(key)
    tags: list[tuple[int, str]] = []
    done = False
    try:
      with open(local, "rb") as f:
        for number in range(1, -(-size // part) + 1):
          base = (number - 1) * part
          count = min(part, size - base)
          report = (lambda sent, at=base: callback(label, at + sent, size)) if callback else None
          part_query = {"partNumber": number, "uploadId": upload}
          resp = self._send("PUT", key, query=part_query, body=_Body(f, count, report),
            length=count)
          tag = _etag(resp.getheader("etag")) or ""
          resp.read()
          if not tag: raise OSError(f"multipart '{key}' part {number} answered no ETag")
          tags.append((number, tag))
      self._finish(key, upload, tags)
      done = True
    finally:
      if not done:
        try: self._send("DELETE", key, query={"uploadId": upload}).read()
        except Exception: pass

  def _start(self, key:str) -> str:
    """Open a multipart upload and answer with the id every part must carry."""
    body = self._send("POST", key, query={"uploads": ""}, length=0).read()
    upload = ElementTree.fromstring(body).findtext(f"{NS}UploadId", "")
    if not upload: raise OSError(f"multipart '{key}' started without an upload id")
    return upload

  def _finish(self, key:str, upload:str, tags:list[tuple[int, str]]) -> None:
    """Complete the upload. Parts are named back in order, because the store assembles on it."""
    items = "".join(f"<Part><PartNumber>{number}</PartNumber><ETag>{escape(tag)}</ETag></Part>"
      for number, tag in tags)
    body = f"<CompleteMultipartUpload>{items}</CompleteMultipartUpload>".encode()
    digest = hashlib.sha256(body).hexdigest()
    answer = self._send("POST", key, query={"uploadId": upload},
      body=body, length=len(body), payload=digest).read()
    _confirm(answer, "CompleteMultipartUploadResult", f"multipart '{key}'")

  #------------------------------------------------------------------------------------ Directories

  def mkdir(self, remote:str, *, verify:bool = True) -> None:
    """
    Nothing to do: a prefix is there from the moment the first object is written under it.

    Kept, and kept quiet, so code written against `Remote` runs here without a branch.
    """

  def ls(self, remote:str) -> list[Attrs]:
    """
    One level under a prefix: `CommonPrefixes` are the folders, `Contents` the files.

    A prefix holding nothing answers `[]`, where `FTP.ls` and `SFTP.ls` raise `FileNotFoundError`.
    The store cannot tell those apart and neither can this:
    nothing records a prefix anywhere, only the keys under it,
    so empty and missing are one state.

    A folder entry carries neither size nor timestamp, because no object holds them.
    """
    self._require_connected()
    prefix = _prefix(remote)
    out = []
    for tree in self._pages(prefix, delimiter="/"):
      for node in tree.findall(f"{NS}CommonPrefixes/{NS}Prefix"):
        name = (node.text or "")[len(prefix):].strip("/")
        if safe_name(name): out.append(Attrs(filename=name, is_dir=True))
      for node in tree.findall(f"{NS}Contents"):
        key = node.findtext(f"{NS}Key", "")
        if _marker(key): continue
        name = key[len(prefix):]
        if safe_name(name): out.append(_listed(node, name))
    return out

  def walk(self, remote:str) -> list[Attrs]:
    """
    Every object under a prefix, at any depth, `filename` holding the path relative to it.

    One listing for the whole subtree:
    with no delimiter the store returns every key under the prefix,
    so this costs a page per thousand objects rather than a request per folder.
    Folders are not listed, because the names imply them exactly as `find -type f` does.

    A key that cannot become a local path is left out, and said so in the log.
    """
    self._require_connected()
    prefix = _prefix(remote)
    out = []
    for tree in self._pages(prefix):
      for node in tree.findall(f"{NS}Contents"):
        key = node.findtext(f"{NS}Key", "")
        if _marker(key): continue
        rel = key[len(prefix):]
        if not _safe_rel(rel):
          if self.log: self.log.wrn(f"unsafe key skipped {c.GREY}{key}{c.END}")
          continue
        out.append(_listed(node, rel))
    return out

  def rmdir(self, remote:str) -> None:
    """
    Remove every object under a prefix. Missing is not an error: there was nothing to remove.

    An empty `remote` is the bucket root, so it empties the bucket.
    Nothing here guards that: a prefix is a prefix, and the root is the one every key shares.

    Markers go too, which is the one place they matter.
    `get_dir` skips them because their name below the prefix is a folder path,
    and opening one for writing fails; leaving them here would keep an emptied folder visible.
    """
    self._require_connected()
    self._delete_keys(self._keys(_prefix(remote)))

  #--------------------------------------------------------------------------------- Batch transfer

  def put_dir(
    self,
    local:str,
    remote:str,
    *,
    filter:Filter|None = None,
    atomic:bool = True,
    callback:Progress|None = None,
  ) -> None:
    """
    Upload every file recursively. No skip check: `sync_push` transfers only what changed.

    Walks files, so an empty local directory has no counterpart afterwards.
    On an object store it could not have one anyway.
    """
    self._require_connected()
    files = local_index(local)
    if self.log:
      self.log.inf(f"put_dir {c.CYAN}{len(files)}{c.END} files → {c.SKY}{remote}{c.END}")
    for rel, f in files.items():
      if pruned(rel, filter): continue
      self.put(str(f), f"{remote}/{rel}", atomic=atomic, callback=callback, _label=rel)

  def get_dir(
    self,
    remote:str,
    local:str,
    *,
    filter:Filter|None = None,
    callback:Progress|None = None,
  ) -> None:
    """Download every object recursively. No skip check: `sync_pull` transfers what changed."""
    self._require_connected()
    root = Path(local)
    for attr in self.walk(remote):
      rel = attr.filename
      if pruned(rel, filter): continue
      self.get(f"{remote}/{rel}", str(root / rel), callback=callback, _label=rel)

  #------------------------------------------------------------------------------------------- Sync

  def sync_push(
    self,
    local:str,
    remote:str,
    *,
    delete:bool = False,
    dry_run:bool = False,
    filter:Filter|None = None,
    callback:Progress|None = None,
  ) -> list[Action]:
    """
    Push local → remote, skipping unchanged objects.

    Skip strategy: size, then the ETag, which for a single-part upload is the object's own MD5.
    So a same-size edit is caught here, where FTP without MFMT would call it unchanged.
    A multipart object falls back to size alone.

    `delete` is refused when the local source is not a directory,
    so a missing source can never wipe the far end.
    Nothing refuses it for a partial listing, because there is no such thing here:
    a listing that fails raises, and one short of a page carries the token to the next.

    Args:
      delete: Remove objects absent locally, `filter` respected.
      dry_run: Plan actions without executing, the returned list is still complete.

    Returns:
      `("put"|"skip"|"delete", rel_path)` per file.
    """
    self._require_connected()
    root = Path(local)
    local_files = local_index(local)
    remote_idx = self._index_remote(remote, filter=filter)
    actions: list[Action] = []
    for rel, lpath in local_files.items():
      if pruned(rel, filter): continue
      rs = remote_idx.get(rel)
      if rs and _same(rs, lpath, lpath.stat().st_size):
        actions.append(("skip", rel)); continue
      actions.append(("put", rel))
      if not dry_run:
        self.put(str(lpath), f"{remote}/{rel}", callback=callback, _label=rel)
    if delete:
      if not root.is_dir(): # a missing source would make every object look deleted
        if self.log: self.log.wrn("delete skipped: local source is not a directory")
      else:
        gone = [rel for rel in remote_idx if rel not in local_files]
        actions += [("delete", rel) for rel in gone]
        if not dry_run and gone:
          prefix = _prefix(remote)
          self._delete_keys([f"{prefix}{rel}" for rel in gone])
    log_sync(self.log, "sync_push", actions, dry_run)
    return actions

  def sync_pull(
    self,
    remote:str,
    local:str,
    *,
    delete:bool = False,
    dry_run:bool = False,
    filter:Filter|None = None,
    callback:Progress|None = None,
  ) -> list[Action]:
    """
    Pull remote → local, skipping unchanged files.

    Skip strategy: size, then the ETag against the local file's own digest,
    so a local edit that kept the size is seen and fetched again.

    `delete` needs no guard against a partial listing, for the reason `sync_push` gives.

    Args:
      delete: Remove local files absent remotely, `filter` respected.
      dry_run: Plan actions without executing, the returned list is still complete.

    Returns:
      `("get"|"skip"|"delete", rel_path)` per file.
    """
    self._require_connected()
    root = Path(local)
    local_idx = local_index(local) if root.exists() else {}
    remote_idx = self._index_remote(remote, filter=filter)
    actions: list[Action] = []
    for rel, rs in remote_idx.items():
      lpath = root / rel
      if lpath.exists() and _same(rs, lpath, lpath.stat().st_size):
        actions.append(("skip", rel)); continue
      actions.append(("get", rel))
      if not dry_run:
        self.get(f"{remote}/{rel}", str(lpath), preserve_mtime=True,
          callback=callback, _label=rel)
    if delete:
      for rel in local_idx:
        if rel in remote_idx or pruned(rel, filter): continue
        actions.append(("delete", rel))
        if not dry_run: (root / rel).unlink(missing_ok=True)
    log_sync(self.log, "sync_pull", actions, dry_run)
    return actions

  #---------------------------------------------------------------------------------------- Helpers

  def _index_remote(self, remote:str, filter:Filter|None = None) -> dict[str, Attrs]:
    """
    `{rel_path: Attrs}` for everything under a prefix, in one listing.

    No partial flag, unlike the file clients:
    a listing that fails raises rather than coming back short,
    so a caller may delete against this without asking what it did not see.
    """
    return {a.filename: a for a in self.walk(remote) if not pruned(a.filename, filter)}

  def _pages(self, prefix:str, delimiter:str = ""):
    """ListObjectsV2 pages for a prefix, following the continuation token to the end."""
    token = ""
    while True:
      query = {"list-type": 2, "max-keys": PAGE_MAX}
      if prefix: query["prefix"] = prefix
      if delimiter: query["delimiter"] = delimiter
      if token: query["continuation-token"] = token
      tree = ElementTree.fromstring(self._send("GET", query=query).read())
      yield tree
      token = tree.findtext(f"{NS}NextContinuationToken", "")
      if not token: return

  def _keys(self, prefix:str) -> list[str]:
    """Every key under a prefix, markers included: with no delimiter one walk covers the tree."""
    keys = []
    for tree in self._pages(prefix):
      keys += [node.findtext(f"{NS}Key", "") for node in tree.findall(f"{NS}Contents")]
    return keys

  def _delete_keys(self, keys:list[str]) -> None:
    """Delete whole keys, a thousand per request, which is the most one call may carry."""
    for start in range(0, len(keys), PAGE_MAX):
      self._delete(keys[start:start + PAGE_MAX])

  def _delete(self, keys:list[str]) -> None:
    """One DeleteObjects call. S3 authenticates a batch by its digest, so the body is signed."""
    items = "".join(f"<Object><Key>{escape(key)}</Key></Object>" for key in keys)
    body = f"<Delete>{items}</Delete>".encode()
    md5 = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()
    digest = hashlib.sha256(body).hexdigest()
    answer = self._send("POST", query={"delete": ""}, body=body, length=len(body),
      payload=digest, extra={"content-md5": md5}).read()
    _kept(_confirm(answer, "DeleteResult", f"delete of {len(keys)} keys"), "delete")
