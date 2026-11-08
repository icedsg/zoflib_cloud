package com.biz59.zoflib.cloud.conformance

import com.biz59.zoflib.cloud.*
import java.nio.file.Files
import java.util.Base64
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*

private val json = Json { encodeDefaults = true; explicitNulls = true; ignoreUnknownKeys = true }

fun main() = runBlocking {
    val store = MemoryCloudStore()
    val reader = System.`in`.bufferedReader(Charsets.UTF_8)
    while (true) {
        val line = reader.readLine() ?: break
        if (line.isBlank()) continue
        val request = json.parseToJsonElement(line).jsonObject
        val id = request["id"] ?: JsonNull
        val response = try {
            val result = execute(store, request)
            buildJsonObject { put("id", id); put("ok", true); put("result", result) }
        } catch (error: CloudException) {
            buildJsonObject {
                put("id", id); put("ok", false)
                putJsonObject("error") { put("code", error.code.wire); put("message", error.message ?: error.code.wire) }
            }
        } catch (error: Throwable) {
            buildJsonObject {
                put("id", id); put("ok", false)
                putJsonObject("error") { put("code", "provider_error"); put("message", error.message ?: "driver error") }
            }
        }
        println(json.encodeToString(response))
        System.out.flush()
    }
}

private suspend fun execute(store: MemoryCloudStore, request: JsonObject): JsonElement {
    val op = request.getValue("op").jsonPrimitive.content
    val args = request["args"]?.jsonObject ?: JsonObject(emptyMap())
    val optionsJson = request["options"]?.jsonObject ?: JsonObject(emptyMap())
    if ((optionsJson["cancel"] as? JsonPrimitive)?.contentOrNull == "before" && op !in setOf("reset", "dump")) {
        throw CloudException(ErrorCode.CANCELLED, "Cancelled before start")
    }
    val options = OperationOptions(
        pageSize = optionsJson["page_size"]?.jsonPrimitive?.intOrNull ?: 1_000,
        limit = optionsJson["limit"]?.jsonPrimitive?.intOrNull ?: 1_000,
        maxBytes = optionsJson["max_bytes"]?.jsonPrimitive?.longOrNull,
        overwrite = when (optionsJson["overwrite"]?.jsonPrimitive?.contentOrNull) {
            "replace" -> Overwrite.REPLACE; "rename" -> Overwrite.RENAME; else -> Overwrite.FAIL
        },
        destructive = optionsJson["destructive"]?.jsonPrimitive?.booleanOrNull ?: false,
        recursive = optionsJson["recursive"]?.jsonPrimitive?.booleanOrNull ?: false,
    )
    fun root() = args["root"]?.jsonPrimitive?.content ?: "test-bucket"
    return when (op) {
        "reset" -> {
            val seed = args["seed"]?.jsonArray.orEmpty().associate { element ->
                val row = element.jsonObject
                val bytes = row["content_b64"]?.jsonPrimitive?.contentOrNull?.let(Base64.getDecoder()::decode)
                    ?: row["content"]?.jsonPrimitive?.content.orEmpty().encodeToByteArray()
                row.getValue("path").jsonPrimitive.content to MemoryCloudStore.Entry(
                    bytes, row["modified"]?.jsonPrimitive?.contentOrNull ?: "2026-01-01T00:00:00Z"
                )
            }
            store.reset(seed)
            buildJsonObject { put("count", seed.size) }
        }
        "dump" -> JsonArray(store.dump().map(::JsonPrimitive))
        "testConnection" -> json.encodeToJsonElement(store.testConnection())
        "listRoots" -> json.encodeToJsonElement(store.listRoots())
        "list" -> json.encodeToJsonElement(store.list(root(), args["path"]?.jsonPrimitive?.content ?: "", args["token"]?.jsonPrimitive?.contentOrNull, options))
        "stat" -> json.encodeToJsonElement(store.stat(root(), args.getValue("path").jsonPrimitive.content))
        "search" -> {
            val cancelAfter = optionsJson["cancel"]?.jsonObject?.get("after_items")?.jsonPrimitive?.intOrNull
            val actual = if (cancelAfter != null) options.copy(limit = maxOf(options.limit, cancelAfter + 1)) else options
            val (items, truncated) = store.search(root(), args["under"]?.jsonPrimitive?.content ?: "", args.getValue("query").jsonPrimitive.content, actual)
            if (cancelAfter != null && items.size >= cancelAfter) throw CloudException(ErrorCode.CANCELLED, "Cancelled after $cancelAfter items")
            buildJsonObject { put("items", json.encodeToJsonElement(items)); put("truncated", truncated) }
        }
        "download" -> {
            val temp = Files.createTempFile("zoflib-driver-", ".bin")
            try {
                val item = store.download(root(), args.getValue("path").jsonPrimitive.content, temp, options)
                val bytes = Files.readAllBytes(temp)
                buildJsonObject { put("content_b64", Base64.getEncoder().encodeToString(bytes)); put("size", item.size!!) }
            } finally { Files.deleteIfExists(temp) }
        }
        "upload" -> {
            val bytes = args["content_b64"]?.jsonPrimitive?.contentOrNull?.let(Base64.getDecoder()::decode)
                ?: args["content"]?.jsonPrimitive?.content.orEmpty().encodeToByteArray()
            val temp = Files.createTempFile("zoflib-driver-", ".bin")
            try { Files.write(temp, bytes); json.encodeToJsonElement(store.upload(root(), args.getValue("path").jsonPrimitive.content, temp, options)) }
            finally { Files.deleteIfExists(temp) }
        }
        "copy" -> json.encodeToJsonElement(store.copy(root(), args.getValue("path").jsonPrimitive.content, args.getValue("to").jsonPrimitive.content, options))
        "move" -> json.encodeToJsonElement(store.move(root(), args.getValue("path").jsonPrimitive.content, args.getValue("to").jsonPrimitive.content, options))
        "delete" -> json.encodeToJsonElement(store.delete(root(), args.getValue("path").jsonPrimitive.content, options))
        else -> throw CloudException(ErrorCode.UNSUPPORTED, "Unknown operation")
    }
}
