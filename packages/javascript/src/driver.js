#!/usr/bin/env node
// Conformance driver (conformance/README.md): node src/driver.js
// Memory backend by default. With ZOFLIB_S3_ENDPOINT, ZOFLIB_S3_ACCESS and ZOFLIB_S3_SECRET set it talks to that
// disposable S3-compatible endpoint (bucket test-bucket, emptied by `reset`); never point it at real data.
import { createInterface } from 'node:readline';
import { CloudStore, MemoryBackend, utf8Compare } from './core.js';
import { CloudError } from './errors.js';
import { S3Backend, Credential } from './s3.js';

const ROOT = 'test-bucket';

function makeStore() {
  const endpoint = process.env.ZOFLIB_S3_ENDPOINT;
  if (!endpoint) return new CloudStore(new MemoryBackend(), ROOT);
  const cred = new Credential(process.env.ZOFLIB_S3_ACCESS, process.env.ZOFLIB_S3_SECRET);
  const config = { endpoint, region: 'us-east-1', credentialRef: 'env', root: ROOT, allowInsecureHttp: true };
  return new CloudStore(new S3Backend(config, () => cred), ROOT);
}

const bytes = (a) => (a.content_b64 != null ? Buffer.from(a.content_b64, 'base64') : Buffer.from(a.content ?? '', 'utf8'));

async function allKeys(store) {
  const out = []; let token = null;
  do {
    const p = await store.backend.listPage('', null, token, 1000);
    out.push(...p.objects.map((o) => o.key)); token = p.nextToken;
  } while (token);
  return out.sort(utf8Compare);
}

async function handle(store, req) {
  const { op } = req, a = req.args ?? {}, o = req.options ?? {};
  const opts = { root: a.root, pageSize: o.page_size, limit: o.limit, maxBytes: o.max_bytes, overwrite: o.overwrite,
    destructive: o.destructive, recursive: o.recursive, token: a.token };
  const c = o.cancel;
  if (c === 'before' && op !== 'reset' && op !== 'dump') throw new CloudError('cancelled', 'cancelled before start');
  if (c && typeof c === 'object') {
    const ctl = new AbortController();
    opts.signal = ctl.signal;
    opts.onResult = (n) => { if (n >= (c.after_items ?? Infinity)) ctl.abort(); };
  }
  switch (op) {
    case 'reset':
      for (const k of await allKeys(store)) await store.backend.delete(k);
      for (const s of a.seed ?? []) await store.backend.put(s.path, bytes(s));
      return { count: (a.seed ?? []).length };
    case 'dump': return allKeys(store);
    case 'testConnection': return store.testConnection(opts);
    case 'listRoots': return store.listRoots();
    case 'list': return store.list(a.path ?? '', opts);
    case 'stat': return store.stat(a.path, opts);
    case 'search': return store.search(a.query, a.under ?? '', opts);
    case 'download': { const r = await store.download(a.path, opts); return { content_b64: Buffer.from(r.content).toString('base64'), size: r.size }; }
    case 'upload': return store.upload(a.path, bytes(a), opts);
    case 'copy': return store.copy(a.path, a.to, opts);
    case 'move': return store.move(a.path, a.to, opts);
    case 'delete': return store.delete(a.path, opts);
    default: throw new CloudError('unsupported', 'unknown operation');
  }
}

// list/search results use camelCase nextToken inside the package; the wire format is snake_case
const wire = (r) => (r && typeof r === 'object' && 'nextToken' in r ? { items: r.items, next_token: r.nextToken } : r);

const store = makeStore();
const rl = createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const req = JSON.parse(line);
  let resp;
  try { resp = { id: req.id, ok: true, result: wire(await handle(store, req)) }; } catch (e) {
    resp = { id: req.id, ok: false, error: e instanceof CloudError ? e.toJSON() : { code: 'provider_error', message: 'internal error' } };
  }
  process.stdout.write(JSON.stringify(resp) + '\n');
}
