// Data-only S3 presets from spec/providers.json. Presets hold defaults and caveats, never credentials.
import { readFileSync } from 'node:fs';

export function loadPresets(providersJson) {
  const data = JSON.parse(readFileSync(providersJson, 'utf8'));
  return Object.fromEntries(data.providers.filter((p) => p.protocol === 's3').map((p) => [p.id, p]));
}

/** Build an S3 config. Self-hosted presets need an explicit endpoint; templates with <placeholders> must be filled in. */
export function configFromPreset(preset, { root, credentialRef, endpoint, region, ...rest }) {
  endpoint ??= preset.endpoint_template;
  if (!endpoint || endpoint.includes('<')) throw new TypeError(`${preset.id} needs an explicit endpoint (template: ${preset.endpoint_template})`);
  return { endpoint, region: region ?? preset.region ?? 'us-east-1', credentialRef, root,
    addressing: preset.addressing === 'virtual' ? 'virtual' : 'path', provider: preset.id, ...rest };
}
