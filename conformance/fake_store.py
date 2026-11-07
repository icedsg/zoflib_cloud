#!/usr/bin/env python3
"""Reference driver: an in-memory object store that follows spec/contract.json.

Speaks the driver protocol on stdio (see conformance/README.md): one JSON request per line in, one JSON response per
line out. Stdlib only. It exists so the conformance cases are themselves tested; language packages ship their own
driver that wraps the real package over a fake or disposable S3 endpoint.
"""
import base64, hashlib, json, sys, unicodedata

ROOT = "test-bucket"
CAPS = ["list", "stat", "search", "upload", "download", "range_download", "copy", "move", "rename", "delete"]


class Fail(Exception):
    def __init__(self, code, message=""):
        self.code, self.message = code, message


class Store:
    def __init__(self):
        self.objs = {}  # key -> {"data": bytes, "modified": str}

    # --- helpers -------------------------------------------------------------------------------------------------
    @staticmethod
    def order(keys):
        return sorted(keys, key=lambda k: k.encode("utf-8"))

    def root(self, args):
        if args.get("root") != ROOT: raise Fail("not_found", "unknown root")

    def item(self, key):
        o = self.objs[key]
        return {"root": ROOT, "path": key, "name": key.rstrip("/").rsplit("/", 1)[-1], "kind": "file",
                "size": len(o["data"]), "modified": o["modified"], "etag": hashlib.md5(o["data"]).hexdigest()}

    @staticmethod
    def folder(prefix):
        return {"root": ROOT, "path": prefix, "name": prefix.rstrip("/").rsplit("/", 1)[-1], "kind": "folder",
                "size": None, "modified": None, "etag": None}

    def children(self, path):
        prefix = path if path == "" or path.endswith("/") else path + "/"
        files, folders = [], set()
        for k in self.objs:
            if not k.startswith(prefix) or k == prefix: continue
            rest = k[len(prefix):]
            if "/" in rest: folders.add(prefix + rest.split("/", 1)[0] + "/")
            else: files.append(k)
        rows = [(k, self.item(k)) for k in files] + [(f, self.folder(f)) for f in folders]
        return [r for _, r in sorted(rows, key=lambda r: r[0].encode("utf-8"))]

    def is_folder(self, path):
        prefix = path if path.endswith("/") else path + "/"
        return any(k.startswith(prefix) for k in self.objs)

    def free_name(self, key):
        if key not in self.objs: return key
        folder, _, name = key.rpartition("/")
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem: stem, ext, dot = name, "", ""
        n = 1
        while True:
            cand = (folder + "/" if folder else "") + f"{stem} ({n}){dot}{ext}"
            if cand not in self.objs: return cand
            n += 1

    def target(self, key, overwrite):
        if key in self.objs:
            if overwrite == "replace": return key
            if overwrite == "rename": return self.free_name(key)
            raise Fail("conflict", "target exists")
        return key

    # --- operations ----------------------------------------------------------------------------------------------
    def op_reset(self, a, o):
        self.objs = {}
        for s in a.get("seed", []):
            data = base64.b64decode(s["content_b64"]) if "content_b64" in s else s.get("content", "").encode("utf-8")
            self.objs[s["path"]] = {"data": data, "modified": s.get("modified", "2026-01-01T00:00:00Z")}
        return {"count": len(self.objs)}

    def op_dump(self, a, o):
        return self.order(self.objs)

    def op_testConnection(self, a, o):
        return {"capabilities": CAPS}

    def op_listRoots(self, a, o):
        return [{"root": ROOT, "path": "", "name": ROOT, "kind": "folder", "size": None, "modified": None, "etag": None}]

    def op_list(self, a, o):
        self.root(a)
        rows = self.children(a.get("path", ""))
        size = max(1, int(o.get("page_size", 1000)))
        start = 0
        if a.get("token"):
            try: start = int(base64.urlsafe_b64decode(a["token"].encode()).decode().split(":", 1)[1])
            except Exception: raise Fail("invalid_config", "bad continuation token")
        page = rows[start:start + size]
        nxt = start + size
        token = base64.urlsafe_b64encode(f"o:{nxt}".encode()).decode() if nxt < len(rows) else None
        return {"items": page, "next_token": token}

    def op_stat(self, a, o):
        self.root(a)
        p = a["path"]
        if p in self.objs: return self.item(p)
        if self.is_folder(p): return self.folder(p if p.endswith("/") else p + "/")
        raise Fail("not_found", "no such item")

    def op_search(self, a, o):
        self.root(a)
        fold = lambda s: unicodedata.normalize("NFC", s).casefold()
        q, under = fold(a["query"]), a.get("under", "")
        limit = int(o.get("limit", 1000))
        cancel = o.get("cancel")
        after = cancel.get("after_items") if isinstance(cancel, dict) else None
        out = []
        for k in self.order(self.objs):
            if not k.startswith(under) or k.endswith("/"): continue
            if q in fold(k.rsplit("/", 1)[-1]):
                if after is not None and len(out) >= after: raise Fail("cancelled", f"after {len(out)} items")
                if len(out) >= limit: return {"items": out, "truncated": True}
                out.append(self.item(k))
        return {"items": out, "truncated": False}

    def op_download(self, a, o):
        self.root(a)
        if a["path"] not in self.objs: raise Fail("not_found", "no such item")
        data = self.objs[a["path"]]["data"]
        if "max_bytes" in o and len(data) > int(o["max_bytes"]): raise Fail("quota", "larger than max_bytes")
        return {"content_b64": base64.b64encode(data).decode(), "size": len(data)}

    def op_upload(self, a, o):
        self.root(a)
        key = self.target(a["path"], o.get("overwrite", "fail"))
        data = base64.b64decode(a["content_b64"]) if "content_b64" in a else a.get("content", "").encode("utf-8")
        self.objs[key] = {"data": data, "modified": "2026-06-01T00:00:00Z"}
        return {"operation": "upload", "state": "completed", "items": [self.item(key)]}

    def op_copy(self, a, o):
        self.root(a)
        if a["path"] not in self.objs: raise Fail("not_found", "no such item")
        key = self.target(a["to"], o.get("overwrite", "fail"))
        self.objs[key] = dict(self.objs[a["path"]])
        return {"operation": "copy", "state": "completed", "items": [self.item(key)]}

    def op_move(self, a, o):
        self.root(a)
        if not o.get("destructive"): raise Fail("confirmation_required", "move deletes the source")
        r = self.op_copy(a, o)
        del self.objs[a["path"]]
        return {"operation": "move", "state": "source_deleted", "items": r["items"]}

    def op_delete(self, a, o):
        self.root(a)
        if not o.get("destructive"): raise Fail("confirmation_required", "delete needs the destructive option")
        p = a["path"]
        if p in self.objs and not p.endswith("/"):
            del self.objs[p]
            return {"operation": "delete", "state": "completed", "items": [{"root": ROOT, "path": p}]}
        prefix = p if p.endswith("/") else p + "/"
        keys = [k for k in self.objs if k.startswith(prefix)]
        if not keys: raise Fail("not_found", "no such item")
        if not o.get("recursive") and any(k != prefix for k in keys): raise Fail("conflict", "folder has contents")
        for k in keys: del self.objs[k]
        return {"operation": "delete", "state": "completed", "items": [{"root": ROOT, "path": k} for k in self.order(keys)]}


def main():
    store = Store()
    for line in sys.stdin:
        if not line.strip(): continue
        req = json.loads(line)
        opts = req.get("options") or {}
        try:
            fn = getattr(store, "op_" + req["op"], None)
            if fn is None: raise Fail("unsupported", "unknown operation")
            if opts.get("cancel") == "before" and req["op"] not in ("reset", "dump"): raise Fail("cancelled", "cancelled before start")
            resp = {"id": req.get("id"), "ok": True, "result": fn(req.get("args") or {}, opts)}
        except Fail as e:
            resp = {"id": req.get("id"), "ok": False, "error": {"code": e.code, "message": e.message}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
