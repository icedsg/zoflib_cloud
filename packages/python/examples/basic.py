"""Minimal use: python examples/basic.py  (needs the package on the path, e.g. `pip install -e packages/python`)."""
import os
from zoflib_cloud import Credential, S3Config, s3_store, CloudError


def resolve(credential_ref, session_token_ref):
    # The host resolves the reference (OS keychain, secret manager, env). Never hard-code keys.
    return Credential(os.environ["S3_ACCESS_KEY"], os.environ["S3_SECRET_KEY"])


config = S3Config(endpoint=os.environ.get("S3_ENDPOINT", "https://s3.eu-central-1.amazonaws.com"), region="eu-central-1",
                  credential_ref="env:S3", root=os.environ.get("S3_BUCKET", "my-bucket"), addressing="virtual")
store = s3_store(config, resolve)
try:
    print(store.test_connection()["capabilities"])
    for item in store.list("photos/", options={"page_size": 50})["items"]: print(item["kind"], item["path"])
    print([i["path"] for i in store.search("invoice")["items"]])
    store.upload("hello.txt", b"hello", {"overwrite": "rename"})
    store.delete("hello.txt", {"destructive": True})
except CloudError as e:
    print(e.code, e, "retry" if e.retry else "")
