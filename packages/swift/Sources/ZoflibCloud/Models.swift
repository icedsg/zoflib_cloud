import Foundation

public enum CloudCapability: String, Sendable, CaseIterable {
    case list, stat, search, upload, download, copy, move, rename, delete
    case multipartUpload = "multipart_upload"
}

public enum ItemKind: String, Sendable { case file, folder }

public struct CloudItem: Sendable, Equatable, Identifiable {
    public var root: String
    public var path: String
    public var name: String
    public var kind: ItemKind
    public var size: Int64?
    public var modified: String?
    public var etag: String?
    public var id: String { root + "/" + path }
    public var isFolder: Bool { kind == .folder }
}

public struct CloudPage: Sendable, Equatable {
    public var items: [CloudItem]
    public var nextToken: String?
}

public struct SearchResult: Sendable, Equatable {
    public var items: [CloudItem]
    public var truncated: Bool
}

public enum OverwriteMode: String, Sendable { case fail, replace, rename }

public struct OperationOptions: Sendable {
    public var root: String?
    public var pageSize = 1000
    public var limit = 1000
    public var maxBytes: Int64?
    public var overwrite: OverwriteMode = .fail
    /// delete and the delete half of move refuse to run without it.
    public var destructive = false
    public var recursive = false
    public var token: String?
    public init() {}
}

public enum ReceiptState: String, Sendable { case completed, copied, sourceDeleted = "source_deleted", partial, nothingToDo = "nothing_to_do" }

public struct OperationReceipt: Sendable, Equatable {
    public var operation: String
    public var state: ReceiptState
    public var items: [CloudItem]
}

/// What a backend answers for one object.
public struct BackendObject: Sendable, Equatable {
    public var key: String
    public var size: Int64
    public var modified: String?
    public var etag: String
}

public struct BackendPage: Sendable {
    public var objects: [BackendObject]
    public var prefixes: [String]
    public var nextToken: String?
    public init(objects: [BackendObject], prefixes: [String], nextToken: String?) {
        self.objects = objects; self.prefixes = prefixes; self.nextToken = nextToken
    }
}

/// Keys are full object keys. Backends throw CloudError.
public protocol CloudBackend: Sendable {
    func listPage(prefix: String, delimiter: String?, token: String?, maxKeys: Int) async throws -> BackendPage
    func head(_ key: String) async throws -> BackendObject?
    func get(_ key: String) async throws -> Data
    func put(_ key: String, _ data: Data) async throws -> BackendObject
    func copy(_ src: String, to dst: String) async throws
    func delete(_ key: String) async throws
}
