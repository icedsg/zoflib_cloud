// Conformance driver (conformance/README.md): swift run ZoflibCloudDriver
// Memory backend by default. With ZOFLIB_S3_ENDPOINT, ZOFLIB_S3_ACCESS and ZOFLIB_S3_SECRET set it talks to that
// disposable S3-compatible endpoint (bucket test-bucket, emptied by `reset`); never point it at real data.
import Foundation
import ZoflibCloud

let root = "test-bucket"
let env = ProcessInfo.processInfo.environment
let backend: CloudBackend
if let endpoint = env["ZOFLIB_S3_ENDPOINT"] {
    let cred = Credential(accessKeyId: env["ZOFLIB_S3_ACCESS"] ?? "", secretAccessKey: env["ZOFLIB_S3_SECRET"] ?? "")
    let config = S3Config(endpoint: endpoint, region: "us-east-1", credentialRef: "env", root: root, allowInsecureHttp: true)
    backend = try S3Backend(config: config, credentials: { _, _ in cred })
} else { backend = MemoryBackend() }
let store = CloudStore(backend: backend, root: root)

func bytes(_ a: [String: Any]) -> Data {
    if let b = a["content_b64"] as? String { return Data(base64Encoded: b) ?? Data() }
    return Data((a["content"] as? String ?? "").utf8)
}

func allKeys() async throws -> [String] {
    var out: [String] = []; var token: String?
    repeat {
        let p = try await backend.listPage(prefix: "", delimiter: nil, token: token, maxKeys: 1000)
        out += p.objects.map(\.key); token = p.nextToken
    } while token != nil
    return out.sorted(by: utf8Less)
}

func wire(_ i: CloudItem) -> [String: Any] {
    ["root": i.root, "path": i.path, "name": i.name, "kind": i.kind.rawValue, "size": i.size as Any? ?? NSNull(),
     "modified": i.modified as Any? ?? NSNull(), "etag": i.etag as Any? ?? NSNull()]
}
func wire(_ r: OperationReceipt) -> [String: Any] { ["operation": r.operation, "state": r.state.rawValue, "items": r.items.map(wire)] }

/// Cancels the running operation once n results were produced.
final class Canceller: @unchecked Sendable {
    private let lock = NSLock()
    private var task: Task<SearchResult, Error>?
    private var cancelled = false
    func set(_ t: Task<SearchResult, Error>) { lock.lock(); task = t; let c = cancelled; lock.unlock(); if c { t.cancel() } }
    func cancel() { lock.lock(); cancelled = true; let t = task; lock.unlock(); t?.cancel() }
}

func handle(_ req: [String: Any]) async throws -> Any {
    let op = req["op"] as? String ?? ""
    let a = req["args"] as? [String: Any] ?? [:], o = req["options"] as? [String: Any] ?? [:]
    var opts = OperationOptions()
    opts.root = a["root"] as? String
    opts.pageSize = o["page_size"] as? Int ?? 1000
    opts.limit = o["limit"] as? Int ?? 1000
    opts.maxBytes = (o["max_bytes"] as? Int).map(Int64.init)
    opts.overwrite = OverwriteMode(rawValue: o["overwrite"] as? String ?? "fail") ?? .fail
    opts.destructive = o["destructive"] as? Bool ?? false
    opts.recursive = o["recursive"] as? Bool ?? false
    opts.token = a["token"] as? String
    let path = a["path"] as? String ?? ""
    if (o["cancel"] as? String) == "before", op != "reset", op != "dump" { throw CloudError(.cancelled, "cancelled before start") }
    switch op {
    case "reset":
        for k in try await allKeys() { try await backend.delete(k) }
        let seed = a["seed"] as? [[String: Any]] ?? []
        for s in seed { _ = try await backend.put(s["path"] as! String, bytes(s)) }
        return ["count": seed.count]
    case "dump": return try await allKeys()
    case "testConnection": return ["capabilities": try await store.testConnection().map(\.rawValue)]
    case "listRoots": return store.listRoots().map(wire)
    case "list":
        let p = try await store.list(path, opts)
        return ["items": p.items.map(wire), "next_token": p.nextToken as Any? ?? NSNull()]
    case "stat": return wire(try await store.stat(path, opts))
    case "search":
        var onResult: (@Sendable (Int) -> Void)?
        let box = Canceller()
        if let c = o["cancel"] as? [String: Any], let n = c["after_items"] as? Int {
            onResult = { count in if count >= n { box.cancel() } }
        }
        let query = a["query"] as? String ?? "", under = a["under"] as? String ?? ""
        let t = Task<SearchResult, Error> { try await store.search(query, under: under, opts, onResult: onResult) }
        box.set(t)
        let r = try await t.value
        return ["items": r.items.map(wire), "truncated": r.truncated]
    case "download":
        let d = try await store.download(path, opts)
        return ["content_b64": d.base64EncodedString(), "size": d.count]
    case "upload": return wire(try await store.upload(path, bytes(a), opts))
    case "copy": return wire(try await store.copy(path, to: a["to"] as? String ?? "", opts))
    case "move": return wire(try await store.move(path, to: a["to"] as? String ?? "", opts))
    case "delete": return wire(try await store.delete(path, opts))
    default: throw CloudError(.unsupported, "unknown operation")
    }
}

while let line = readLine() {
    if line.trimmingCharacters(in: .whitespaces).isEmpty { continue }
    guard let req = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { continue }
    var resp: [String: Any] = ["id": req["id"] as Any]
    do { resp["ok"] = true; resp["result"] = try await handle(req) } catch let e as CloudError {
        var err: [String: Any] = ["code": e.code.rawValue, "message": e.message]
        if let p = e.providerCode { err["provider_code"] = p }
        if let r = e.requestId { err["request_id"] = r }
        if let r = e.retryAfterMs { err["retry_after_ms"] = r }
        resp = ["id": req["id"] as Any, "ok": false, "error": err]
    } catch { resp = ["id": req["id"] as Any, "ok": false, "error": ["code": "provider_error", "message": "internal error"]] }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: resp) + Data("\n".utf8))
}
