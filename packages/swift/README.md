# ZoflibCloud for Swift

Swift implementation of the zoflib cloud contract for macOS 14+ (the manifest also lists iOS 17). The package
implements contract `0.1.0` (`contractVersion`) and has a generic S3-compatible adapter that signs requests with
SigV4 over `URLSession`; it has no other dependencies.

## Add the package

The repository root has a `Package.swift`, so Swift Package Manager can add it by its git URL. Versions come from git
tags:

```swift
dependencies: [
    .package(url: "https://github.com/icedsg/zoflib_cloud", from: "0.1.0"),
],
targets: [
    .target(name: "MyApp", dependencies: [.product(name: "ZoflibCloud", package: "zoflib_cloud")]),
]
```

In Xcode, use File > Add Package Dependencies with the same URL. The root manifest and `packages/swift/Package.swift`
build the same sources; keep them in step.

## Build and test

From the repository root or from this folder:

```shell
swift build
swift test
python3 conformance/run.py .build/debug/ZoflibCloudDriver
```

(From this folder the suite is `../../conformance/run.py`.) The conformance driver uses an in-memory store by
default and never contacts a provider. With `ZOFLIB_S3_ENDPOINT`, `ZOFLIB_S3_ACCESS` and `ZOFLIB_S3_SECRET` set it
runs the suite through the S3 adapter instead, for example against `conformance/fake_s3.py`. Real-provider testing
must use a disposable bucket.

## Connect to S3

```swift
let config = S3Config(
    endpoint: "https://account-id.r2.cloudflarestorage.com",
    region: "auto",
    credentialRef: "cloud/main",
    root: "my-bucket"
)
let backend = try S3Backend(config: config) { credentialRef, sessionTokenRef in
    try await secretStore.credential(for: credentialRef, sessionToken: sessionTokenRef)
}
let store = CloudStore(backend: backend, root: "my-bucket")

var options = OperationOptions()
options.pageSize = 100
let page = try await store.list("photos/", options)
let data = try await store.download(page.items[0].path)
```

Credentials are requested through the `CredentialProvider` closure for each request and are never serialized or
printed by the package (`Credential` redacts itself). Keep keys in the Keychain and pass only references in
`S3Config`. HTTPS is required; plain HTTP is allowed only for a loopback endpoint with `allowInsecureHttp`.

Uploads are a single PUT and downloads return `Data`; multipart upload is not advertised. Move/rename is copy then
delete and requires `destructive = true`. Delete also requires that flag; deleting a non-empty folder additionally
requires `recursive = true`. Copy and move fail when the destination exists unless `overwrite` says otherwise.
