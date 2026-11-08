package com.biz59.zoflib.cloud.conformance

import com.biz59.zoflib.cloud.*
import java.nio.file.Files
import kotlin.test.*
import kotlinx.coroutines.runBlocking

class MemoryCloudStoreTest {
    @Test fun `safe mutation rename pagination and file transfers`() = runBlocking {
        val store = MemoryCloudStore()
        store.reset(mapOf(
            "a/report.txt" to MemoryCloudStore.Entry("one".encodeToByteArray(), "2026-01-01T00:00:00Z"),
            "a/z.txt" to MemoryCloudStore.Entry("z".encodeToByteArray(), "2026-01-01T00:00:00Z"),
        ))
        val first = store.list("test-bucket", "a/", options = OperationOptions(pageSize = 1))
        assertEquals(1, first.items.size)
        assertNotNull(first.nextToken)

        val source = Files.createTempFile("zoflib-test-", ".txt")
        val destination = Files.createTempFile("zoflib-test-out-", ".txt")
        try {
            Files.writeString(source, "two")
            val receipt = store.upload("test-bucket", "a/report.txt", source, OperationOptions(overwrite = Overwrite.RENAME))
            assertEquals("a/report (1).txt", receipt.items.single().path)
            store.download("test-bucket", "a/report (1).txt", destination)
            assertEquals("two", Files.readString(destination))
        } finally { Files.deleteIfExists(source); Files.deleteIfExists(destination) }

        val error = assertFailsWith<CloudException> { store.delete("test-bucket", "a/report.txt") }
        assertEquals(ErrorCode.CONFIRMATION_REQUIRED, error.code)
        store.move("test-bucket", "a/report.txt", "moved.txt", OperationOptions(destructive = true))
        assertEquals("one", store.bytes("moved.txt")!!.decodeToString())
    }

    @Test fun `search is normalized and bounded`() = runBlocking {
        val store = MemoryCloudStore()
        store.reset(mapOf(
            "x/cafe\u0301.txt" to MemoryCloudStore.Entry(byteArrayOf(), "2026-01-01T00:00:00Z"),
            "x/CAFÉ-2.txt" to MemoryCloudStore.Entry(byteArrayOf(), "2026-01-01T00:00:00Z"),
        ))
        val (items, truncated) = store.search("test-bucket", "x/", "café", OperationOptions(limit = 1))
        assertEquals(1, items.size)
        assertTrue(truncated)
    }
}
