import json, os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "conformance"))
import fake_s3
from zoflib_cloud import (CloudError, CancelToken, Credential, S3Config, CONTRACT_VERSION, MemoryBackend, CloudStore,
                          s3_store, load_presets, config_from_preset, CODES)
from zoflib_cloud.errors import redact


class S3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = fake_s3.serve(0)
        cls.ep = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def store(self, bucket="b1", secret=fake_s3.SECRET, **kw):
        cfg = S3Config(self.ep, "us-east-1", "ref:x", bucket, allow_insecure_http=True)
        return s3_store(cfg, lambda ref, tok: Credential(fake_s3.ACCESS, secret), **kw)

    def test_operations(self):
        s = self.store("ops")
        s.upload("docs/a b/ü.txt", b"hello")
        self.assertEqual(s.download("docs/a b/ü.txt")["content"], b"hello")
        self.assertEqual([i["path"] for i in s.list("docs/")["items"]], ["docs/a b/"])
        self.assertEqual(s.stat("docs/a b")["kind"], "folder")
        self.assertEqual(s.search("Ü")["items"][0]["name"], "ü.txt")
        self.assertEqual(s.upload("docs/a b/ü.txt", b"2", {"overwrite": "rename"})["items"][0]["path"], "docs/a b/ü (1).txt")
        self.assertEqual(s.copy("docs/a b/ü.txt", "c.txt")["state"], "completed")
        self.assertEqual(s.move("c.txt", "d.txt", {"destructive": True})["state"], "source_deleted")
        with self.assertRaises(CloudError) as e: s.delete("d.txt")
        self.assertEqual(e.exception.code, "confirmation_required")
        self.assertEqual(s.delete("docs/", {"destructive": True, "recursive": True})["state"], "completed")
        self.assertEqual([i["path"] for i in s.list("")["items"]], ["d.txt"])

    def test_multipart_17_mib(self):
        s = self.store("mp")
        data = os.urandom(17 * 1024 * 1024)
        s.upload("big.bin", data)
        self.assertEqual(s.download("big.bin")["content"], data)
        self.assertEqual(s.stat("big.bin")["size"], len(data))

    def test_errors(self):
        with self.assertRaises(CloudError) as e: self.store(secret="wrong").list("")
        self.assertEqual(e.exception.code, "authentication")
        with self.assertRaises(CloudError) as e: self.store("throttle").list("")
        self.assertEqual((e.exception.code, e.exception.retry_after_ms, e.exception.retry), ("throttled", 2000, True))
        dead = S3Config("http://127.0.0.1:1", "us-east-1", "r", "b", allow_insecure_http=True)
        with self.assertRaises(CloudError) as e: s3_store(dead, lambda *a: Credential("a", "b")).list("")
        self.assertEqual(e.exception.code, "network")

    def test_cancel(self):
        tok = CancelToken(); s = self.store("cx", cancel=tok); tok.cancel()
        with self.assertRaises(CloudError) as e: s.list("")
        self.assertEqual(e.exception.code, "cancelled")

    def test_config_safety(self):
        for cfg in (S3Config("http://example.com", "r", "c", "b"), S3Config("http://example.com", "r", "c", "b", allow_insecure_http=True)):
            with self.assertRaises(CloudError) as e: cfg.validate()
            self.assertEqual(e.exception.code, "invalid_config")
        self.assertNotIn("secret", repr(Credential("access-id-value", "topsecretvalue")))


class CoreTests(unittest.TestCase):
    def test_contract_version_and_codes(self):
        spec = json.load(open(os.path.join(REPO, "spec", "errors.json"), encoding="utf-8"))
        self.assertEqual(CONTRACT_VERSION, spec["contract_version"])
        self.assertEqual(list(CODES), [e["code"] for e in spec["errors"]])
        self.assertEqual(CONTRACT_VERSION, json.load(open(os.path.join(REPO, "spec", "contract.json"), encoding="utf-8"))["contract_version"])

    def test_redaction(self):
        sig, key = "abcdef" + "0123456789", "AK" + "IA" + "IOSFODNN7EXAMPLE"  # built at run time: no secret-looking literals
        text = redact(f"GET https://h/x?X-Amz-Signature={sig}&a=1 {key} Authorization: AWS4-HMAC-SHA256 Credential=x")
        for bad in (sig, key, "Credential=x"): self.assertNotIn(bad, text)

    def test_presets(self):
        p = load_presets(os.path.join(REPO, "spec", "providers.json"))
        self.assertEqual(len(p), 24)
        with self.assertRaises(ValueError): config_from_preset(p["minio"], "b", "ref")
        cfg = config_from_preset(p["minio"], "b", "ref", endpoint="https://minio.example.org")
        self.assertEqual(cfg.addressing, "path")

    def test_paging_and_search_bounds(self):
        b = MemoryBackend()
        for i in range(25): b.seed(f"p/f{i:02}", b"x")
        s = CloudStore(b, "r")
        seen, tok = [], None
        while True:
            pg = s.list("p/", tok, {"page_size": 10}); seen += [i["path"] for i in pg["items"]]; tok = pg["next_token"]
            if not tok: break
        self.assertEqual(seen, [f"p/f{i:02}" for i in range(25)])
        r = s.search("f", "p/", {"limit": 7}); self.assertEqual((len(r["items"]), r["truncated"]), (7, True))


if __name__ == "__main__": unittest.main()
