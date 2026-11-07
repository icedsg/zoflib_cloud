"""Generic S3-compatible backend: SigV4 over urllib, no dependencies. Credentials come from a host callback."""
import datetime, hashlib, hmac, http.client, ssl, urllib.parse, xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Optional
from .errors import CloudError, CancelToken

MULTIPART_THRESHOLD = 8 * 1024 * 1024
PART_SIZE = 8 * 1024 * 1024
_EMPTY = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class Credential:
    access_key_id: str
    secret_access_key: str
    session_token: Optional[str] = None

    def __repr__(self): return "Credential(<redacted>)"


@dataclass(frozen=True)
class S3Config:
    """Never holds secrets: credential_ref names a secret the host resolves through the credential callback."""
    endpoint: str
    region: str
    credential_ref: str
    root: str
    addressing: str = "path"            # "path" or "virtual"
    signing_region: Optional[str] = None
    session_token_ref: Optional[str] = None
    allow_insecure_http: bool = False   # loopback development endpoints only
    provider: str = "s3"

    def validate(self):
        u = urllib.parse.urlsplit(self.endpoint)
        loopback = u.hostname in ("localhost", "127.0.0.1", "::1")
        if u.scheme != "https" and not (self.allow_insecure_http and loopback and u.scheme == "http"):
            raise CloudError("invalid_config", "HTTPS is required; HTTP is allowed only for an explicit loopback development endpoint.")
        if not self.region or not self.credential_ref or not self.root:
            raise CloudError("invalid_config", "Region, credential reference and root are required.")


_PROVIDER_CODES = dict(InvalidAccessKeyId="authentication", SignatureDoesNotMatch="authentication", ExpiredToken="authentication",
                       AccessDenied="permission", NoSuchKey="not_found", NoSuchBucket="not_found", NotFound="not_found",
                       SlowDown="throttled", Throttling="throttled", QuotaExceeded="quota", EntityTooLarge="quota")


def _q(s, safe="-_.~"): return urllib.parse.quote(s, safe=safe)


def _hmac(key, msg): return hmac.new(key, msg.encode(), hashlib.sha256).digest()


class S3Backend:
    def __init__(self, config, credentials: Callable, cancel: Optional[CancelToken] = None, timeout=30,
                 multipart_threshold=MULTIPART_THRESHOLD, part_size=PART_SIZE):
        config.validate()
        self.c, self._creds, self.cancel, self.timeout = config, credentials, cancel, timeout
        self.threshold, self.part_size = multipart_threshold, part_size
        u = urllib.parse.urlsplit(config.endpoint)
        self._scheme, self._port = u.scheme, u.port
        self._host = u.hostname
        self._base = u.path.rstrip("/")

    # --- signing and transport ---------------------------------------------------------------------------------------
    def _request(self, method, key="", query=None, body=b"", headers=None):
        if self.cancel: self.cancel.check()
        cred = self._creds(self.c.credential_ref, self.c.session_token_ref)
        if self.c.addressing == "virtual":
            host, path = f"{self.c.root}.{self._host}", f"{self._base}/{_q(key, '/-_.~')}"
        else:
            host, path = self._host, f"{self._base}/{_q(self.c.root)}" + (f"/{_q(key, '/-_.~')}" if key else "")
        netloc = host + (f":{self._port}" if self._port else "")
        query = query or {}
        canon_q = "&".join(f"{_q(k)}={_q(str(v))}" for k, v in sorted(query.items()))
        now = datetime.datetime.now(datetime.timezone.utc)
        amz, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        h = {"host": netloc, "x-amz-date": amz, "x-amz-content-sha256": hashlib.sha256(body).hexdigest() if body else _EMPTY}
        if cred.session_token: h["x-amz-security-token"] = cred.session_token
        for k, v in (headers or {}).items(): h[k.lower()] = v
        names = sorted(h)
        canon = "\n".join([method, path or "/", canon_q, "".join(f"{n}:{str(h[n]).strip()}\n" for n in names),
                           ";".join(names), h["x-amz-content-sha256"]])
        region = self.c.signing_region or self.c.region
        scope = f"{day}/{region}/s3/aws4_request"
        sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canon.encode()).hexdigest()])
        k = _hmac(_hmac(_hmac(_hmac(("AWS4" + cred.secret_access_key).encode(), day), region), "s3"), "aws4_request")
        sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
        h["authorization"] = f"AWS4-HMAC-SHA256 Credential={cred.access_key_id}/{scope}, SignedHeaders={';'.join(names)}, Signature={sig}"
        conn_cls = http.client.HTTPSConnection if self._scheme == "https" else http.client.HTTPConnection
        kw = {"context": ssl.create_default_context()} if self._scheme == "https" else {}
        conn = conn_cls(host, self._port, timeout=self.timeout, **kw)
        try:
            conn.request(method, (path or "/") + ("?" + canon_q if canon_q else ""), body=body or None,
                         headers={k: v for k, v in h.items() if k != "host"})
            r = conn.getresponse()
            data = r.read()
            hdrs = {k.lower(): v for k, v in r.getheaders()}
        except (OSError, http.client.HTTPException) as e:
            raise CloudError("network", f"connection failed ({type(e).__name__})") from None
        finally:
            conn.close()
        if r.status >= 300: raise self._error(r.status, data, hdrs, method)
        return r.status, data, hdrs

    @staticmethod
    def _error(status, body, hdrs, method):
        pcode = None
        try: pcode = ET.fromstring(body).findtext("Code")
        except ET.ParseError: pass
        rid = hdrs.get("x-amz-request-id")
        code = _PROVIDER_CODES.get(pcode)
        if not code:
            code = {401: "authentication", 403: "permission", 404: "not_found", 429: "throttled", 503: "throttled",
                    507: "quota"}.get(status, "provider_error")
        retry = None
        if "retry-after" in hdrs:
            try: retry = int(float(hdrs["retry-after"]) * 1000)
            except ValueError: pass
        return CloudError(code, f"provider answered HTTP {status}" + (f" {pcode}" if pcode else ""), pcode, rid, retry)

    # --- backend interface -------------------------------------------------------------------------------------------
    def list_page(self, prefix, delimiter, token, max_keys):
        q = {"list-type": "2", "max-keys": str(max_keys), "prefix": prefix}
        if delimiter: q["delimiter"] = delimiter
        if token: q["continuation-token"] = token
        _, body, _ = self._request("GET", "", q)
        root = ET.fromstring(body)
        ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
        objs = [{"key": c.findtext(ns + "Key"), "size": int(c.findtext(ns + "Size") or 0),
                 "modified": c.findtext(ns + "LastModified"), "etag": (c.findtext(ns + "ETag") or "").strip('"')}
                for c in root.findall(ns + "Contents")]
        prefixes = [p.findtext(ns + "Prefix") for p in root.findall(ns + "CommonPrefixes")]
        truncated = root.findtext(ns + "IsTruncated") == "true"
        return {"objects": objs, "prefixes": prefixes, "next_token": root.findtext(ns + "NextContinuationToken") if truncated else None}

    def head(self, key):
        try: _, _, h = self._request("HEAD", key)
        except CloudError as e:
            if e.code == "not_found": return None
            raise
        return {"key": key, "size": int(h.get("content-length", 0)), "modified": h.get("last-modified"), "etag": h.get("etag", "").strip('"')}

    def get(self, key): return self._request("GET", key)[1]

    def put(self, key, data):
        if len(data) > self.threshold: self._multipart(key, data)
        else: self._request("PUT", key, body=data)
        return self.head(key)

    def _multipart(self, key, data):
        _, body, _ = self._request("POST", key, {"uploads": ""})
        root = ET.fromstring(body)
        uid = next(e.text for e in root.iter() if e.tag.endswith("UploadId"))
        try:
            etags = []
            for n, off in enumerate(range(0, len(data), self.part_size), 1):
                _, _, h = self._request("PUT", key, {"partNumber": str(n), "uploadId": uid}, data[off:off + self.part_size])
                etags.append(h["etag"])
            xml = "<CompleteMultipartUpload>" + "".join(
                f"<Part><PartNumber>{i}</PartNumber><ETag>{e}</ETag></Part>" for i, e in enumerate(etags, 1)) + "</CompleteMultipartUpload>"
            self._request("POST", key, {"uploadId": uid}, xml.encode())
        except BaseException:
            try: self._request("DELETE", key, {"uploadId": uid})
            except CloudError: pass
            raise

    def copy(self, src, dst):
        self._request("PUT", dst, headers={"x-amz-copy-source": f"/{_q(self.c.root)}/{_q(src, '/-_.~')}"})

    def delete(self, key): self._request("DELETE", key)
