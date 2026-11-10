package net.biz59.zoflib.cloud

import java.nio.file.Path

interface CloudStore : AutoCloseable {
    suspend fun testConnection(): Capabilities
    suspend fun listRoots(): List<CloudItem>
    suspend fun list(root: String, path: String = "", token: String? = null, options: OperationOptions = OperationOptions()): Page
    suspend fun stat(root: String, path: String): CloudItem
    suspend fun search(root: String, under: String, query: String, options: OperationOptions = OperationOptions()): Pair<List<CloudItem>, Boolean>
    suspend fun download(root: String, path: String, destination: Path, options: OperationOptions = OperationOptions()): CloudItem
    suspend fun upload(root: String, path: String, source: Path, options: OperationOptions = OperationOptions()): OperationReceipt
    suspend fun copy(root: String, path: String, to: String, options: OperationOptions = OperationOptions()): OperationReceipt
    suspend fun move(root: String, path: String, to: String, options: OperationOptions = OperationOptions()): OperationReceipt
    suspend fun delete(root: String, path: String, options: OperationOptions = OperationOptions()): OperationReceipt
}
