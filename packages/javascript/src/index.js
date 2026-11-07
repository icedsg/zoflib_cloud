import { CloudStore } from './core.js';
import { S3Backend } from './s3.js';

export { CloudError, CODES, CONTRACT_VERSION, redact } from './errors.js';
export { CloudStore, MemoryBackend, CAPABILITIES } from './core.js';
export { S3Backend, Credential, validateConfig } from './s3.js';
export { loadPresets, configFromPreset } from './presets.js';

/** CloudStore over generic S3. credentials(credentialRef, sessionTokenRef) -> Credential (sync or async). */
export function s3Store(config, credentials, options) {
  return new CloudStore(new S3Backend(config, credentials, options), config.root);
}
