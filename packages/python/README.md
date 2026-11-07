# zoflib-cloud (Python)

Contract 0.1.0 for generic S3-compatible storage. Python 3.9+, standard library only. Credentials stay outside
configuration: the host resolves a credential reference only when a request is signed. The API is synchronous.

```python
from zoflib_cloud import S3Config, Credential, s3_store

config = S3Config(endpoint="https://objects.example.com", region="us-east-1", credential_ref="my-secret-reference",
                  root="photos-bucket", addressing="path")
store = s3_store(config, lambda ref, token_ref: Credential(...))   # resolve ref in your secret store
page = store.list("2026/", options={"page_size": 100})
```

Operations: `test_connection`, `list_roots`, `list`, `stat`, `search`, `download`, `upload`, `copy`, `move`, `delete`.
Cancel with a `CancelToken` in `options["cancel"]`. Destructive calls need `{"destructive": True}`; folders with
contents also need `{"recursive": True}`. `upload`/`copy`/`move` take `overwrite` of `fail`, `replace` or `rename`.
Uploads above 8 MiB use multipart. Failures are `CloudError` with a `code` from `spec/errors.json`, `retry`,
`provider_code`, `request_id` and `retry_after_ms`; messages never hold credentials, headers, signed URLs or response
bodies. HTTP is rejected unless `allow_insecure_http` is set for a loopback development endpoint.

Presets: `load_presets("spec/providers.json")` and `config_from_preset(preset, root, credential_ref, endpoint=...)`.
A preset is a documented default, not a claim that the provider was integration-tested.

```sh
python -m unittest discover -s packages/python/tests                                # package tests
PYTHONPATH=packages/python python conformance/run.py python -m zoflib_cloud.driver  # shared conformance
```

Set `ZOFLIB_S3_ENDPOINT`, `ZOFLIB_S3_ACCESS`, `ZOFLIB_S3_SECRET` to run the same suite through the S3 adapter against a
disposable endpoint (`python conformance/fake_s3.py 9090` is one).
