package net.biz59.zoflib.cloud

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

const val CONTRACT_VERSION = "0.1.0"

@Serializable
enum class ItemKind { @SerialName("file") FILE, @SerialName("folder") FOLDER }

@Serializable
data class CloudItem(
    val root: String,
    val path: String,
    val name: String,
    val kind: ItemKind,
    val size: Long? = null,
    val modified: String? = null,
    val etag: String? = null,
    @SerialName("version_id") val versionId: String? = null,
    @SerialName("content_type") val contentType: String? = null,
    val metadata: Map<String, String> = emptyMap(),
)

@Serializable data class Page(val items: List<CloudItem>, @SerialName("next_token") val nextToken: String? = null)

enum class Overwrite { FAIL, REPLACE, RENAME }

data class OperationOptions(
    val deadlineMs: Long? = null,
    val pageSize: Int = 1_000,
    val limit: Int = 1_000,
    val maxBytes: Long? = null,
    val overwrite: Overwrite = Overwrite.FAIL,
    val destructive: Boolean = false,
    val recursive: Boolean = false,
)

@Serializable
data class OperationReceipt(
    val operation: String,
    val state: String,
    val items: List<CloudItem>,
    @SerialName("request_id") val requestId: String? = null,
    val undo: Map<String, String>? = null,
)

@Serializable data class Capabilities(val capabilities: Set<String>)

enum class Addressing { PATH, VIRTUAL }

data class ConnectionConfig(
    val provider: String,
    val endpoint: String,
    val region: String,
    val signingRegion: String? = null,
    val addressing: Addressing = Addressing.PATH,
    val root: String? = null,
    val credentialRef: String,
    val sessionTokenRef: String? = null,
    val allowInsecureHttp: Boolean = false,
) {
    init {
        require(endpoint.startsWith("https://") || allowInsecureHttp) {
            "Plain HTTP requires allowInsecureHttp for local development"
        }
    }
}

data class ResolvedCredential(val accessKey: String, val secretKey: String, val sessionToken: String? = null)
fun interface CredentialResolver { suspend fun resolve(reference: String, sessionTokenReference: String?): ResolvedCredential }

enum class ErrorCode(val wire: String) {
    AUTHENTICATION("authentication"), PERMISSION("permission"), NOT_FOUND("not_found"), CONFLICT("conflict"),
    CONFIRMATION_REQUIRED("confirmation_required"), THROTTLED("throttled"), QUOTA("quota"),
    INVALID_CONFIG("invalid_config"), NETWORK("network"), CANCELLED("cancelled"), UNSUPPORTED("unsupported"),
    PROVIDER_ERROR("provider_error")
}

class CloudException(
    val code: ErrorCode,
    message: String,
    val providerCode: String? = null,
    val requestId: String? = null,
    val retryAfterMs: Long? = null,
    cause: Throwable? = null,
) : Exception(message, cause)

val S3_CAPABILITIES = setOf(
    "list", "stat", "search", "upload", "download", "copy", "move",
    "rename", "delete"
)

internal val utf8Comparator = Comparator<String> { a, b ->
    val aa = a.encodeToByteArray()
    val bb = b.encodeToByteArray()
    for (i in 0 until minOf(aa.size, bb.size)) {
        val compared = (aa[i].toInt() and 0xff).compareTo(bb[i].toInt() and 0xff)
        if (compared != 0) return@Comparator compared
    }
    aa.size.compareTo(bb.size)
}
