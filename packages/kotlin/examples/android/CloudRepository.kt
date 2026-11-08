package com.example.zofle.cloud

import com.biz59.zoflib.cloud.ConnectionConfig
import com.biz59.zoflib.cloud.CredentialResolver
import com.biz59.zoflib.cloud.OperationOptions
import com.biz59.zoflib.cloud.ResolvedCredential
import com.biz59.zoflib.cloud.S3CloudStore
import java.nio.file.Path
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** The implementation decrypts values using an Android-Keystore-backed key; it must never log them. */
fun interface KeystoreSecrets { suspend fun resolve(reference: String): ResolvedCredential }

class CloudRepository(
    config: ConnectionConfig,
    secrets: KeystoreSecrets,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) : AutoCloseable {
    private val store = S3CloudStore.create(config, CredentialResolver { reference, _ -> secrets.resolve(reference) })

    suspend fun download(bucket: String, key: String, destination: Path) = withContext(io) {
        store.download(bucket, key, destination, OperationOptions(maxBytes = 2L * 1024 * 1024 * 1024))
    }

    suspend fun upload(bucket: String, key: String, source: Path) = withContext(io) {
        store.upload(bucket, key, source)
    }

    override fun close() = store.close()
}
