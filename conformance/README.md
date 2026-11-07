# Driver protocol

`run.py` starts the driver command and talks to it over stdio, one JSON object per line each way.

Request:

```json
{"id": 7, "op": "upload", "args": {"root": "test-bucket", "path": "a/report.pdf", "content": "v2"}, "options": {"overwrite": "rename"}}
```

Response, success or failure:

```json
{"id": 7, "ok": true, "result": {"operation": "upload", "state": "completed", "items": [{"path": "a/report (1).pdf", "...": "..."}]}}
{"id": 7, "ok": false, "error": {"code": "conflict", "message": "target exists"}}
```

`id` is echoed. `error.code` is one of `spec/errors.json`.

## Operations

The contract operations from `spec/contract.json` (`testConnection`, `listRoots`, `list`, `stat`, `search`,
`download`, `upload`, `copy`, `move`, `delete`), plus two test-only ones:

- `reset` with `args.seed` = `[{"path", "content" | "content_b64", "modified"?}]`: empty the root `test-bucket` and fill it.
- `dump`: return every key in the root, in UTF-8 byte order.

Shapes the cases rely on:

- `list` takes `args.path` and, for later pages, `args.token`; returns `{"items", "next_token"}`.
- `search` returns `{"items", "truncated"}`.
- `download` returns `{"content_b64", "size"}`; above `options.max_bytes` it fails with `quota`.
- `upload` takes `args.content` (UTF-8 text) or `args.content_b64`.
- Receipts are `{"operation", "state", "items"}`.

## Cancellation

`options.cancel` is `"before"` (the token is already cancelled when the call starts: return `cancelled`, change
nothing) or `{"after_items": n}` for `search` (cancel once `n` results have been produced: return `cancelled`).

## A real package's driver

A package driver maps these requests onto the package's public API and points it at a disposable bucket, for
example a local S3-compatible server started for the test run. It must reset and dump through the same API. Never
run the suite against a bucket that holds real data.
