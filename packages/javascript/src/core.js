// Contract 0.1.0 over a small backend interface. Backends: MemoryBackend (tests) and S3Backend (generic S3).
// Backend methods (async, keys are full object keys):
//   listPage(prefix, delimiter, token, maxKeys, signal) -> {objects:[{key,size,modified,etag}], prefixes, nextToken}
//   head(key, signal) -> object | null;  get(key, signal) -> Uint8Array;  put(key, data, signal) -> object;
//   copy(src, dst, signal);  delete(key, signal)
import { createHash } from 'node:crypto';
import { CloudError, checkSignal } from './errors.js';

export const CAPABILITIES = ['list', 'stat', 'search', 'upload', 'multipart_upload', 'download', 'copy', 'move', 'rename', 'delete'];

const enc = new TextEncoder();
export const utf8Compare = (a, b) => Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'));
const fold = (s) => s.normalize('NFC').toLowerCase().normalize('NFC');
const nameOf = (p) => p.replace(/\/+$/, '').split('/').pop();
const dirOf = (p) => (p === '' || p.endsWith('/') ? p : p + '/');
const receipt = (operation, state, items) => ({ operation, state, items });

export class CloudStore {
  constructor(backend, root) { this.backend = backend; this.root = root; }

  #item(o) { return { root: this.root, path: o.key, name: nameOf(o.key), kind: 'file', size: o.size, modified: o.modified, etag: o.etag }; }
  #folder(prefix) { return { root: this.root, path: prefix, name: nameOf(prefix), kind: 'folder', size: null, modified: null, etag: null }; }
  #begin(options) {
    checkSignal(options.signal);
    if (options.root != null && options.root !== this.root) throw new CloudError('not_found', 'unknown root');
    return options.signal;
  }

  async #freeName(key, signal) {
    const i = key.lastIndexOf('/'), folder = i < 0 ? '' : key.slice(0, i), name = key.slice(i + 1);
    const d = name.lastIndexOf('.');
    const [stem, ext] = d > 0 ? [name.slice(0, d), name.slice(d)] : [name, ''];
    for (let n = 1; ; n++) {
      const cand = (folder ? folder + '/' : '') + `${stem} (${n})${ext}`;
      if (!(await this.backend.head(cand, signal))) return cand;
    }
  }

  async #target(key, overwrite = 'fail', signal) {
    if (!['fail', 'replace', 'rename'].includes(overwrite)) throw new CloudError('invalid_config', 'unknown overwrite mode');
    if (!(await this.backend.head(key, signal))) return key;
    if (overwrite === 'replace') return key;
    if (overwrite === 'rename') return this.#freeName(key, signal);
    throw new CloudError('conflict', 'target exists');
  }

  async *#allKeys(prefix, signal) {
    let token = null;
    do {
      const page = await this.backend.listPage(prefix, null, token, 1000, signal);
      yield* page.objects;
      token = page.nextToken;
    } while (token);
  }

  async testConnection(options = {}) {
    await this.backend.listPage('', '/', null, 1, options.signal);
    return { capabilities: [...CAPABILITIES] };
  }
  async listRoots() {
    return [{ root: this.root, path: '', name: this.root, kind: 'folder', size: null, modified: null, etag: null }];
  }
  async list(path = '', options = {}) {
    const signal = this.#begin(options), prefix = dirOf(path);
    const page = await this.backend.listPage(prefix, '/', options.token ?? null, Math.max(1, options.pageSize ?? 1000), signal);
    const rows = [...page.objects.filter((o) => o.key !== prefix).map((o) => [o.key, this.#item(o)]),
      ...page.prefixes.filter((p) => p !== prefix).map((p) => [p, this.#folder(p)])];
    rows.sort((a, b) => utf8Compare(a[0], b[0]));
    return { items: rows.map((r) => r[1]), nextToken: page.nextToken ?? null };
  }
  async stat(path, options = {}) {
    const signal = this.#begin(options);
    const o = path.endsWith('/') ? null : await this.backend.head(path, signal);
    if (o) return this.#item(o);
    const prefix = dirOf(path);
    if (prefix && (await this.backend.listPage(prefix, null, null, 1, signal)).objects.length) return this.#folder(prefix);
    throw new CloudError('not_found', 'no such item');
  }
  /** options.onResult(count) fires after each result (the conformance driver uses it for cancel-after-N). */
  async search(query, under = '', options = {}) {
    const signal = this.#begin(options), q = fold(query), limit = options.limit ?? 1000, items = [];
    for await (const o of this.#allKeys(under, signal)) {
      if (o.key.endsWith('/') || !fold(nameOf(o.key)).includes(q)) continue;
      checkSignal(signal);
      if (items.length >= limit) return { items, truncated: true };
      items.push(this.#item(o));
      options.onResult?.(items.length);
    }
    return { items, truncated: false };
  }
  async download(path, options = {}) {
    const signal = this.#begin(options);
    const o = await this.backend.head(path, signal);
    if (!o) throw new CloudError('not_found', 'no such item');
    if (options.maxBytes != null && o.size > options.maxBytes) throw new CloudError('quota', 'larger than maxBytes');
    const content = await this.backend.get(path, signal);
    return { content, size: content.length };
  }
  async upload(path, data, options = {}) {
    const signal = this.#begin(options);
    const bytes = typeof data === 'string' ? enc.encode(data) : data;
    const key = await this.#target(path, options.overwrite, signal);
    return receipt('upload', 'completed', [this.#item(await this.backend.put(key, bytes, signal))]);
  }
  async copy(path, to, options = {}) {
    const signal = this.#begin(options);
    if (!(await this.backend.head(path, signal))) throw new CloudError('not_found', 'no such item');
    const key = await this.#target(to, options.overwrite, signal);
    await this.backend.copy(path, key, signal);
    return receipt('copy', 'completed', [this.#item(await this.backend.head(key, signal))]);
  }
  async move(path, to, options = {}) {
    const signal = this.#begin(options);
    if (!options.destructive) throw new CloudError('confirmation_required', 'move deletes the source');
    const r = await this.copy(path, to, options);
    if (r.items[0].path === path) return receipt('move', 'nothing_to_do', r.items);
    try { await this.backend.delete(path, signal); } catch (e) {
      if (e instanceof CloudError) return receipt('move', 'copied', r.items);
      throw e;
    }
    return receipt('move', 'source_deleted', r.items);
  }
  async delete(path, options = {}) {
    const signal = this.#begin(options);
    if (!options.destructive) throw new CloudError('confirmation_required', 'delete needs the destructive option');
    if (!path.endsWith('/') && (await this.backend.head(path, signal))) {
      await this.backend.delete(path, signal);
      return receipt('delete', 'completed', [{ root: this.root, path }]);
    }
    const prefix = dirOf(path), keys = [];
    for await (const o of this.#allKeys(prefix, signal)) keys.push(o.key);
    keys.sort(utf8Compare);
    if (!keys.length) throw new CloudError('not_found', 'no such item');
    if (!options.recursive && keys.some((k) => k !== prefix)) throw new CloudError('conflict', 'folder has contents');
    const done = [];
    for (const k of keys) {
      if (signal?.aborted) return receipt('delete', 'partial', done);
      await this.backend.delete(k, signal);
      done.push({ root: this.root, path: k });
    }
    return receipt('delete', 'completed', done);
  }
}

/** In-memory object store with S3 listing behaviour; used by tests and the conformance driver. */
export class MemoryBackend {
  objs = new Map();
  #obj(key) {
    const [data, modified] = this.objs.get(key);
    return { key, size: data.length, modified, etag: createHash('md5').update(data).digest('hex') };
  }
  seed(key, data, modified = '2026-01-01T00:00:00Z') { this.objs.set(key, [Uint8Array.from(data), modified]); }
  async listPage(prefix, delimiter, token, maxKeys) {
    const rows = [], seen = new Set();
    for (const k of this.objs.keys()) {
      if (!k.startsWith(prefix)) continue;
      const rest = k.slice(prefix.length);
      if (delimiter && rest.includes(delimiter)) {
        const p = prefix + rest.split(delimiter)[0] + delimiter;
        if (!seen.has(p)) { seen.add(p); rows.push([p, false]); }
      } else rows.push([k, true]);
    }
    rows.sort((a, b) => utf8Compare(a[0], b[0]));
    let start = 0;
    if (token) {
      const m = /^o:(\d+)$/.exec(Buffer.from(token, 'base64url').toString());
      if (!m) throw new CloudError('invalid_config', 'bad continuation token');
      start = Number(m[1]);
    }
    const page = rows.slice(start, start + maxKeys), next = start + maxKeys;
    return { objects: page.filter((r) => r[1]).map((r) => this.#obj(r[0])), prefixes: page.filter((r) => !r[1]).map((r) => r[0]),
      nextToken: next < rows.length ? Buffer.from(`o:${next}`).toString('base64url') : null };
  }
  async head(key) { return this.objs.has(key) ? this.#obj(key) : null; }
  async get(key) { return this.objs.get(key)[0]; }
  async put(key, data) { this.seed(key, data, '2026-06-01T00:00:00Z'); return this.#obj(key); }
  async copy(src, dst) { this.objs.set(dst, this.objs.get(src)); }
  async delete(key) { this.objs.delete(key); }
}
