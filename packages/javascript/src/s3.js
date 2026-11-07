// Generic S3-compatible backend: SigV4 over fetch, no dependencies. Credentials come from a host callback.
import { createHash, createHmac } from 'node:crypto';
import { CloudError, checkSignal } from './errors.js';

export const MULTIPART_THRESHOLD = 8 * 1024 * 1024;
export const PART_SIZE = 8 * 1024 * 1024;
const EMPTY = createHash('sha256').update('').digest('hex');
const PROVIDER_CODES = {
  InvalidAccessKeyId: 'authentication', SignatureDoesNotMatch: 'authentication', ExpiredToken: 'authentication',
  AccessDenied: 'permission', NoSuchKey: 'not_found', NoSuchBucket: 'not_found', NotFound: 'not_found',
  SlowDown: 'throttled', Throttling: 'throttled', QuotaExceeded: 'quota', EntityTooLarge: 'quota',
};
const STATUS_CODES = { 401: 'authentication', 403: 'permission', 404: 'not_found', 429: 'throttled', 503: 'throttled', 507: 'quota' };

const q = (s, safe = '') => [...encodeURIComponent(s).replace(/[!'()*]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase())]
  .join('').replace(/%2F/g, safe.includes('/') ? '/' : '%2F');
const hmac = (key, msg) => createHmac('sha256', key).update(msg).digest();
const sha = (b) => createHash('sha256').update(b).digest('hex');
const tag = (xml, name) => new RegExp(`<${name}>([\\s\\S]*?)</${name}>`).exec(xml)?.[1];
const unxml = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&');

/** A resolved secret. Its string form never shows the values. */
export class Credential {
  constructor(accessKeyId, secretAccessKey, sessionToken) {
    Object.defineProperty(this, 'accessKeyId', { value: accessKeyId });
    Object.defineProperty(this, 'secretAccessKey', { value: secretAccessKey });
    Object.defineProperty(this, 'sessionToken', { value: sessionToken });
  }
  toString() { return 'Credential(<redacted>)'; }
  toJSON() { return '<redacted>'; }
  [Symbol.for('nodejs.util.inspect.custom')]() { return 'Credential(<redacted>)'; }
}

/** config: {endpoint, region, credentialRef, root, addressing: 'path'|'virtual', signingRegion?, sessionTokenRef?,
 *  allowInsecureHttp?}. No secrets: credentialRef names a secret the host resolves in the credentials callback. */
export function validateConfig(c) {
  let u;
  try { u = new URL(c.endpoint); } catch { throw new CloudError('invalid_config', 'endpoint is not a URL'); }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname);
  if (u.protocol !== 'https:' && !(c.allowInsecureHttp && loopback && u.protocol === 'http:'))
    throw new CloudError('invalid_config', 'HTTPS is required; HTTP is allowed only for an explicit loopback development endpoint.');
  if (!c.region || !c.credentialRef || !c.root) throw new CloudError('invalid_config', 'Region, credential reference and root are required.');
}

export class S3Backend {
  constructor(config, credentials, { signal, multipartThreshold = MULTIPART_THRESHOLD, partSize = PART_SIZE } = {}) {
    validateConfig(config);
    this.c = config; this.credentials = credentials; this.signal = signal;
    this.threshold = multipartThreshold; this.partSize = partSize;
    this.u = new URL(config.endpoint);
  }

  async #request(method, key = '', query = {}, body, headers = {}, signal) {
    checkSignal(this.signal); checkSignal(signal);
    const cred = await this.credentials(this.c.credentialRef, this.c.sessionTokenRef);
    const base = this.u.pathname.replace(/\/$/, '');
    const virtual = this.c.addressing === 'virtual';
    const host = virtual ? `${this.c.root}.${this.u.host}` : this.u.host;
    const path = virtual ? `${base}/${q(key, '/')}` : `${base}/${q(this.c.root)}${key ? '/' + q(key, '/') : ''}`;
    const cq = Object.keys(query).sort().map((k) => `${q(k)}=${q(String(query[k]))}`).join('&');
    const data = body ?? new Uint8Array(0);
    const now = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '');
    const day = now.slice(0, 8);
    const h = { host, 'x-amz-date': now, 'x-amz-content-sha256': body?.length ? sha(data) : EMPTY };
    if (cred.sessionToken) h['x-amz-security-token'] = cred.sessionToken;
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;
    const names = Object.keys(h).sort();
    const canon = [method, path || '/', cq, names.map((n) => `${n}:${String(h[n]).trim()}\n`).join(''), names.join(';'), h['x-amz-content-sha256']].join('\n');
    const region = this.c.signingRegion || this.c.region, scope = `${day}/${region}/s3/aws4_request`;
    const sts = ['AWS4-HMAC-SHA256', now, scope, sha(canon)].join('\n');
    const k = hmac(hmac(hmac(hmac('AWS4' + cred.secretAccessKey, day), region), 's3'), 'aws4_request');
    const sig = createHmac('sha256', k).update(sts).digest('hex');
    h.authorization = `AWS4-HMAC-SHA256 Credential=${cred.accessKeyId}/${scope}, SignedHeaders=${names.join(';')}, Signature=${sig}`;
    delete h.host;
    let res, text;
    try {
      res = await fetch(`${this.u.protocol}//${host}${path || '/'}${cq ? '?' + cq : ''}`, { method, headers: h, body: body?.length ? data : undefined, signal: signal ?? this.signal });
      text = method === 'GET' && !('uploads' in query) && !('list-type' in query) && res.ok ? null : await res.text();
    } catch (e) {
      if (e?.name === 'AbortError') throw new CloudError('cancelled', 'operation cancelled');
      throw new CloudError('network', `connection failed (${e?.cause?.code ?? e?.name ?? 'error'})`);
    }
    if (!res.ok) throw this.#error(res, text ?? '');
    return { res, text, bytes: text === null ? new Uint8Array(await res.arrayBuffer()) : null };
  }

  #error(res, body) {
    const providerCode = tag(body, 'Code');
    const code = PROVIDER_CODES[providerCode] ?? STATUS_CODES[res.status] ?? 'provider_error';
    const ra = Number(res.headers.get('retry-after'));
    return new CloudError(code, `provider answered HTTP ${res.status}${providerCode ? ' ' + providerCode : ''}`,
      { providerCode, requestId: res.headers.get('x-amz-request-id') ?? undefined, retryAfterMs: Number.isFinite(ra) && ra > 0 ? ra * 1000 : undefined });
  }

  async listPage(prefix, delimiter, token, maxKeys, signal) {
    const query = { 'list-type': '2', 'max-keys': String(maxKeys), prefix };
    if (delimiter) query.delimiter = delimiter;
    if (token) query['continuation-token'] = token;
    const { text } = await this.#request('GET', '', query, undefined, {}, signal);
    const objects = [...text.matchAll(/<Contents>([\s\S]*?)<\/Contents>/g)].map(([, c]) => ({
      key: unxml(tag(c, 'Key')), size: Number(tag(c, 'Size') ?? 0), modified: tag(c, 'LastModified'), etag: unxml(tag(c, 'ETag') ?? '').replace(/"/g, '') }));
    const prefixes = [...text.matchAll(/<CommonPrefixes>\s*<Prefix>([\s\S]*?)<\/Prefix>/g)].map((m) => unxml(m[1]));
    return { objects, prefixes, nextToken: tag(text, 'IsTruncated') === 'true' ? unxml(tag(text, 'NextContinuationToken')) : null };
  }

  async head(key, signal) {
    try {
      const { res } = await this.#request('HEAD', key, {}, undefined, {}, signal);
      return { key, size: Number(res.headers.get('content-length') ?? 0), modified: res.headers.get('last-modified'), etag: (res.headers.get('etag') ?? '').replace(/"/g, '') };
    } catch (e) {
      if (e instanceof CloudError && e.code === 'not_found') return null;
      throw e;
    }
  }

  async get(key, signal) { return (await this.#request('GET', key, {}, undefined, {}, signal)).bytes; }

  async put(key, data, signal) {
    if (data.length > this.threshold) await this.#multipart(key, data, signal);
    else await this.#request('PUT', key, {}, data, {}, signal);
    return this.head(key, signal);
  }

  async #multipart(key, data, signal) {
    const init = await this.#request('POST', key, { uploads: '' }, undefined, {}, signal);
    const uploadId = tag(init.text, 'UploadId');
    try {
      const etags = [];
      for (let off = 0, n = 1; off < data.length; off += this.partSize, n++) {
        const r = await this.#request('PUT', key, { partNumber: String(n), uploadId }, data.subarray(off, off + this.partSize), {}, signal);
        etags.push(r.res.headers.get('etag'));
      }
      const xml = '<CompleteMultipartUpload>' + etags.map((e, i) => `<Part><PartNumber>${i + 1}</PartNumber><ETag>${e}</ETag></Part>`).join('') + '</CompleteMultipartUpload>';
      await this.#request('POST', key, { uploadId }, new TextEncoder().encode(xml), {}, signal);
    } catch (e) {
      try { await this.#request('DELETE', key, { uploadId }); } catch { /* abort is best effort */ }
      throw e;
    }
  }

  async copy(src, dst, signal) {
    await this.#request('PUT', dst, {}, undefined, { 'x-amz-copy-source': `/${q(this.c.root)}/${q(src, '/')}` }, signal);
  }
  async delete(key, signal) { await this.#request('DELETE', key, {}, undefined, {}, signal); }
}
