import CryptoKit
import Foundation

func sameKey(_ a: String, _ b: String) -> Bool { a.utf8.elementsEqual(b.utf8) }
public func utf8Less(_ a: String, _ b: String) -> Bool { a.utf8.lexicographicallyPrecedes(b.utf8) }

private func fold(_ s: String) -> String { s.precomposedStringWithCanonicalMapping.lowercased().precomposedStringWithCanonicalMapping }
private func nameOf(_ p: String) -> String {
    var s = Substring(p)
    while s.hasSuffix("/") { s = s.dropLast() }
    return String(s.split(separator: "/", omittingEmptySubsequences: false).last ?? "")
}
private func dirOf(_ p: String) -> String { p.isEmpty || p.hasSuffix("/") ? p : p + "/" }

/// Contract 0.1.0 over a backend. Cancel an operation by cancelling its Task.
public final class CloudStore: Sendable {
    public let backend: CloudBackend
    public let root: String

    public init(backend: CloudBackend, root: String) {
        self.backend = backend
        self.root = root
    }

    private func item(_ o: BackendObject) -> CloudItem {
        CloudItem(root: root, path: o.key, name: nameOf(o.key), kind: .file, size: o.size, modified: o.modified, etag: o.etag)
    }
    private func folder(_ prefix: String) -> CloudItem {
        CloudItem(root: root, path: prefix, name: nameOf(prefix), kind: .folder, size: nil, modified: nil, etag: nil)
    }
    private func begin(_ o: OperationOptions) throws {
        try checkCancelled()
        if let r = o.root, r != root { throw CloudError(.notFound, "unknown root") }
    }

    private func freeName(_ key: String) async throws -> String {
        let slash = key.lastIndex(of: "/")
        let dir = slash.map { String(key[...$0]) } ?? ""
        let name = slash.map { String(key[key.index(after: $0)...]) } ?? key
        let dot = name.lastIndex(of: ".")
        let (stem, ext) = dot.flatMap { $0 > name.startIndex ? (String(name[..<$0]), String(name[$0...])) : nil } ?? (name, "")
        var n = 1
        while true {
            let cand = "\(dir)\(stem) (\(n))\(ext)"
            if try await backend.head(cand) == nil { return cand }
            n += 1
        }
    }

    private func target(_ key: String, _ mode: OverwriteMode) async throws -> String {
        if try await backend.head(key) == nil { return key }
        switch mode {
        case .replace: return key
        case .rename: return try await freeName(key)
        case .fail: throw CloudError(.conflict, "target exists")
        }
    }

    private func allKeys(_ prefix: String) async throws -> [BackendObject] {
        var out: [BackendObject] = []
        var token: String?
        repeat {
            try checkCancelled()
            let page = try await backend.listPage(prefix: prefix, delimiter: nil, token: token, maxKeys: 1000)
            out += page.objects
            token = page.nextToken
        } while token != nil
        return out
    }

    private func receipt(_ op: String, _ state: ReceiptState, _ items: [CloudItem]) -> OperationReceipt {
        OperationReceipt(operation: op, state: state, items: items)
    }

    public func testConnection() async throws -> [CloudCapability] {
        _ = try await backend.listPage(prefix: "", delimiter: "/", token: nil, maxKeys: 1)
        return CloudCapability.allCases.filter { $0 != .multipartUpload }
    }

    public func listRoots() -> [CloudItem] {
        [CloudItem(root: root, path: "", name: root, kind: .folder, size: nil, modified: nil, etag: nil)]
    }

    public func list(_ path: String = "", _ options: OperationOptions = .init()) async throws -> CloudPage {
        try begin(options)
        let prefix = dirOf(path)
        let page = try await backend.listPage(prefix: prefix, delimiter: "/", token: options.token, maxKeys: max(1, options.pageSize))
        var rows = page.objects.filter { !sameKey($0.key, prefix) }.map { ($0.key, item($0)) }
        rows += page.prefixes.filter { !sameKey($0, prefix) }.map { ($0, folder($0)) }
        rows.sort { utf8Less($0.0, $1.0) }
        return CloudPage(items: rows.map(\.1), nextToken: page.nextToken)
    }

    public func stat(_ path: String, _ options: OperationOptions = .init()) async throws -> CloudItem {
        try begin(options)
        if !path.hasSuffix("/"), let o = try await backend.head(path) { return item(o) }
        let prefix = dirOf(path)
        if !prefix.isEmpty, !(try await backend.listPage(prefix: prefix, delimiter: nil, token: nil, maxKeys: 1)).objects.isEmpty {
            return folder(prefix)
        }
        throw CloudError(.notFound, "no such item")
    }

    /// `onResult(count)` fires after each result (the conformance driver uses it for cancel-after-N).
    public func search(_ query: String, under: String = "", _ options: OperationOptions = .init(),
                       onResult: (@Sendable (Int) -> Void)? = nil) async throws -> SearchResult {
        try begin(options)
        let q = fold(query)
        var items: [CloudItem] = []
        var token: String?
        repeat {
            try checkCancelled()
            let page = try await backend.listPage(prefix: under, delimiter: nil, token: token, maxKeys: 1000)
            for o in page.objects {
                if o.key.hasSuffix("/") || !fold(nameOf(o.key)).contains(q) { continue }
                try checkCancelled()
                if items.count >= options.limit { return SearchResult(items: items, truncated: true) }
                items.append(item(o))
                onResult?(items.count)
            }
            token = page.nextToken
        } while token != nil
        return SearchResult(items: items, truncated: false)
    }

    public func download(_ path: String, _ options: OperationOptions = .init()) async throws -> Data {
        try begin(options)
        guard let o = try await backend.head(path) else { throw CloudError(.notFound, "no such item") }
        if let max = options.maxBytes, o.size > max { throw CloudError(.quota, "larger than maxBytes") }
        return try await backend.get(path)
    }

    public func upload(_ path: String, _ data: Data, _ options: OperationOptions = .init()) async throws -> OperationReceipt {
        try begin(options)
        let key = try await target(path, options.overwrite)
        return receipt("upload", .completed, [item(try await backend.put(key, data))])
    }

    public func copy(_ path: String, to: String, _ options: OperationOptions = .init()) async throws -> OperationReceipt {
        try begin(options)
        guard try await backend.head(path) != nil else { throw CloudError(.notFound, "no such item") }
        let key = try await target(to, options.overwrite)
        try await backend.copy(path, to: key)
        guard let made = try await backend.head(key) else { throw CloudError(.providerError, "copy did not appear") }
        return receipt("copy", .completed, [item(made)])
    }

    public func move(_ path: String, to: String, _ options: OperationOptions = .init()) async throws -> OperationReceipt {
        try begin(options)
        if !options.destructive { throw CloudError(.confirmationRequired, "move deletes the source") }
        let r = try await copy(path, to: to, options)
        if sameKey(r.items[0].path, path) { return receipt("move", .nothingToDo, r.items) }
        do { try await backend.delete(path) } catch is CloudError { return receipt("move", .copied, r.items) }
        return receipt("move", .sourceDeleted, r.items)
    }

    public func delete(_ path: String, _ options: OperationOptions = .init()) async throws -> OperationReceipt {
        try begin(options)
        if !options.destructive { throw CloudError(.confirmationRequired, "delete needs the destructive option") }
        if !path.hasSuffix("/"), try await backend.head(path) != nil {
            try await backend.delete(path)
            return receipt("delete", .completed, [CloudItem(root: root, path: path, name: nameOf(path), kind: .file, size: nil, modified: nil, etag: nil)])
        }
        let prefix = dirOf(path)
        let keys = try await allKeys(prefix).map(\.key).sorted(by: utf8Less)
        if keys.isEmpty { throw CloudError(.notFound, "no such item") }
        if !options.recursive, keys.contains(where: { !sameKey($0, prefix) }) { throw CloudError(.conflict, "folder has contents") }
        var done: [CloudItem] = []
        for k in keys {
            if Task.isCancelled { return receipt("delete", .partial, done) }
            try await backend.delete(k)
            done.append(CloudItem(root: root, path: k, name: nameOf(k), kind: .file, size: nil, modified: nil, etag: nil))
        }
        return receipt("delete", .completed, done)
    }
}

/// In-memory object store with S3 listing behaviour; for tests and the conformance driver.
public actor MemoryBackend: CloudBackend {
    /// Keyed by the key's UTF-8 bytes: Swift's String equality treats NFC and NFD spellings as one, keys are exact.
    private var objs: [Data: (data: Data, modified: String)] = [:]

    public init() {}

    private func obj(_ key: String) -> BackendObject {
        let (d, m) = objs[Data(key.utf8)]!
        return BackendObject(key: key, size: Int64(d.count), modified: m,
                             etag: Insecure.MD5.hash(data: d).map { String(format: "%02x", $0) }.joined())
    }
    public func seed(_ key: String, _ data: Data, modified: String = "2026-01-01T00:00:00Z") { objs[Data(key.utf8)] = (data, modified) }
    public func keys() -> [String] { objs.keys.map { String(decoding: $0, as: UTF8.self) }.sorted(by: utf8Less) }

    public func listPage(prefix: String, delimiter: String?, token: String?, maxKeys: Int) async throws -> BackendPage {
        var rows: [(String, Bool)] = []
        var seen = Set<Data>()
        let pre = Data(prefix.utf8), delim = delimiter.map { Data($0.utf8) }
        for kd in objs.keys where kd.starts(with: pre) {
            let rest = kd.dropFirst(pre.count)
            if let d = delim, let r = rest.firstRange(of: d) {
                let p = pre + rest[rest.startIndex..<r.lowerBound] + d
                if seen.insert(p).inserted { rows.append((String(decoding: p, as: UTF8.self), false)) }
            } else { rows.append((String(decoding: kd, as: UTF8.self), true)) }
        }
        rows.sort { utf8Less($0.0, $1.0) }
        var start = 0
        if let t = token {
            guard let d = Data(base64Encoded: t), let s = String(data: d, encoding: .utf8), s.hasPrefix("o:"), let n = Int(s.dropFirst(2))
            else { throw CloudError(.invalidConfig, "bad continuation token") }
            start = n
        }
        let end = min(rows.count, start + maxKeys)
        let page = start < end ? Array(rows[start..<end]) : []
        return BackendPage(objects: page.filter(\.1).map { obj($0.0) }, prefixes: page.filter { !$0.1 }.map(\.0),
                           nextToken: end < rows.count ? Data("o:\(end)".utf8).base64EncodedString() : nil)
    }
    public func head(_ key: String) async throws -> BackendObject? { objs[Data(key.utf8)] == nil ? nil : obj(key) }
    public func get(_ key: String) async throws -> Data {
        guard let o = objs[Data(key.utf8)] else { throw CloudError(.notFound, "no such item") }
        return o.data
    }
    public func put(_ key: String, _ data: Data) async throws -> BackendObject {
        objs[Data(key.utf8)] = (data, "2026-06-01T00:00:00Z")
        return obj(key)
    }
    public func copy(_ src: String, to dst: String) async throws {
        guard let o = objs[Data(src.utf8)] else { throw CloudError(.notFound, "no such item") }
        objs[Data(dst.utf8)] = o
    }
    public func delete(_ key: String) async throws { objs[Data(key.utf8)] = nil }
}
