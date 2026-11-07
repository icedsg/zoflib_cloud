"""Conformance driver (conformance/README.md): python -m zoflib_cloud.driver

Memory backend by default. With ZOFLIB_S3_ENDPOINT, ZOFLIB_S3_ACCESS and ZOFLIB_S3_SECRET set it talks to that
disposable S3-compatible endpoint (bucket test-bucket, emptied by `reset`); never point it at real data.
"""
import base64, json, os, sys
from .core import CloudStore, MemoryBackend, utf8_key
from .errors import CloudError, CancelToken
from .s3 import S3Backend, S3Config, Credential

ROOT = "test-bucket"


def make_store():
    ep = os.environ.get("ZOFLIB_S3_ENDPOINT")
    if not ep: return CloudStore(MemoryBackend(), ROOT)
    cfg = S3Config(endpoint=ep, region="us-east-1", credential_ref="env", root=ROOT, allow_insecure_http=True)
    cred = Credential(os.environ["ZOFLIB_S3_ACCESS"], os.environ["ZOFLIB_S3_SECRET"])
    return CloudStore(S3Backend(cfg, lambda ref, tok: cred), ROOT)


def _data(a): return base64.b64decode(a["content_b64"]) if "content_b64" in a else a.get("content", "").encode("utf-8")


def handle(store, req):
    op, a, o = req["op"], req.get("args") or {}, dict(req.get("options") or {})
    root, b = a.get("root"), store.backend
    on_result = None
    c = o.get("cancel")
    if c == "before" and op not in ("reset", "dump"):
        raise CloudError("cancelled", "cancelled before start")
    if isinstance(c, dict):
        tok = CancelToken(); o["cancel"] = tok
        on_result = lambda n: tok.cancel() if n >= c.get("after_items", 1 << 60) else None
    elif c is not None: o.pop("cancel")
    if op == "reset":
        for k in [x["key"] for x in store._all_keys("")]: b.delete(k)
        for s in a.get("seed", []): b.put(s["path"], _data({"content_b64": s["content_b64"]} if "content_b64" in s else {"content": s.get("content", "")}))
        return {"count": len(a.get("seed", []))}
    if op == "dump": return sorted((x["key"] for x in store._all_keys("")), key=utf8_key)
    if op == "testConnection": return store.test_connection(o)
    if op == "listRoots": return store.list_roots(o)
    if op == "list": return store.list(a.get("path", ""), a.get("token"), o, root)
    if op == "stat": return store.stat(a["path"], o, root)
    if op == "search": return store.search(a["query"], a.get("under", ""), o, root, on_result)
    if op == "download":
        r = store.download(a["path"], o, root)
        return {"content_b64": base64.b64encode(r["content"]).decode(), "size": r["size"]}
    if op == "upload": return store.upload(a["path"], _data(a), o, root)
    if op == "copy": return store.copy(a["path"], a["to"], o, root)
    if op == "move": return store.move(a["path"], a["to"], o, root)
    if op == "delete": return store.delete(a["path"], o, root)
    raise CloudError("unsupported", "unknown operation")


def main():
    store = make_store()
    for line in sys.stdin:
        if not line.strip(): continue
        req = json.loads(line)
        try: resp = {"id": req.get("id"), "ok": True, "result": handle(store, req)}
        except CloudError as e: resp = {"id": req.get("id"), "ok": False, "error": e.to_dict()}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
