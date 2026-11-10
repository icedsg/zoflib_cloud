package net.biz59.zoflib.cloud

import aws.sdk.kotlin.services.s3.S3Client
import aws.sdk.kotlin.services.s3.model.CopyObjectRequest
import aws.sdk.kotlin.services.s3.model.DeleteObjectRequest
import aws.sdk.kotlin.services.s3.model.GetObjectRequest
import aws.sdk.kotlin.services.s3.model.HeadObjectRequest
import aws.sdk.kotlin.services.s3.model.HeadBucketRequest
import aws.sdk.kotlin.services.s3.model.ListBucketsRequest
import aws.sdk.kotlin.services.s3.model.ListObjectsV2Request
import aws.sdk.kotlin.services.s3.model.NoSuchKey
import aws.sdk.kotlin.services.s3.model.PutObjectRequest
import aws.sdk.kotlin.services.s3.model.S3Exception
import aws.smithy.kotlin.runtime.auth.awscredentials.Credentials
import aws.smithy.kotlin.runtime.auth.awscredentials.CredentialsProvider
import aws.smithy.kotlin.runtime.collections.Attributes
import aws.smithy.kotlin.runtime.content.ByteStream
import aws.smithy.kotlin.runtime.content.fromFile
import aws.smithy.kotlin.runtime.content.writeToFile
import aws.smithy.kotlin.runtime.net.url.Url
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.text.Normalizer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive

class S3CloudStore private constructor(
    private val client: S3Client,
    private val configuredRoot: String? = null,
) : CloudStore {
    companion object {
        fun create(config: ConnectionConfig, resolver: CredentialResolver): S3CloudStore {
            val s3 = S3Client {
                region = config.signingRegion ?: config.region
                endpointUrl = Url.parse(config.endpoint)
                forcePathStyle = config.addressing == Addressing.PATH
                credentialsProvider = object : CredentialsProvider {
                    override suspend fun resolve(attributes: Attributes): Credentials {
                        val value = resolver.resolve(config.credentialRef, config.sessionTokenRef)
                        return Credentials(value.accessKey, value.secretKey, value.sessionToken)
                    }
                }
            }
            return S3CloudStore(s3, config.root)
        }

        fun fromClient(client: S3Client, configuredRoot: String? = null): S3CloudStore = S3CloudStore(client, configuredRoot)
    }

    override suspend fun testConnection(): Capabilities = mapped {
        if (configuredRoot != null) client.headBucket(HeadBucketRequest { bucket = configuredRoot })
        else client.listBuckets(ListBucketsRequest {})
        Capabilities(S3_CAPABILITIES)
    }

    override suspend fun listRoots(): List<CloudItem> = mapped {
        configuredRoot?.let { return@mapped listOf(CloudItem(it, "", it, ItemKind.FOLDER)) }
        client.listBuckets(ListBucketsRequest {}).buckets.orEmpty().mapNotNull { bucket ->
            bucket.name?.let { CloudItem(it, "", it, ItemKind.FOLDER) }
        }.sortedWith(compareBy(utf8Comparator) { it.root })
    }

    override suspend fun list(root: String, path: String, token: String?, options: OperationOptions): Page = mapped {
        currentCoroutineContext().ensureActive()
        val prefix = when {
            path.isEmpty() || path.endsWith('/') -> path
            else -> "$path/"
        }
        val response = client.listObjectsV2(ListObjectsV2Request {
            bucket = root
            this.prefix = prefix
            delimiter = "/"
            continuationToken = token
            maxKeys = options.pageSize.coerceIn(1, 1_000)
        })
        val files = response.contents.orEmpty().mapNotNull { obj ->
            val key = obj.key ?: return@mapNotNull null
            if (key == prefix) null else CloudItem(
                root, key, key.substringAfterLast('/'), ItemKind.FILE, obj.size,
                obj.lastModified?.toString(), obj.eTag?.trim('"')
            )
        }
        val folders = response.commonPrefixes.orEmpty().mapNotNull { common ->
            common.prefix?.let { CloudItem(root, it, it.trimEnd('/').substringAfterLast('/'), ItemKind.FOLDER) }
        }
        Page((files + folders).sortedWith(compareBy(utf8Comparator) { it.path }), response.nextContinuationToken)
    }

    override suspend fun stat(root: String, path: String): CloudItem = mapped {
        currentCoroutineContext().ensureActive()
        if (path.endsWith('/')) {
            val page = list(root, path, options = OperationOptions(pageSize = 1))
            if (page.items.isEmpty()) throw CloudException(ErrorCode.NOT_FOUND, "No such item")
            CloudItem(root, path, path.trimEnd('/').substringAfterLast('/'), ItemKind.FOLDER)
        } else {
            val response = client.headObject(HeadObjectRequest { bucket = root; key = path })
            CloudItem(root, path, path.substringAfterLast('/'), ItemKind.FILE, response.contentLength,
                response.lastModified?.toString(), response.eTag?.trim('"'), response.versionId, response.contentType,
                response.metadata.orEmpty())
        }
    }

    override suspend fun search(
        root: String,
        under: String,
        query: String,
        options: OperationOptions,
    ): Pair<List<CloudItem>, Boolean> = mapped {
        val foldedQuery = fold(query)
        val found = mutableListOf<CloudItem>()
        var token: String? = null
        do {
            currentCoroutineContext().ensureActive()
            val response = client.listObjectsV2(ListObjectsV2Request {
                bucket = root
                prefix = under
                continuationToken = token
                maxKeys = options.pageSize.coerceIn(1, 1_000)
            })
            for (obj in response.contents.orEmpty()) {
                currentCoroutineContext().ensureActive()
                val key = obj.key ?: continue
                if (fold(key.substringAfterLast('/')).contains(foldedQuery)) {
                    if (found.size >= options.limit) return@mapped found.sortedWith(compareBy(utf8Comparator) { it.path }) to true
                    found += CloudItem(root, key, key.substringAfterLast('/'), ItemKind.FILE, obj.size,
                        obj.lastModified?.toString(), obj.eTag?.trim('"'))
                }
            }
            token = response.nextContinuationToken
        } while (token != null)
        found.sortedWith(compareBy(utf8Comparator) { it.path }) to false
    }

    override suspend fun download(root: String, path: String, destination: Path, options: OperationOptions): CloudItem = mapped {
        currentCoroutineContext().ensureActive()
        val parent = destination.toAbsolutePath().parent
        Files.createDirectories(parent)
        val temporary = Files.createTempFile(parent, ".zoflib-", ".part")
        try {
            client.getObject(GetObjectRequest { bucket = root; key = path }) { response ->
                val length = response.contentLength
                if (options.maxBytes != null && length != null && length > options.maxBytes) {
                    throw CloudException(ErrorCode.QUOTA, "Object exceeds maxBytes")
                }
                response.body?.writeToFile(temporary) ?: Files.write(temporary, byteArrayOf())
            }
            currentCoroutineContext().ensureActive()
            if (options.maxBytes != null && Files.size(temporary) > options.maxBytes) {
                throw CloudException(ErrorCode.QUOTA, "Object exceeds maxBytes")
            }
            try {
                Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } catch (_: java.nio.file.AtomicMoveNotSupportedException) {
                Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING)
            }
            stat(root, path)
        } finally {
            Files.deleteIfExists(temporary)
        }
    }

    override suspend fun upload(root: String, path: String, source: Path, options: OperationOptions): OperationReceipt = mapped {
        currentCoroutineContext().ensureActive()
        val target = resolveTarget(root, path, options.overwrite)
        client.putObject(PutObjectRequest { bucket = root; key = target; body = ByteStream.fromFile(source.toFile()) })
        OperationReceipt("upload", "completed", listOf(stat(root, target)))
    }

    override suspend fun copy(root: String, path: String, to: String, options: OperationOptions): OperationReceipt = mapped {
        currentCoroutineContext().ensureActive()
        stat(root, path)
        val target = resolveTarget(root, to, options.overwrite)
        val encodedSource = root + "/" + path.split('/').joinToString("/") { encodePathPart(it) }
        val response = client.copyObject(CopyObjectRequest { bucket = root; key = target; copySource = encodedSource })
        OperationReceipt("copy", "completed", listOf(stat(root, target)), response.requestCharged?.value)
    }

    override suspend fun move(root: String, path: String, to: String, options: OperationOptions): OperationReceipt {
        if (!options.destructive) throw CloudException(ErrorCode.CONFIRMATION_REQUIRED, "Move deletes the source")
        val copied = copy(root, path, to, options)
        return try {
            client.deleteObject(DeleteObjectRequest { bucket = root; key = path })
            copied.copy(operation = "move", state = "source_deleted")
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            copied.copy(operation = "move", state = "copied")
        }
    }

    override suspend fun delete(root: String, path: String, options: OperationOptions): OperationReceipt = mapped {
        if (!options.destructive) throw CloudException(ErrorCode.CONFIRMATION_REQUIRED, "Delete needs destructive=true")
        if (path.endsWith('/')) {
            val all = mutableListOf<CloudItem>()
            var token: String? = null
            do {
                val response = client.listObjectsV2(ListObjectsV2Request {
                    bucket = root; prefix = path; continuationToken = token
                })
                all += response.contents.orEmpty().mapNotNull { it.key?.let { key -> CloudItem(root, key, key.substringAfterLast('/'), ItemKind.FILE) } }
                token = response.nextContinuationToken
            } while (token != null)
            if (all.isEmpty()) throw CloudException(ErrorCode.NOT_FOUND, "No such item")
            if (!options.recursive) throw CloudException(ErrorCode.CONFLICT, "Folder has contents")
            for (item in all) {
                currentCoroutineContext().ensureActive()
                client.deleteObject(DeleteObjectRequest { bucket = root; key = item.path })
            }
            OperationReceipt("delete", "completed", all.sortedWith(compareBy(utf8Comparator) { it.path }))
        } else {
            val item = stat(root, path)
            client.deleteObject(DeleteObjectRequest { bucket = root; key = path })
            OperationReceipt("delete", "completed", listOf(item))
        }
    }

    private suspend fun resolveTarget(root: String, wanted: String, overwrite: Overwrite): String {
        val exists = try { stat(root, wanted); true } catch (e: CloudException) {
            if (e.code == ErrorCode.NOT_FOUND) false else throw e
        }
        if (!exists || overwrite == Overwrite.REPLACE) return wanted
        if (overwrite == Overwrite.FAIL) throw CloudException(ErrorCode.CONFLICT, "Target exists")
        val slash = wanted.lastIndexOf('/')
        val folder = if (slash >= 0) wanted.substring(0, slash + 1) else ""
        val name = wanted.substring(slash + 1)
        val dot = name.lastIndexOf('.').takeIf { it > 0 } ?: name.length
        val stem = name.substring(0, dot)
        val extension = name.substring(dot)
        var number = 1
        while (true) {
            val candidate = "$folder$stem ($number)$extension"
            val taken = try { stat(root, candidate); true } catch (e: CloudException) {
                if (e.code == ErrorCode.NOT_FOUND) false else throw e
            }
            if (!taken) return candidate
            number++
        }
    }

    private suspend fun <T> mapped(block: suspend () -> T): T = try {
        block()
    } catch (error: CloudException) {
        throw error
    } catch (error: CancellationException) {
        throw CloudException(ErrorCode.CANCELLED, "Operation cancelled", cause = error)
    } catch (error: S3Exception) {
        val providerCode = error.sdkErrorMetadata.errorCode
        val code = when (providerCode) {
            "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken" -> ErrorCode.AUTHENTICATION
            "AccessDenied", "AllAccessDisabled" -> ErrorCode.PERMISSION
            "NoSuchKey", "NoSuchBucket", "NotFound" -> ErrorCode.NOT_FOUND
            "BucketAlreadyExists", "BucketAlreadyOwnedByYou", "PreconditionFailed", "OperationAborted" -> ErrorCode.CONFLICT
            "SlowDown", "Throttling", "ThrottlingException" -> ErrorCode.THROTTLED
            "QuotaExceeded", "StorageFull" -> ErrorCode.QUOTA
            else -> ErrorCode.PROVIDER_ERROR
        }
        throw CloudException(code, "S3 request failed", providerCode, error.sdkErrorMetadata.requestId, cause = error)
    } catch (error: IllegalArgumentException) {
        throw CloudException(ErrorCode.INVALID_CONFIG, error.message ?: "Invalid configuration", cause = error)
    } catch (error: Throwable) {
        throw CloudException(ErrorCode.NETWORK, "S3 request failed", cause = error)
    }

    override fun close() = client.close()

    private fun fold(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFC).lowercase()
    private fun encodePathPart(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.name()).replace("+", "%20")
}
