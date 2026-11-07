# zoflib_cloud

One contract for cloud file storage, with a shared conformance suite, so apps can list, search, upload, download,
copy, move and delete files across providers with the same behaviour in every language.

This repository holds the contract, test suite and the first language implementation: the C# generic-S3 package.
JavaScript/TypeScript, Python, Kotlin and Swift packages will follow and must pass the same suite before publishing.

## What is here

| Path | What it is |
|---|---|
| `spec/contract.json` | Concepts, operations, options, receipts, path rules and cancellation semantics (versioned, `contract_version`). |
| `spec/errors.json` | The normalized error codes every package returns. |
| `spec/providers.json` | 30 storage services with protocol, endpoint pattern, addressing, caveats and the official documentation each entry was checked against (`verified_at`). |
| `conformance/cases/` | Language-neutral test cases: pagination, duplicate names, Unicode keys, cancellation, safe deletes and the basics. |
| `conformance/run.py` | Runs the spec checks and every case against a driver. |
| `conformance/fake_store.py` | Reference driver backed by an in-memory store, so the suite itself is tested. |
| `fixtures/` | Redacted example connection configs and receipts. Credentials appear only as references. |
| `packages/csharp/` | .NET 10+ contract models, provider presets, generic S3 adapter, conformance driver and tests. |

## Run

```
python conformance/run.py python conformance/fake_store.py
```

Python 3.8+, standard library only. Exit code 0 means every check passed. A package plugs in by shipping a small
driver that speaks the protocol in [conformance/README.md](conformance/README.md).

## Providers

S3-compatible services share one adapter and differ only by preset (endpoint, region, addressing). Others need a
native adapter behind the same contract. Each entry in `spec/providers.json` has one classification:

| Classification | Meaning | Count |
|---|---|---|
| `tested` | Passes integration tests against the provider | 0 |
| `compatible_by_protocol` | Documents an S3-compatible API; the generic S3 adapter should work, not tested yet | 24 |
| `native_planned` | Needs its own adapter (Azure Blob Storage, Google Drive, OneDrive/SharePoint, Dropbox, Box) | 5 |
| `unsupported` | No public API for a third-party library (iCloud Drive outside Apple devices) | 1 |

Nothing is called supported until it is `tested`. Self-hosted S3 servers (MinIO, Ceph, Garage, SeaweedFS) take any
endpoint you give them.

## Design rules

- Keys are kept byte for byte: no Unicode normalization or case folding of stored names. Search matches names after
  NFC normalization and case folding, so `café` finds both spellings.
- Listing and search return items in UTF-8 byte order, page by opaque tokens, and stream rather than load a bucket.
- Delete and move do nothing without an explicit destructive option; folders with contents also need `recursive`.
  Every change returns a receipt that says what happened, including partial moves and delete markers.
- A cancel before a call changes nothing.
- HTTPS by default. Plain HTTP only with an explicit development override.
- Credentials are never stored, logged or put in errors and receipts. Apps keep them in the platform's secret store
  and pass a reference.

## Licence

MIT, see [LICENSE](LICENSE).
