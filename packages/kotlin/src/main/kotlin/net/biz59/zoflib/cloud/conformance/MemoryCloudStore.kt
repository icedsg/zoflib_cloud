package net.biz59.zoflib.cloud.conformance

import net.biz59.zoflib.cloud.*
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.text.Normalizer
import java.time.Instant
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive

internal class MemoryCloudStore : CloudStore {
    data class Entry(val bytes: ByteArray, val modified: String)
    private val objects = linkedMapOf<String, Entry>()
    private val rootName = "test-bucket"

    fun reset(seed: Map<String, Entry>) { objects.clear(); objects.putAll(seed) }
    fun dump(): List<String> = objects.keys.sortedWith(utf8Comparator)
    fun bytes(path: String): ByteArray? = objects[path]?.bytes

    override suspend fun testConnection() = Capabilities(S3_CAPABILITIES)
    override suspend fun listRoots() = listOf(CloudItem(rootName, "", rootName, ItemKind.FOLDER))

    override suspend fun list(root: String, path: String, token: String?, options: OperationOptions): Page {
        checkRoot(root)
        currentCoroutineContext().ensureActive()
        val prefix = if (path.isEmpty() || path.endsWith('/')) path else "$path/"
        val folders = linkedSetOf<String>()
        val rows = mutableListOf<CloudItem>()
        for ((key, entry) in objects) {
            if (!key.startsWith(prefix) || key == prefix) continue
            val rest = key.removePrefix(prefix)
            if ('/' in rest) folders += prefix + rest.substringBefore('/') + "/"
            else rows += item(key, entry)
        }
        rows += folders.map { folder(it) }
        rows.sortWith(compareBy(utf8Comparator) { it.path })
        val start = token?.toIntOrNull() ?: 0
        val size = options.pageSize.coerceAtLeast(1)
        val page = rows.drop(start).take(size)
        return Page(page, (start + page.size).takeIf { it < rows.size }?.toString())
    }

    override suspend fun stat(root: String, path: String): CloudItem {
        checkRoot(root)
        objects[path]?.let { return item(path, it) }
        val prefix = if (path.endsWith('/')) path else "$path/"
        if (objects.keys.any { it.startsWith(prefix) }) return folder(prefix)
        throw CloudException(ErrorCode.NOT_FOUND, "No such item")
    }

    override suspend fun search(root: String, under: String, query: String, options: OperationOptions): Pair<List<CloudItem>, Boolean> {
        checkRoot(root)
        val folded = fold(query)
        val matches = mutableListOf<CloudItem>()
        for (key in dump()) {
            currentCoroutineContext().ensureActive()
            if (key.startsWith(under) && fold(key.substringAfterLast('/')).contains(folded)) {
                if (matches.size >= options.limit) return matches to true
                matches += item(key, objects.getValue(key))
            }
        }
        return matches to false
    }

    override suspend fun download(root: String, path: String, destination: Path, options: OperationOptions): CloudItem {
        val item = stat(root, path)
        val bytes = objects.getValue(path).bytes
        if (options.maxBytes != null && bytes.size > options.maxBytes) throw CloudException(ErrorCode.QUOTA, "Object exceeds maxBytes")
        currentCoroutineContext().ensureActive()
        Files.write(destination, bytes)
        return item
    }

    override suspend fun upload(root: String, path: String, source: Path, options: OperationOptions): OperationReceipt {
        checkRoot(root)
        currentCoroutineContext().ensureActive()
        val target = target(path, options.overwrite)
        objects[target] = Entry(Files.readAllBytes(source), "2026-06-01T00:00:00Z")
        return OperationReceipt("upload", "completed", listOf(item(target, objects.getValue(target))))
    }

    override suspend fun copy(root: String, path: String, to: String, options: OperationOptions): OperationReceipt {
        checkRoot(root)
        val source = objects[path] ?: throw CloudException(ErrorCode.NOT_FOUND, "No such item")
        val target = target(to, options.overwrite)
        objects[target] = source.copy(bytes = source.bytes.copyOf())
        return OperationReceipt("copy", "completed", listOf(item(target, objects.getValue(target))))
    }

    override suspend fun move(root: String, path: String, to: String, options: OperationOptions): OperationReceipt {
        if (!options.destructive) throw CloudException(ErrorCode.CONFIRMATION_REQUIRED, "Move deletes the source")
        val receipt = copy(root, path, to, options)
        objects.remove(path)
        return receipt.copy(operation = "move", state = "source_deleted")
    }

    override suspend fun delete(root: String, path: String, options: OperationOptions): OperationReceipt {
        checkRoot(root)
        if (!options.destructive) throw CloudException(ErrorCode.CONFIRMATION_REQUIRED, "Delete needs destructive=true")
        objects[path]?.let {
            objects.remove(path)
            return OperationReceipt("delete", "completed", listOf(CloudItem(root, path, path.substringAfterLast('/'), ItemKind.FILE)))
        }
        val prefix = if (path.endsWith('/')) path else "$path/"
        val keys = dump().filter { it.startsWith(prefix) }
        if (keys.isEmpty()) throw CloudException(ErrorCode.NOT_FOUND, "No such item")
        if (!options.recursive) throw CloudException(ErrorCode.CONFLICT, "Folder has contents")
        keys.forEach(objects::remove)
        return OperationReceipt("delete", "completed", keys.map { CloudItem(root, it, it.substringAfterLast('/'), ItemKind.FILE) })
    }

    private fun target(wanted: String, overwrite: Overwrite): String {
        if (wanted !in objects || overwrite == Overwrite.REPLACE) return wanted
        if (overwrite == Overwrite.FAIL) throw CloudException(ErrorCode.CONFLICT, "Target exists")
        val folder = wanted.substringBeforeLast('/', "").let { if (it.isEmpty()) "" else "$it/" }
        val name = wanted.substringAfterLast('/')
        val dot = name.lastIndexOf('.').takeIf { it > 0 } ?: name.length
        val stem = name.substring(0, dot)
        val extension = name.substring(dot)
        var n = 1
        while ("$folder$stem ($n)$extension" in objects) n++
        return "$folder$stem ($n)$extension"
    }

    private fun checkRoot(root: String) { if (root != rootName) throw CloudException(ErrorCode.NOT_FOUND, "Unknown root") }
    private fun folder(path: String) = CloudItem(rootName, path, path.trimEnd('/').substringAfterLast('/'), ItemKind.FOLDER)
    private fun item(path: String, entry: Entry) = CloudItem(
        rootName, path, path.substringAfterLast('/'), ItemKind.FILE, entry.bytes.size.toLong(), entry.modified,
        MessageDigest.getInstance("MD5").digest(entry.bytes).joinToString("") { "%02x".format(it) }
    )
    private fun fold(value: String) = Normalizer.normalize(value, Normalizer.Form.NFC).lowercase()
    override fun close() = Unit
}
