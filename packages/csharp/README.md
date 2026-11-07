# C# package

`Zoflib.Cloud` implements contract 0.1.0 for generic S3-compatible storage. It targets .NET 10 or later and keeps
credentials outside configuration: the host resolves a credential reference only when constructing a client.

```csharp
var config = new S3ConnectionConfig(
    "minio", new Uri("https://objects.example.com"), "us-east-1", "my-secret-reference");
using var cloud = new S3CloudStore(config, async (credentialRef, tokenRef, cancellation) =>
    await secrets.ResolveS3Async(credentialRef, tokenRef, cancellation));
var page = await cloud.ListAsync("photos", "2026/", options: new(PageSize: 100), cancellationToken: ct);
```

Load the 24 data-only S3 presets from the repository catalog with
`ProviderPresets.Load("spec/providers.json")`. Presets provide documented defaults and caveats; they never contain
credentials, and `compatible_by_protocol` is not a claim that a provider has been integration-tested.

Destructive operations require `new OperationOptions(Destructive: true)`. Move is copy-then-delete and reports
`copied` if the delete half fails. HTTP is rejected unless it is explicitly enabled for a loopback development
endpoint. Errors contain normalized codes and safe provider/request identifiers, never response bodies, credentials,
authorization headers, or signed URLs.

Run package tests and shared conformance from the repository root:

```powershell
dotnet test packages/csharp/Zoflib.Cloud.Tests/Zoflib.Cloud.Tests.csproj
dotnet build packages/csharp/Zoflib.Cloud.Driver/Zoflib.Cloud.Driver.csproj
python conformance/run.py dotnet packages/csharp/Zoflib.Cloud.Driver/bin/Debug/net10.0/Zoflib.Cloud.Driver.dll
```

The generic-S3 integration test runs when `ZOFLIB_S3_ENDPOINT`, `ZOFLIB_S3_ACCESS` and `ZOFLIB_S3_SECRET` point to a
disposable endpoint. CI starts a fresh S3 mock container, exercises all operations plus a 17 MiB multipart upload, and
deletes its temporary bucket.
