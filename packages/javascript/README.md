# zoflib-cloud (JavaScript / TypeScript)

Contract 0.1.0 for generic S3-compatible storage. Node 20+, no dependencies, types included. Credentials stay outside
configuration: the host resolves a credential reference only when a request is signed.

```js
import { s3Store, Credential } from 'zoflib-cloud';
const store = s3Store({ endpoint: 'https://objects.example.com', region: 'us-east-1', credentialRef: 'my-secret-reference',
  root: 'photos-bucket', addressing: 'path' }, async (ref) => new Credential(/* resolve ref in your secret store */));
const page = await store.list('2026/', { pageSize: 100 });
```

Operations: `testConnection`, `listRoots`, `list`, `stat`, `search`, `download`, `upload`, `copy`, `move`, `delete`.
Cancel with an `AbortSignal` in `options.signal`. Destructive calls need `{ destructive: true }`; folders with contents also
need `{ recursive: true }`. `upload`/`copy`/`move` take `overwrite: 'fail' | 'replace' | 'rename'`. Uploads above 8 MiB
use multipart. Failures are `CloudError` with a `code` from `spec/errors.json`, `retry`, `providerCode`, `requestId`
and `retryAfterMs`; messages never hold credentials, headers, signed URLs or response bodies. HTTP is rejected unless
`allowInsecureHttp` is set for a loopback development endpoint.

Presets: `loadPresets('spec/providers.json')` and `configFromPreset(preset, { root, credentialRef, endpoint })`. A preset
is a documented default, not a claim that the provider was integration-tested.

```sh
node --test packages/javascript/test/                                # package tests (start the fake S3 server themselves)
python conformance/run.py node packages/javascript/src/driver.js     # shared conformance (memory backend)
```

Set `ZOFLIB_S3_ENDPOINT`, `ZOFLIB_S3_ACCESS`, `ZOFLIB_S3_SECRET` to run the same suite through the S3 adapter against a
disposable endpoint (`python conformance/fake_s3.py 9090` is one).
