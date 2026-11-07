// Normalized errors (spec/errors.json). Messages never carry credentials, headers, signed URLs or response bodies.
export const CODES = ['authentication', 'permission', 'not_found', 'conflict', 'confirmation_required', 'throttled', 'quota',
  'invalid_config', 'network', 'cancelled', 'unsupported', 'provider_error'];
export const RETRYABLE = ['throttled', 'network', 'provider_error'];
export const CONTRACT_VERSION = '0.1.0';

export function redact(text) {
  return String(text)
    .replace(/X-Amz-[A-Za-z-]+=[^&\s]+/gi, 'X-Amz-...=<redacted>')
    .replace(/(authorization:\s*)\S+(\s+\S+)*/gi, '$1<redacted>')
    .replace(/AKIA[0-9A-Z]{16}/g, '<redacted>');
}

export class CloudError extends Error {
  constructor(code, message = '', { providerCode, requestId, retryAfterMs } = {}) {
    if (!CODES.includes(code)) throw new TypeError('unknown error code ' + code);
    super(redact(message));
    this.name = 'CloudError';
    this.code = code; this.providerCode = providerCode; this.requestId = requestId; this.retryAfterMs = retryAfterMs;
  }
  get retry() { return RETRYABLE.includes(this.code); }
  toJSON() {
    const d = { code: this.code, message: this.message };
    if (this.providerCode != null) d.provider_code = this.providerCode;
    if (this.requestId != null) d.request_id = this.requestId;
    if (this.retryAfterMs != null) d.retry_after_ms = this.retryAfterMs;
    return d;
  }
}

/** Cancellation is an AbortSignal in options.signal; an aborted signal throws the contract's `cancelled` error. */
export function checkSignal(signal) {
  if (signal?.aborted) throw new CloudError('cancelled', 'operation cancelled');
}
