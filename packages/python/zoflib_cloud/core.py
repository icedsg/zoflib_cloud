"""Contract 0.1.0 over a small backend interface. Backends: MemoryBackend (tests) and S3Backend (generic S3).

Backend methods (sync, keys are full object keys):
  list_page(prefix, delimiter, token, max_keys) -> {"objects": [{key,size,modified,etag}], "prefixes": [..], "next_token"}
  head(key) -> object dict or None;  get(key) -> bytes;  put(key, data) -> object dict;  copy(src, dst);  delete(key)
Every backend call may raise CloudError; cancellation is a CancelToken in options["cancel"].
"""
import base64, hashlib, unicodedata
from .errors import CloudError, CancelToken

CAPABILITIES = ["list", "stat", "search", "upload", "multipart_upload", "download", "copy", "move", "rename", "delete"]


def utf8_key(s): return s.encode("utf-8")


def _fold(s): return unicodedata.normalize("NFC", s).casefold()


def _name(path): return path.rstrip("/").rsplit("/", 1)[-1]


def _dir(path): return path if path == "" or path.endswith("/") else path + "/"


def _receipt(op, state, items): return {"operation": op, "state": state, "items": items}


class CloudStore:
    """The contract operations for one root (bucket)."""

    def __init__(self, backend, root):
        self.backend, self.root = backend, root

    # --- helpers --------------------------------------------------------------------------------------------------
    def _item(self, o):
        return {"root": self.root, "path": o["key"], "name": _name(o["key"]), "kind": "file", "size": o["size"],
                "modified": o["modified"], "etag": o["etag"]}

    def _folder(self, prefix):
        return {"root": self.root, "path": prefix, "name": _name(prefix), "kind": "folder", "size": None,
                "modified": None, "etag": None}

    def _begin(self, root, options):
        cancel = options.get("cancel")
        cancel = cancel if isinstance(cancel, CancelToken) else None
        if cancel: cancel.check()
        if root is not None and root != self.root: raise CloudError("not_found", "unknown root")
        return cancel

    def _free_name(self, key):
        folder, _, name = key.rpartition("/")
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem: stem, ext, dot = name, "", ""
        n = 1
        while True:
            cand = (folder + "/" if folder else "") + f"{stem} ({n}){dot}{ext}"
            if self.backend.head(cand) is None: return cand
            n += 1

    def _target(self, key, overwrite):
        if overwrite not in ("fail", "replace", "rename"): raise CloudError("invalid_config", "unknown overwrite mode")
        if self.backend.head(key) is None: return key
        if overwrite == "replace": return key
        if overwrite == "rename": return self._free_name(key)
        raise CloudError("conflict", "target exists")

    def _all_keys(self, prefix):
        token = None
        while True:
            page = self.backend.list_page(prefix, None, token, 1000)
            yield from page["objects"]
            token = page["next_token"]
            if not token: return

    # --- operations (options: page_size, limit, max_bytes, overwrite, destructive, recursive, cancel) -----------------
    def test_connection(self, options=None):
        self.backend.list_page("", "/", None, 1)
        return {"capabilities": list(CAPABILITIES)}

    def list_roots(self, options=None):
        return [{"root": self.root, "path": "", "name": self.root, "kind": "folder", "size": None, "modified": None, "etag": None}]

    def list(self, path="", token=None, options=None, root=None):
        options = options or {}
        self._begin(root, options)
        prefix = _dir(path)
        page = self.backend.list_page(prefix, "/", token, max(1, int(options.get("page_size", 1000))))
        rows = [(o["key"], self._item(o)) for o in page["objects"] if o["key"] != prefix]
        rows += [(p, self._folder(p)) for p in page["prefixes"] if p != prefix]
        rows.sort(key=lambda r: utf8_key(r[0]))
        return {"items": [r for _, r in rows], "next_token": page["next_token"]}

    def stat(self, path, options=None, root=None):
        self._begin(root, options or {})
        o = None if path.endswith("/") else self.backend.head(path)
        if o: return self._item(o)
        prefix = _dir(path)
        if prefix and self.backend.list_page(prefix, None, None, 1)["objects"]: return self._folder(prefix)
        raise CloudError("not_found", "no such item")

    def search(self, query, under="", options=None, root=None, on_result=None):
        options = options or {}
        cancel = self._begin(root, options)
        q, limit, out = _fold(query), int(options.get("limit", 1000)), []
        for o in self._all_keys(under):
            if o["key"].endswith("/") or q not in _fold(_name(o["key"])): continue
            if cancel: cancel.check()
            if len(out) >= limit: return {"items": out, "truncated": True}
            out.append(self._item(o))
            if on_result: on_result(len(out))
        return {"items": out, "truncated": False}

    def download(self, path, options=None, root=None):
        options = options or {}
        self._begin(root, options)
        o = self.backend.head(path)
        if o is None: raise CloudError("not_found", "no such item")
        if "max_bytes" in options and o["size"] > int(options["max_bytes"]): raise CloudError("quota", "larger than max_bytes")
        data = self.backend.get(path)
        return {"content": data, "size": len(data)}

    def upload(self, path, data, options=None, root=None):
        options = options or {}
        self._begin(root, options)
        key = self._target(path, options.get("overwrite", "fail"))
        return _receipt("upload", "completed", [self._item(self.backend.put(key, bytes(data)))])

    def copy(self, path, to, options=None, root=None):
        options = options or {}
        self._begin(root, options)
        if self.backend.head(path) is None: raise CloudError("not_found", "no such item")
        key = self._target(to, options.get("overwrite", "fail"))
        self.backend.copy(path, key)
        return _receipt("copy", "completed", [self._item(self.backend.head(key))])

    def move(self, path, to, options=None, root=None):
        options = options or {}
        self._begin(root, options)
        if not options.get("destructive"): raise CloudError("confirmation_required", "move deletes the source")
        r = self.copy(path, to, options, root)
        if r["items"][0]["path"] == path: return _receipt("move", "nothing_to_do", r["items"])
        try: self.backend.delete(path)
        except CloudError: return _receipt("move", "copied", r["items"])
        return _receipt("move", "source_deleted", r["items"])

    def delete(self, path, options=None, root=None):
        options = options or {}
        cancel = self._begin(root, options)
        if not options.get("destructive"): raise CloudError("confirmation_required", "delete needs the destructive option")
        if not path.endswith("/") and self.backend.head(path):
            self.backend.delete(path)
            return _receipt("delete", "completed", [{"root": self.root, "path": path}])
        prefix = _dir(path)
        keys = sorted((o["key"] for o in self._all_keys(prefix)), key=utf8_key)
        if not keys: raise CloudError("not_found", "no such item")
        if not options.get("recursive") and any(k != prefix for k in keys): raise CloudError("conflict", "folder has contents")
        done = []
        for k in keys:
            if cancel and cancel.cancelled: return _receipt("delete", "partial", done)
            self.backend.delete(k)
            done.append({"root": self.root, "path": k})
        return _receipt("delete", "completed", done)


class MemoryBackend:
    """In-memory object store with S3 listing behaviour; used by tests and the conformance driver."""

    def __init__(self): self.objs = {}

    def _obj(self, key):
        data, modified = self.objs[key]
        return {"key": key, "size": len(data), "modified": modified, "etag": hashlib.md5(data).hexdigest()}

    def seed(self, key, data, modified="2026-01-01T00:00:00Z"): self.objs[key] = (bytes(data), modified)

    def list_page(self, prefix, delimiter, token, max_keys):
        rows, seen = [], set()
        for k in self.objs:
            if not k.startswith(prefix): continue
            rest = k[len(prefix):]
            if delimiter and delimiter in rest:
                p = prefix + rest.split(delimiter, 1)[0] + delimiter
                if p not in seen: seen.add(p); rows.append((p, False))
            else: rows.append((k, True))
        rows.sort(key=lambda r: utf8_key(r[0]))
        start = 0
        if token:
            try: start = int(base64.urlsafe_b64decode(token.encode()).decode().split(":", 1)[1])
            except Exception: raise CloudError("invalid_config", "bad continuation token")
        page, nxt = rows[start:start + max_keys], start + max_keys
        return {"objects": [self._obj(k) for k, is_obj in page if is_obj], "prefixes": [k for k, is_obj in page if not is_obj],
                "next_token": base64.urlsafe_b64encode(f"o:{nxt}".encode()).decode() if nxt < len(rows) else None}

    def head(self, key): return self._obj(key) if key in self.objs else None
    def get(self, key): return self.objs[key][0]
    def put(self, key, data): self.seed(key, data, "2026-06-01T00:00:00Z"); return self._obj(key)
    def copy(self, src, dst): self.objs[dst] = self.objs[src]
    def delete(self, key): self.objs.pop(key, None)
