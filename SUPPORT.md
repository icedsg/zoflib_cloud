# Support

What this repository supports today, by storage provider and by language. The provider table is generated from
[`spec/providers.json`](spec/providers.json); when the two disagree, the JSON is right.

## By provider

Every S3-compatible service goes through the same generic S3 adapter with a preset (endpoint, region, addressing).
The classifications are defined in `spec/providers.json`:

| Classification | Meaning | Count |
|---|---|---|
| `tested` | Passes this repository's integration tests against the provider. | 0 |
| `compatible_by_protocol` | The provider documents an S3-compatible API; the generic S3 adapter should work with the preset, but it has not been tested against the provider yet. | 24 |
| `native_planned` | Not supported yet (needs a native adapter; no S3 API). | 5 |
| `unsupported` | No public API reachable by a third-party library. | 1 |

| Provider | id | Classification | Protocol | Addressing | Notable caveats |
|---|---|---|---|---|---|
| Amazon S3 | `aws-s3` | `compatible_by_protocol` | s3 | both | Path-style is supported but scheduled for deprecation; dotted bucket names break virtual-hosted HTTPS. |
| Cloudflare R2 | `cloudflare-r2` | `compatible_by_protocol` | s3 | unknown | No ACLs, versioning, bucket policies or object tagging. |
| Wasabi Hot Cloud Storage | `wasabi` | `compatible_by_protocol` | s3 | both | Wrong regional endpoint allows reads but not writes; path-style recommended. |
| Backblaze B2 (S3 Compatible API) | `backblaze-b2` | `compatible_by_protocol` | s3 | both | No object ACLs or object tagging; HTTPS only. |
| DigitalOcean Spaces | `digitalocean-spaces` | `compatible_by_protocol` | s3 | virtual | No cross-region copy; canned ACLs only. |
| Akamai Object Storage (Linode) | `akamai-linode` | `compatible_by_protocol` | s3 | both | Legacy cluster endpoints (<cluster>.linodeobjects.com) have lower limits. |
| Vultr Object Storage | `vultr-object-storage` | `compatible_by_protocol` | s3 | virtual | S3 subset; with gzip, Content-Length may differ from the file size. |
| IBM Cloud Object Storage | `ibm-cos` | `compatible_by_protocol` | s3 | unknown | S3 subset; list returns at most 1,000 per request. |
| Oracle Cloud Infrastructure Object Storage (S3 Compatibility API) | `oci-object-storage` | `compatible_by_protocol` | s3 | both | No object ACLs; virtual-hosted uses the vhcompat host. |
| Google Cloud Storage (XML API interoperability) | `gcs-interop` | `compatible_by_protocol` | s3 | unknown | Operation coverage is not listed on the interoperability page. |
| Alibaba Cloud Object Storage Service (OSS) | `alibaba-oss` | `compatible_by_protocol` | s3 | both | No aws-chunked encoding; new mainland China accounts need a custom domain for data operations. |
| Tencent Cloud Object Storage (COS) | `tencent-cos` | `compatible_by_protocol` | s3 | both | Newer buckets may not accept path-style. |
| Huawei Cloud Object Storage Service (OBS) | `huawei-obs` | `compatible_by_protocol` | s3 | unknown | SigV4 needs unsigned or streaming payload signing; path-style is off in some regions. |
| Hetzner Object Storage | `hetzner-object-storage` | `compatible_by_protocol` | s3 | virtual | CopyObject only within one bucket. |
| Scaleway Object Storage | `scaleway-object-storage` | `compatible_by_protocol` | s3 | both | - |
| OVHcloud Object Storage | `ovhcloud` | `compatible_by_protocol` | s3 | virtual | Path-style support is not stated. |
| IDrive e2 | `idrive-e2` | `compatible_by_protocol` | s3 | path | Endpoint is per account; no ACLs. |
| Storj S3 Compatible Gateway | `storj` | `compatible_by_protocol` | s3 | path | ListMultipartUploads is partial; no ACLs or bucket policies. |
| Tigris Object Storage | `tigris` | `compatible_by_protocol` | s3 | virtual | Virtual-hosted addressing required; no PutBucketVersioning. |
| Supabase Storage (S3 protocol) | `supabase-storage` | `compatible_by_protocol` | s3 | path | S3 must be enabled in the project; access keys bypass row-level security; no versioning or tagging. |
| MinIO | `minio` | `compatible_by_protocol` | s3 | both | Path-style by default; virtual-hosted needs a server domain setting; no ACLs. |
| Ceph Object Gateway | `ceph-rgw` | `compatible_by_protocol` | s3 | both | Virtual-hosted needs rgw_dns_name and a wildcard certificate. |
| Garage | `garage` | `compatible_by_protocol` | s3 | both | No versioning, ACLs or bucket policies. |
| SeaweedFS S3 API | `seaweedfs` | `compatible_by_protocol` | s3 | both | Virtual-hosted needs a domain setting and wildcard DNS. |
| Azure Blob Storage | `azure-blob` | `native_planned` | native | - | Not supported yet (needs a native adapter; no S3 API). |
| Google Drive | `google-drive` | `native_planned` | native | - | Not supported yet (needs a native adapter; no S3 API). |
| Microsoft OneDrive and SharePoint (Microsoft Graph) | `onedrive-sharepoint` | `native_planned` | native | - | Not supported yet (needs a native adapter; no S3 API). |
| Dropbox | `dropbox` | `native_planned` | native | - | Not supported yet (needs a native adapter; no S3 API). |
| Box | `box` | `native_planned` | native | - | Not supported yet (needs a native adapter; no S3 API). |
| Apple iCloud Drive | `icloud-drive` | `unsupported` | none | - | Apple documents only on-device access (the iCloud Drive folder and app ubiquity containers on Apple platforms) and CloudKit for an app's own data; no public API for a user's iCloud Drive files from other platforms. Apps reach it as local files on Apple devices. |

Addressing is `path`, `virtual` (virtual-hosted), `both`, or `unknown` when the provider's documentation does not
say. Self-hosted servers (MinIO, Ceph, Garage, SeaweedFS) take whatever endpoint you give them. Each entry in the JSON
links the official page it was checked against (`doc_url`, `verified_at`).

## By language

| Language | Package | Runtime minimum | Version | Contract | Operations | Multipart upload |
|---|---|---|---|---|---|---|
| C# | `Zoflib.Cloud` ([packages/csharp](packages/csharp)) | .NET 10 | 0.1.0 | 0.1.0 | all 10 | Yes: seekable streams of 16 MiB or more, 8 MiB parts |
| JavaScript / TypeScript | `zoflib-cloud` ([packages/javascript](packages/javascript)) | Node 20 | 0.1.0 | 0.1.0 | all 10 | Yes: above 8 MiB, 8 MiB parts |
| Python | `zoflib-cloud` ([packages/python](packages/python)) | Python 3.9 | 0.1.0 | 0.1.0 | all 10 | Yes: above 8 MiB, 8 MiB parts |
| Kotlin | `net.biz59.zoflib.cloud:zoflib-cloud-kotlin` ([packages/kotlin](packages/kotlin)) | JDK 11; Android API 26 | 0.1.0 | 0.1.0 | all 10 | No (not advertised; uploads are a single request) |
| Swift | `ZoflibCloud` ([packages/swift](packages/swift)) | macOS 14 (the manifest also lists iOS 17; tested on macOS only) | 0.1.0 (Swift Package Manager takes versions from git tags) | 0.1.0 | all 10 | No (single PUT; `multipart_upload` is not reported) |

The 10 operations are those in `spec/contract.json`: `testConnection`, `listRoots`, `list`, `stat`, `search`,
`download`, `upload`, `copy`, `move` and `delete`, with each language's usual naming.

Every package passes the shared conformance suite (388 of 388 checks) against its in-memory backend. The JavaScript,
Python and Swift packages also pass it through their S3 adapter against `conformance/fake_s3.py`, a local fake S3
server that verifies request signatures. The C# integration test runs against a local S3 mock server and includes a
17 MiB multipart upload. The Kotlin driver runs the suite against its in-memory backend only.

Each package says which contract version it implements: `Contract.Version` (C#), `CONTRACT_VERSION` (JavaScript,
Python, Kotlin) and `contractVersion` (Swift).

## What "tested" means

A provider is `tested` only when a package's integration tests pass against that provider's real service, using a
disposable bucket. Passing the conformance suite against an in-memory store or a local fake S3 server shows that a
package follows the contract; it does not show that a given provider behaves the same way.

**No provider is `tested` yet.** All 24 S3-compatible services are `compatible_by_protocol`: they document an S3 API
and should work through the generic S3 adapter, but none of them has been run against this repository's tests.

## Reporting a provider result

If you run a package against a provider, please open an issue on this repository with:

- the provider `id` from `spec/providers.json`, and the region and addressing style you used;
- the package, its version and the contract version it reports;
- the result: the conformance count from `python conformance/run.py <driver>` with `ZOFLIB_S3_ENDPOINT`,
  `ZOFLIB_S3_ACCESS` and `ZOFLIB_S3_SECRET` pointing at a disposable bucket (for drivers that support it), or which
  operations worked and which failed, with the normalized error codes;
- anything the provider did differently from the caveats listed above.

Never include access keys, secrets, session tokens, signed URLs, bucket names that identify you, or file contents.
Use a bucket that holds no real data: the suite empties the bucket it runs against.

## Contract version policy

`contract_version` in `spec/contract.json` follows semantic versioning:

- **patch** (0.1.x): clarifications and new test cases that do not change required behaviour;
- **minor** (0.x.0): additions such as new optional operations, options, capabilities or error codes;
- **major**: changes that break packages or apps written against the previous version.

While the major version is 0, a minor release may also contain breaking changes; when it does, the spec says so.
Each package declares the contract version it implements (see "By language") and must pass the conformance suite for
that version before it is published. A package's own version and the contract version are separate numbers.
