# zoflib-cloud for Kotlin

Kotlin/JVM and Android API 26+ implementation of the zoflib cloud contract. The package implements contract
`0.1.0` and uses the official AWS SDK for Kotlin for generic S3-compatible storage.

## Build and test

Use Gradle with JDK 11 or newer:

```shell
gradle test installDist
python ../../conformance/run.py build/install/zoflib-cloud/bin/zoflib-cloud
```

On Windows, use the generated `.bat` launcher in the last command. The shared conformance driver uses an in-memory
store and fake credentials; it never contacts a provider. Real-provider testing must use a disposable bucket.

## Connect to S3

```kotlin
val store = S3CloudStore.create(
    ConnectionConfig(
        provider = "cloudflare-r2",
        endpoint = "https://account-id.r2.cloudflarestorage.com",
        region = "auto",
        root = "my-bucket",
        credentialRef = "cloud/main",
    )
) { credentialRef, sessionTokenRef ->
    secretStore.resolveS3(credentialRef, sessionTokenRef)
}

store.use {
    val page = it.list("my-bucket", "photos/", options = OperationOptions(pageSize = 100))
    it.download("my-bucket", page.items.first().path, destinationFile)
}
```

`upload` reads from a file-backed stream, and `download` writes a temporary file then replaces the destination.
Both are suspending operations and respond to coroutine cancellation. Credentials are requested through
`CredentialResolver` for SDK requests and are not serialized by the package. HTTPS is required unless a caller
explicitly enables development-only HTTP.

S3 move/rename is copy then delete and requires `destructive = true`. Delete also requires that flag; deleting a
non-empty prefix additionally requires `recursive = true`. Multipart upload is not advertised yet.

## Android

The AWS SDK for Kotlin supports Android API 24+; this package's file APIs require API 26+, while Zofle targets
Android 13+. Keep secrets in Android Keystore (or encrypted storage backed by it), expose only opaque references in `ConnectionConfig`, create the client in a
repository/service scope, and close it when that scope ends. Do not place access keys in resources, `Bundle`, saved
state, logs, WorkManager input, or Compose state.

See [`examples/android/CloudRepository.kt`](examples/android/CloudRepository.kt) for a lifecycle-safe example using
an injected Keystore-backed resolver and file-based streaming. The example intentionally has no Android UI or APK.

Provider defaults and caveats are loaded from `spec/providers.json` with `ProviderPresets.load(inputStream)`, which
accepts an Android asset stream as well as a JVM resource stream.
