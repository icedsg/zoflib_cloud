// node examples/basic.mjs  (set S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY)
import { s3Store, Credential, CloudError } from '../src/index.js';

// The host resolves the reference (OS keychain, secret manager, env). Never hard-code keys.
const resolve = async () => new Credential(process.env.S3_ACCESS_KEY, process.env.S3_SECRET_KEY);
const store = s3Store({ endpoint: process.env.S3_ENDPOINT ?? 'https://s3.eu-central-1.amazonaws.com', region: 'eu-central-1',
  credentialRef: 'env:S3', root: process.env.S3_BUCKET ?? 'my-bucket', addressing: 'virtual' }, resolve);

const ctl = new AbortController(); // ctl.abort() cancels the call in flight
try {
  console.log((await store.testConnection()).capabilities);
  for (const item of (await store.list('photos/', { pageSize: 50, signal: ctl.signal })).items) console.log(item.kind, item.path);
  console.log((await store.search('invoice')).items.map((i) => i.path));
  await store.upload('hello.txt', 'hello', { overwrite: 'rename' });
  await store.delete('hello.txt', { destructive: true });
} catch (e) {
  if (e instanceof CloudError) console.log(e.code, e.message, e.retry ? '(retry)' : ''); else throw e;
}
