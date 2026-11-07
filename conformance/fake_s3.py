#!/usr/bin/env python3
"""Disposable fake S3 server for package tests: python conformance/fake_s3.py [PORT]  (0 = pick one; prints the port).

Path-style only, one in-memory bucket set, verifies the SigV4 signature of every request (so signing bugs in a package
fail here), supports ListObjectsV2, HEAD, GET, PUT, copy, DELETE and multipart upload. Stdlib only, test use only.
"""
import hashlib, hmac, sys, threading, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

ACCESS, SECRET, REGION = "zoflibtest", "zoflibtestsecret", "us-east-1"
BUCKETS, UPLOADS, LOCK = {}, {}, threading.Lock()


def _h(k, m): return hmac.new(k, m.encode(), hashlib.sha256).digest()


def _q(s, safe="-_.~"): return urllib.parse.quote(s, safe=safe)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.send_header("x-amz-request-id", "REQ" + uuid.uuid4().hex[:8])
        if "Content-Length" not in (headers or {}): self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def _err(self, status, code):
        self._send(status, f"<Error><Code>{code}</Code><Message>x</Message></Error>".encode(), {"Content-Type": "application/xml"})

    def _verify(self, body):
        auth = self.headers.get("Authorization", "")
        try:
            parts = dict(p.strip().split("=", 1) for p in auth[len("AWS4-HMAC-SHA256 "):].split(","))
            access, day, region, _, _ = parts["Credential"].split("/")
            signed = parts["SignedHeaders"].split(";")
        except Exception: return "AccessDenied"
        if access != ACCESS: return "InvalidAccessKeyId"
        if self.headers.get("x-amz-content-sha256") != hashlib.sha256(body).hexdigest(): return "XAmzContentSHA256Mismatch"
        raw_path, _, raw_q = self.path.partition("?")
        pairs = [p.split("=", 1) if "=" in p else [p, ""] for p in raw_q.split("&") if p]
        cq = "&".join(f"{_q(urllib.parse.unquote(k))}={_q(urllib.parse.unquote(v))}" for k, v in sorted(pairs, key=lambda p: (urllib.parse.unquote(p[0]), urllib.parse.unquote(p[1]))))
        ch = "".join(f"{n}:{self.headers.get(n).strip()}\n" for n in signed)
        canon = "\n".join([self.command, raw_path, cq, ch, ";".join(signed), self.headers["x-amz-content-sha256"]])
        scope = f"{day}/{region}/s3/aws4_request"
        sts = "\n".join(["AWS4-HMAC-SHA256", self.headers["x-amz-date"], scope, hashlib.sha256(canon.encode()).hexdigest()])
        k = _h(_h(_h(_h(("AWS4" + SECRET).encode(), day), region), "s3"), "aws4_request")
        return None if hmac.new(k, sts.encode(), hashlib.sha256).hexdigest() == parts["Signature"] else "SignatureDoesNotMatch"

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        bad = self._verify(body)
        if bad: return self._err(403, bad)
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        segs = urllib.parse.unquote(u.path).lstrip("/").split("/", 1)
        bucket, key = segs[0], (segs[1] if len(segs) > 1 else "")
        with LOCK:
            if bucket == "throttle": return self._send(503, b"<Error><Code>SlowDown</Code></Error>", {"Retry-After": "2"})
            b = BUCKETS.setdefault(bucket, {})
            m = self.command
            if not key and m == "GET": return self._list(b, q)
            if m == "HEAD":
                if key not in b: return self._send(404)
                return self._send(200, headers={"Content-Length": str(len(b[key][0])), "ETag": '"%s"' % b[key][1], "Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT"})
            if m == "GET":
                if key not in b: return self._err(404, "NoSuchKey")
                return self._send(200, b[key][0])
            if m == "DELETE":
                if "uploadId" in q: UPLOADS.pop(q["uploadId"], None)
                else: b.pop(key, None)
                return self._send(204)
            if m == "POST" and "uploads" in q:
                uid = uuid.uuid4().hex; UPLOADS[uid] = {}
                return self._send(200, f"<InitiateMultipartUploadResult><UploadId>{uid}</UploadId></InitiateMultipartUploadResult>".encode())
            if m == "POST" and "uploadId" in q:
                parts = UPLOADS.pop(q["uploadId"])
                data = b"".join(parts[i] for i in sorted(parts))
                b[key] = (data, hashlib.md5(data).hexdigest() + "-%d" % len(parts))
                return self._send(200, b"<CompleteMultipartUploadResult/>")
            if m == "PUT" and "partNumber" in q:
                UPLOADS[q["uploadId"]][int(q["partNumber"])] = body
                return self._send(200, headers={"ETag": '"%s"' % hashlib.md5(body).hexdigest()})
            if m == "PUT":
                src = self.headers.get("x-amz-copy-source")
                if src:
                    sb, _, sk = urllib.parse.unquote(src).lstrip("/").partition("/")
                    if sk not in BUCKETS.get(sb, {}): return self._err(404, "NoSuchKey")
                    b[key] = BUCKETS[sb][sk]
                    return self._send(200, b"<CopyObjectResult/>")
                b[key] = (body, hashlib.md5(body).hexdigest())
                return self._send(200, headers={"ETag": '"%s"' % b[key][1]})
        self._err(400, "InvalidRequest")

    def _list(self, b, q):
        prefix, delim, size = q.get("prefix", ""), q.get("delimiter"), int(q.get("max-keys", 1000))
        rows, seen = [], set()
        for k in b:
            if not k.startswith(prefix): continue
            rest = k[len(prefix):]
            if delim and delim in rest:
                p = prefix + rest.split(delim, 1)[0] + delim
                if p not in seen: seen.add(p); rows.append((p, False))
            else: rows.append((k, True))
        rows.sort(key=lambda r: r[0].encode("utf-8"))
        start = int(q["continuation-token"]) if q.get("continuation-token") else 0
        page = rows[start:start + size]
        more = start + size < len(rows)
        x = ["<ListBucketResult xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">", f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>"]
        if more: x.append(f"<NextContinuationToken>{start + size}</NextContinuationToken>")
        for k, is_obj in page:
            if is_obj: x.append(f"<Contents><Key>{escape(k)}</Key><Size>{len(b[k][0])}</Size><ETag>&quot;{b[k][1]}&quot;</ETag><LastModified>2026-06-01T00:00:00.000Z</LastModified></Contents>")
            else: x.append(f"<CommonPrefixes><Prefix>{escape(k)}</Prefix></CommonPrefixes>")
        x.append("</ListBucketResult>")
        self._send(200, "".join(x).encode(), {"Content-Type": "application/xml"})

    do_GET = do_PUT = do_POST = do_DELETE = do_HEAD = _handle


def serve(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    srv = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    print(srv.server_address[1], flush=True)
    threading.Event().wait()
