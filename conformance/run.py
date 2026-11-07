#!/usr/bin/env python3
"""zoflib_cloud conformance test. Usage: python conformance/run.py DRIVER_CMD [ARGS...]

Checks spec/*.json and fixtures/, then runs every conformance/cases/*.json against a driver (see conformance/README.md).
Stdlib only. Exit 0 = all passed.
"""
import base64, glob, json, os, re, subprocess, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
fails, passed = [], 0


def check(cond, name, detail=""):
    global passed
    if cond: passed += 1; print("ok   ", name)
    else: fails.append(name); print("FAIL ", name, detail)


def load(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f: return json.load(f)


# --- spec and repo checks ---------------------------------------------------------------------------------------------
def check_spec():
    contract, errors, providers = load("spec/contract.json"), load("spec/errors.json"), load("spec/providers.json")
    ver = contract["contract_version"]
    check(re.fullmatch(r"\d+\.\d+\.\d+", ver) is not None, "spec: contract_version is semver")
    check(errors["contract_version"] == ver and providers["contract_version"] == ver, "spec: files share contract_version")
    codes = [e["code"] for e in errors["errors"]]
    check(len(codes) == len(set(codes)), "spec: error codes unique")
    for op, d in contract["operations"].items():
        unknown = [c for c in d.get("errors", []) if c not in codes]
        check(not unknown, f"spec: {op} errors are known codes", unknown)
    caps = set(contract["capabilities"])
    for k in ("list", "stat", "search", "upload", "download", "copy", "move", "delete"):
        check(k in caps, f"spec: capability {k}")

    classes, ways = set(providers["classifications"]), set(providers["verification"])
    rows = providers["providers"]
    ids = [p["id"] for p in rows]
    check(len(rows) == 30, "providers: 30 entries", len(rows))
    check(len(ids) == len(set(ids)), "providers: ids unique")
    need = ["id", "name", "protocol", "classification", "self_hosted", "endpoint_template", "region", "addressing",
            "auth", "caveats", "doc_url", "verified_at", "verification"]
    for p in rows:
        pid = p.get("id", "?")
        missing = [k for k in need if k not in p]
        check(not missing, f"providers: {pid} has all fields", missing)
        check(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", pid) is not None, f"providers: {pid} id is kebab-case")
        check(p.get("classification") in classes, f"providers: {pid} classification known")
        check(p.get("verification") in ways, f"providers: {pid} verification known")
        check(str(p.get("doc_url", "")).startswith("https://"), f"providers: {pid} doc_url is https")
        try: ok = date.fromisoformat(p["verified_at"]) <= date.today()
        except Exception: ok = False
        check(ok, f"providers: {pid} verified_at is a past date")
        proto, cls = p.get("protocol"), p.get("classification")
        consistent = (proto == "s3" and cls in ("tested", "compatible_by_protocol")) or \
                     (proto == "native" and cls in ("tested", "native_planned")) or (proto == "none" and cls == "unsupported")
        check(consistent, f"providers: {pid} protocol matches classification", f"{proto}/{cls}")
        if proto == "s3":
            check(p.get("addressing") in ("virtual", "path", "both", "unknown"), f"providers: {pid} addressing known")
            t = p.get("endpoint_template")
            check(p.get("self_hosted") == (t is None), f"providers: {pid} endpoint given unless self-hosted")
            check(t is None or t.startswith("https://"), f"providers: {pid} preset endpoint is https")


SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"(?i)(secret_access_key|secret|password|token)\"\s*:\s*\"[^\"<]{8,}\"", "secret value in JSON"),
    (r"(?i)authorization:\s*(aws4-hmac|bearer)\s+\S", "authorization header"),
    (r"X-Amz-Signature=[0-9a-f]{16,}", "signed URL"),
]


def check_repo():
    files = [f for f in glob.glob(os.path.join(REPO, "**", "*"), recursive=True)
             if os.path.isfile(f) and ".git" not in f.split(os.sep) and f != os.path.abspath(__file__)]
    hits = []
    for f in files:
        try: text = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError): continue
        for pat, what in SECRET_PATTERNS:
            if re.search(pat, text): hits.append(f"{os.path.relpath(f, REPO)}: {what}")
    check(not hits, "repo: no secrets, auth headers or signed URLs", hits)
    for f in sorted(glob.glob(os.path.join(REPO, "fixtures", "connections", "*.json"))):
        c = json.load(open(f, encoding="utf-8"))
        name = os.path.basename(f)
        check(c.get("provider") in {p["id"] for p in load("spec/providers.json")["providers"]}, f"fixture {name}: known provider")
        check("credential_ref" in c and not any(k in c for k in ("secret_access_key", "access_key_id", "password")),
              f"fixture {name}: credential by reference only")
        check(c.get("allow_insecure_http", False) is False or "localhost" in c.get("endpoint", ""),
              f"fixture {name}: plain http only on localhost")
    for f in sorted(glob.glob(os.path.join(REPO, "fixtures", "receipts", "*.json"))):
        r = json.load(open(f, encoding="utf-8"))
        states = load("spec/contract.json")["concepts"]["OperationReceipt"]["state"]
        check(r.get("state") in states, f"fixture {os.path.basename(f)}: receipt state known")


# --- driver cases -----------------------------------------------------------------------------------------------------
class Driver:
    def __init__(self, cmd):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.n = 0

    def call(self, op, args=None, options=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"id": self.n, "op": op, "args": args or {}, "options": options or {}}) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line: raise RuntimeError("driver exited")
        resp = json.loads(line)
        if resp.get("id") != self.n: raise RuntimeError(f"response id {resp.get('id')} != {self.n}")
        return resp

    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception: self.p.kill()


def expand(seed):
    out = []
    for s in seed:
        if "generate" in s: out += [{"path": s["generate"].format(i=i), "content": s.get("content", "")} for i in range(s["count"])]
        else: out.append(s)
    return out


def paths(result):
    items = result if isinstance(result, list) else result.get("items", [])
    return [i["path"] for i in items]


def subset(have, want):
    return all(k in have and have[k] == v for k, v in want.items())


def run_case(drv, case):
    name, root = case["name"], "test-bucket"
    r = drv.call("reset", {"seed": expand(case.get("seed", []))})
    check(r.get("ok"), f"{name}: reset")
    for n, step in enumerate(case["steps"], 1):
        label = f"{name} #{n} {step['op']}"
        args = dict(step.get("args", {}))
        if step["op"] not in ("testConnection", "listRoots"): args.setdefault("root", root)
        opts, exp = step.get("options", {}), step["expect"]
        resp = drv.call(step["op"], args, opts)
        if "error" in exp:
            got = None if resp.get("ok") else resp.get("error", {}).get("code")
            check(got == exp["error"], f"{label}: error {exp['error']}", f"got {got or 'ok'}")
        else:
            if not resp.get("ok"):
                check(False, f"{label}: ok", resp.get("error")); continue
            res = resp["result"]
            if "pages" in exp:
                pages, items, token = 1, list(res["items"]), res.get("next_token")
                sizes = [len(res["items"])]
                while token and pages < 100:
                    nxt = drv.call("list", dict(args, token=token), opts)
                    if not nxt.get("ok"): break
                    pages += 1; items += nxt["result"]["items"]; sizes.append(len(nxt["result"]["items"]))
                    token = nxt["result"].get("next_token")
                check(pages == exp["pages"], f"{label}: {exp['pages']} pages", pages)
                if "max_page_size" in exp:
                    check(max(sizes) <= exp["max_page_size"], f"{label}: page size <= {exp['max_page_size']}", sizes)
                if "all_pages_paths" in exp:
                    g = exp["all_pages_paths"]
                    want = [g["generate"].format(i=i) for i in range(g["count"])] + g.get("then", [])
                    got = [i["path"] for i in items]
                    check(got == want, f"{label}: every item once, in order", f"{len(got)} items")
            if "result_paths" in exp:
                check(paths(res) == exp["result_paths"], f"{label}: paths", paths(res))
            if "count" in exp:
                check(len(res if isinstance(res, list) else res["items"]) == exp["count"], f"{label}: count {exp['count']}")
            if "result_has" in exp:
                check(subset(res, exp["result_has"]), f"{label}: result fields", {k: res.get(k) for k in exp["result_has"]})
            if "item_has" in exp:
                item = (res.get("items") or [{}])[0]
                check(subset(item, exp["item_has"]), f"{label}: item fields", {k: item.get(k) for k in exp["item_has"]})
            if "content" in exp:
                got = base64.b64decode(res["content_b64"]).decode("utf-8", "replace")
                check(got == exp["content"], f"{label}: content", got)
            if "capabilities_include" in exp:
                missing = [c for c in exp["capabilities_include"] if c not in res.get("capabilities", [])]
                check(not missing, f"{label}: capabilities", missing)
        if "store" in exp or "store_count" in exp:
            keys = drv.call("dump")["result"]
            if "store" in exp: check(keys == exp["store"], f"{label}: store after", keys)
            if "store_count" in exp: check(len(keys) == exp["store_count"], f"{label}: store unchanged", len(keys))


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    check_spec()
    check_repo()
    drv = Driver(sys.argv[1:])
    try:
        for f in sorted(glob.glob(os.path.join(HERE, "cases", "*.json"))):
            run_case(drv, json.load(open(f, encoding="utf-8")))
    finally:
        drv.close()
    print(f"\n{passed} passed, {len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
