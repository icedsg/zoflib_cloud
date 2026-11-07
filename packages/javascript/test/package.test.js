import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { inspect } from 'node:util';
import { s3Store, MemoryBackend, CloudStore, CloudError, Credential, CODES, CONTRACT_VERSION, redact, loadPresets, configFromPreset } from '../src/index.js';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const readJson = (p) => JSON.parse(readFileSync(path.join(REPO, p), 'utf8'));
let server, endpoint;

before(async () => {
  server = spawn('python', [path.join(REPO, 'conformance', 'fake_s3.py'), '0'], { stdio: ['ignore', 'pipe', 'inherit'] });
  const port = await new Promise((res) => server.stdout.once('data', (d) => res(String(d).trim())));
  endpoint = `http://127.0.0.1:${port}`;
});
after(() => server.kill());

const store = (bucket, secret = 'zoflibtestsecret', options) =>
  s3Store({ endpoint, region: 'us-east-1', credentialRef: 'ref:x', root: bucket, allowInsecureHttp: true }, async () => new Credential('zoflibtest', secret), options);
const code = (p) => p.then(() => 'none', (e) => e.code);

test('operations over signed S3 requests', async () => {
  const s = store('ops');
  await s.upload('docs/a b/ü.txt', 'hello');
  assert.equal(Buffer.from((await s.download('docs/a b/ü.txt')).content).toString(), 'hello');
  assert.deepEqual((await s.list('docs/')).items.map((i) => i.path), ['docs/a b/']);
  assert.equal((await s.stat('docs/a b')).kind, 'folder');
  assert.equal((await s.search('Ü')).items[0].name, 'ü.txt');
  assert.equal((await s.upload('docs/a b/ü.txt', '2', { overwrite: 'rename' })).items[0].path, 'docs/a b/ü (1).txt');
  assert.equal((await s.copy('docs/a b/ü.txt', 'c.txt')).state, 'completed');
  assert.equal((await s.move('c.txt', 'd.txt', { destructive: true })).state, 'source_deleted');
  assert.equal(await code(s.delete('d.txt')), 'confirmation_required');
  assert.equal((await s.delete('docs/', { destructive: true, recursive: true })).state, 'completed');
  assert.deepEqual((await s.list('')).items.map((i) => i.path), ['d.txt']);
});

test('multipart upload of 17 MiB', async () => {
  const s = store('mp'), data = randomBytes(17 * 1024 * 1024);
  await s.upload('big.bin', data);
  assert.ok(Buffer.from((await s.download('big.bin')).content).equals(data));
  assert.equal((await s.stat('big.bin')).size, data.length);
});

test('errors are normalized and carry retry hints', async () => {
  assert.equal(await code(store('e1', 'wrong').list('')), 'authentication');
  const e = await store('throttle').list('').catch((x) => x);
  assert.deepEqual([e.code, e.retryAfterMs, e.retry], ['throttled', 2000, true]);
  const dead = s3Store({ endpoint: 'http://127.0.0.1:1', region: 'r', credentialRef: 'r', root: 'b', allowInsecureHttp: true }, () => new Credential('a', 'b'));
  assert.equal(await code(dead.list('')), 'network');
});

test('cancellation with an AbortSignal', async () => {
  const ctl = new AbortController(); ctl.abort();
  assert.equal(await code(store('cx').list('', { signal: ctl.signal })), 'cancelled');
});

test('config safety and credential redaction', () => {
  assert.throws(() => s3Store({ endpoint: 'http://example.com', region: 'r', credentialRef: 'c', root: 'b' }, () => {}), { code: 'invalid_config' });
  assert.throws(() => s3Store({ endpoint: 'http://example.com', region: 'r', credentialRef: 'c', root: 'b', allowInsecureHttp: true }, () => {}), { code: 'invalid_config' });
  const c = new Credential('access-id-value', 'topsecretvalue');
  for (const text of [String(c), JSON.stringify(c), inspect(c)]) assert.ok(!/topsecretvalue|access-id-value/.test(text));
  const sig = 'abcdef' + '0123456789', key = 'AK' + 'IA' + 'IOSFODNN7EXAMPLE';
  const r = redact(`GET https://h/x?X-Amz-Signature=${sig}&a=1 ${key} Authorization: AWS4-HMAC-SHA256 Credential=x`);
  for (const bad of [sig, key, 'Credential=x']) assert.ok(!r.includes(bad));
});

test('contract version, error codes and presets match the spec', () => {
  const errors = readJson('spec/errors.json');
  assert.equal(CONTRACT_VERSION, errors.contract_version);
  assert.equal(CONTRACT_VERSION, readJson('spec/contract.json').contract_version);
  assert.deepEqual(CODES, errors.errors.map((e) => e.code));
  const p = loadPresets(path.join(REPO, 'spec', 'providers.json'));
  assert.equal(Object.keys(p).length, 24);
  assert.throws(() => configFromPreset(p.minio, { root: 'b', credentialRef: 'r' }), TypeError);
  assert.equal(configFromPreset(p.minio, { root: 'b', credentialRef: 'r', endpoint: 'https://minio.example.org' }).addressing, 'path');
});

test('paging and bounded search on the memory backend', async () => {
  const b = new MemoryBackend();
  for (let i = 0; i < 25; i++) b.seed(`p/f${String(i).padStart(2, '0')}`, [1]);
  const s = new CloudStore(b, 'r'), seen = []; let token = null;
  do { const pg = await s.list('p/', { pageSize: 10, token }); seen.push(...pg.items.map((i) => i.path)); token = pg.nextToken; } while (token);
  assert.equal(seen.length, 25);
  const r = await s.search('f', 'p/', { limit: 7 });
  assert.deepEqual([r.items.length, r.truncated], [7, true]);
});
