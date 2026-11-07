export type ErrorCode = 'authentication' | 'permission' | 'not_found' | 'conflict' | 'confirmation_required' | 'throttled'
  | 'quota' | 'invalid_config' | 'network' | 'cancelled' | 'unsupported' | 'provider_error';
export const CODES: readonly ErrorCode[];
export const CONTRACT_VERSION: string;
export const CAPABILITIES: readonly string[];
export function redact(text: string): string;

export class CloudError extends Error {
  constructor(code: ErrorCode, message?: string, extra?: { providerCode?: string; requestId?: string; retryAfterMs?: number });
  code: ErrorCode; providerCode?: string; requestId?: string; retryAfterMs?: number;
  readonly retry: boolean;
  toJSON(): { code: ErrorCode; message: string; provider_code?: string; request_id?: string; retry_after_ms?: number };
}

export interface CloudItem {
  root: string; path: string; name: string; kind: 'file' | 'folder';
  size: number | null; modified: string | null; etag: string | null;
}
export interface Receipt { operation: string; state: 'completed' | 'copied' | 'source_deleted' | 'partial' | 'nothing_to_do'; items: Partial<CloudItem>[] }
export interface Page { items: CloudItem[]; nextToken: string | null }
export interface Options {
  signal?: AbortSignal; root?: string; pageSize?: number; token?: string | null; limit?: number; maxBytes?: number;
  overwrite?: 'fail' | 'replace' | 'rename'; destructive?: boolean; recursive?: boolean; onResult?: (count: number) => void;
}

export interface ObjectInfo { key: string; size: number; modified: string | null; etag: string }
export interface Backend {
  listPage(prefix: string, delimiter: string | null, token: string | null, maxKeys: number, signal?: AbortSignal):
    Promise<{ objects: ObjectInfo[]; prefixes: string[]; nextToken: string | null }>;
  head(key: string, signal?: AbortSignal): Promise<ObjectInfo | null>;
  get(key: string, signal?: AbortSignal): Promise<Uint8Array>;
  put(key: string, data: Uint8Array, signal?: AbortSignal): Promise<ObjectInfo>;
  copy(src: string, dst: string, signal?: AbortSignal): Promise<void>;
  delete(key: string, signal?: AbortSignal): Promise<void>;
}

export class CloudStore {
  constructor(backend: Backend, root: string);
  backend: Backend; root: string;
  testConnection(options?: Options): Promise<{ capabilities: string[] }>;
  listRoots(): Promise<CloudItem[]>;
  list(path?: string, options?: Options): Promise<Page>;
  stat(path: string, options?: Options): Promise<CloudItem>;
  search(query: string, under?: string, options?: Options): Promise<{ items: CloudItem[]; truncated: boolean }>;
  download(path: string, options?: Options): Promise<{ content: Uint8Array; size: number }>;
  upload(path: string, data: Uint8Array | string, options?: Options): Promise<Receipt>;
  copy(path: string, to: string, options?: Options): Promise<Receipt>;
  move(path: string, to: string, options?: Options): Promise<Receipt>;
  delete(path: string, options?: Options): Promise<Receipt>;
}
export class MemoryBackend implements Backend {
  seed(key: string, data: Uint8Array | number[], modified?: string): void;
  listPage: Backend['listPage']; head: Backend['head']; get: Backend['get']; put: Backend['put']; copy: Backend['copy']; delete: Backend['delete'];
}

export class Credential {
  constructor(accessKeyId: string, secretAccessKey: string, sessionToken?: string);
  readonly accessKeyId: string; readonly secretAccessKey: string; readonly sessionToken?: string;
}
export interface S3Config {
  endpoint: string; region: string; credentialRef: string; root: string; addressing?: 'path' | 'virtual';
  signingRegion?: string; sessionTokenRef?: string; allowInsecureHttp?: boolean; provider?: string;
}
export type CredentialResolver = (credentialRef: string, sessionTokenRef?: string) => Credential | Promise<Credential>;
export class S3Backend implements Backend {
  constructor(config: S3Config, credentials: CredentialResolver, options?: { signal?: AbortSignal; multipartThreshold?: number; partSize?: number });
  listPage: Backend['listPage']; head: Backend['head']; get: Backend['get']; put: Backend['put']; copy: Backend['copy']; delete: Backend['delete'];
}
export function validateConfig(config: S3Config): void;
export function s3Store(config: S3Config, credentials: CredentialResolver, options?: { signal?: AbortSignal }): CloudStore;

export interface Preset { id: string; name: string; protocol: 's3'; classification: string; endpoint_template: string | null; region: string | null; addressing: string; caveats: string }
export function loadPresets(providersJson: string): Record<string, Preset>;
export function configFromPreset(preset: Preset, o: { root: string; credentialRef: string; endpoint?: string; region?: string; allowInsecureHttp?: boolean }): S3Config;
