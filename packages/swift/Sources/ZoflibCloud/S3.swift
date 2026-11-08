import CryptoKit
import Foundation

/// A resolved secret. Its description never shows the values.
public struct Credential: Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    let accessKeyId: String
    let secretAccessKey: String
    let sessionToken: String?
    public init(accessKeyId: String, secretAccessKey: String, sessionToken: String? = nil) {
        self.accessKeyId = accessKeyId; self.secretAccessKey = secretAccessKey; self.sessionToken = sessionToken
    }
    public var description: String { "Credential(<redacted>)" }
    public var debugDescription: String { description }
}

public enum Addressing: String, Sendable { case path, virtual }

/// No secrets: `credentialRef` names a secret the host resolves in the credentials callback (Keychain on Apple).
public struct S3Config: Sendable {
    public var endpoint: String
    public var region: String
    public var signingRegion: String?
    public var credentialRef: String
    public var sessionTokenRef: String?
    public var root: String
    public var addressing: Addressing = .path
    public var allowInsecureHttp = false

    public init(endpoint: String, region: String, credentialRef: String, root: String, addressing: Addressing = .path,
                signingRegion: String? = nil, sessionTokenRef: String? = nil, allowInsecureHttp: Bool = false) {
        self.endpoint = endpoint; self.region = region; self.credentialRef = credentialRef; self.root = root
        self.addressing = addressing; self.signingRegion = signingRegion; self.sessionTokenRef = sessionTokenRef
        self.allowInsecureHttp = allowInsecureHttp
    }

    /// HTTPS only; plain HTTP for an explicit loopback development endpoint.
    public func validate() throws {
        guard let u = URL(string: endpoint), let host = u.host, !host.isEmpty else { throw CloudError(.invalidConfig, "endpoint is not a URL") }
        let loopback = ["localhost", "127.0.0.1", "::1"].contains(host)
        if u.scheme != "https", !(allowInsecureHttp && loopback && u.scheme == "http") {
            throw CloudError(.invalidConfig, "HTTPS is required; HTTP is allowed only for an explicit loopback development endpoint.")
        }
        if region.isEmpty || credentialRef.isEmpty || root.isEmpty { throw CloudError(.invalidConfig, "Region, credential reference and root are required.") }
    }
}

public typealias CredentialProvider = @Sendable (_ ref: String, _ sessionTokenRef: String?) async throws -> Credential

/// AWS Signature Version 4 (Authorization header).
enum SigV4 {
    static func hex<D: Sequence>(_ bytes: D) -> String where D.Element == UInt8 { bytes.map { String(format: "%02x", $0) }.joined() }
    static func sha256Hex(_ data: Data) -> String { hex(SHA256.hash(data: data)) }
    private static func hmac(_ key: Data, _ s: String) -> Data {
        Data(HMAC<SHA256>.authenticationCode(for: Data(s.utf8), using: SymmetricKey(data: key)))
    }

    /// RFC 3986 as S3 wants it; '/' kept in paths.
    static func encode(_ s: String, keepSlash: Bool) -> String {
        var out = ""
        for b in s.utf8 {
            if (b >= 0x41 && b <= 0x5A) || (b >= 0x61 && b <= 0x7A) || (b >= 0x30 && b <= 0x39) || b == 0x2D || b == 0x5F || b == 0x2E
                || b == 0x7E || (keepSlash && b == 0x2F) {
                out.append(Character(Unicode.Scalar(b)))
            } else { out += String(format: "%%%02X", b) }
        }
        return out
    }

    static func stamp(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        return f.string(from: d)
    }

    static func authorization(method: String, path: String, query: [(String, String)], headers: [String: String],
                              payloadHash: String, cred: Credential, region: String) -> String {
        let lower = Dictionary(headers.map { ($0.key.lowercased(), $0.value.trimmingCharacters(in: .whitespaces)) }, uniquingKeysWith: { $1 })
        let stamp = lower["x-amz-date"] ?? ""
        let day = String(stamp.prefix(8))
        let cq = query.map { (encode($0.0, keepSlash: false), encode($0.1, keepSlash: false)) }
            .sorted { $0.0 != $1.0 ? $0.0 < $1.0 : $0.1 < $1.1 }.map { "\($0.0)=\($0.1)" }.joined(separator: "&")
        let names = lower.keys.sorted()
        let canonical = [method, path.isEmpty ? "/" : path, cq, names.map { "\($0):\(lower[$0]!)\n" }.joined(), names.joined(separator: ";"), payloadHash]
            .joined(separator: "\n")
        let scope = "\(day)/\(region)/s3/aws4_request"
        let toSign = "AWS4-HMAC-SHA256\n\(stamp)\n\(scope)\n\(sha256Hex(Data(canonical.utf8)))"
        let key = hmac(hmac(hmac(hmac(Data("AWS4\(cred.secretAccessKey)".utf8), day), region), "s3"), "aws4_request")
        return "AWS4-HMAC-SHA256 Credential=\(cred.accessKeyId)/\(scope), SignedHeaders=\(names.joined(separator: ";")), Signature=\(hex(hmac(key, toSign)))"
    }
}

/// Generic S3-compatible backend. Single PUT uploads (no multipart yet: `multipart_upload` is not reported).
public final class S3Backend: CloudBackend, @unchecked Sendable {
    let config: S3Config
    let credentials: CredentialProvider
    let session: URLSession
    static let emptyHash = SigV4.sha256Hex(Data())

    public init(config: S3Config, credentials: @escaping CredentialProvider, session: URLSession = .shared) throws {
        try config.validate()
        self.config = config; self.credentials = credentials; self.session = session
    }

    private static let providerCodes: [String: CloudErrorCode] = [
        "InvalidAccessKeyId": .authentication, "SignatureDoesNotMatch": .authentication, "ExpiredToken": .authentication,
        "AccessDenied": .permission, "NoSuchKey": .notFound, "NoSuchBucket": .notFound, "NotFound": .notFound,
        "SlowDown": .throttled, "Throttling": .throttled, "QuotaExceeded": .quota, "EntityTooLarge": .quota,
    ]
    private static let statusCodes: [Int: CloudErrorCode] = [401: .authentication, 403: .permission, 404: .notFound, 429: .throttled, 503: .throttled, 507: .quota]

    private func send(_ method: String, _ key: String = "", query: [(String, String)] = [], body: Data? = nil,
                       headers extra: [String: String] = [:]) async throws -> (Data, HTTPURLResponse) {
        try checkCancelled()
        let cred = try await credentials(config.credentialRef, config.sessionTokenRef)
        guard let base = URL(string: config.endpoint) else { throw CloudError(.invalidConfig, "endpoint is not a URL") }
        let basePath = base.path.hasSuffix("/") ? String(base.path.dropLast()) : base.path
        let virtual = config.addressing == .virtual
        let hostName = base.host! + (base.port.map { ":\($0)" } ?? "")
        let host = virtual ? "\(config.root).\(hostName)" : hostName
        let rawPath = virtual ? "\(basePath)/\(key)" : "\(basePath)/\(config.root)" + (key.isEmpty ? "" : "/\(key)")
        let path = SigV4.encode(rawPath.isEmpty ? "/" : rawPath, keepSlash: true)
        let payload = body.map { SigV4.sha256Hex($0) } ?? Self.emptyHash
        var h = ["host": host, "x-amz-date": SigV4.stamp(Date()), "x-amz-content-sha256": payload]
        if let t = cred.sessionToken { h["x-amz-security-token"] = t }
        for (k, v) in extra { h[k.lowercased()] = v }
        let qs = query.isEmpty ? "" : "?" + query.sorted { $0.0 < $1.0 }
            .map { "\(SigV4.encode($0.0, keepSlash: false))=\(SigV4.encode($0.1, keepSlash: false))" }.joined(separator: "&")
        guard let url = URL(string: "\(base.scheme!)://\(host)\(path)\(qs)") else { throw CloudError(.invalidConfig, "bad request URL") }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(SigV4.authorization(method: method, path: path, query: query, headers: h, payloadHash: payload, cred: cred,
                                         region: config.signingRegion ?? config.region), forHTTPHeaderField: "Authorization")
        for (k, v) in h where k != "host" { req.setValue(v, forHTTPHeaderField: k) }
        do {
            let (data, res) = if let body { try await session.upload(for: req, from: body) } else { try await session.data(for: req) }
            let http = res as! HTTPURLResponse
            if !(200..<300).contains(http.statusCode) { throw Self.error(http, data) }
            return (data, http)
        } catch let e as CloudError { throw e }
        catch let e as URLError {
            if e.code == .cancelled { throw CloudError(.cancelled, "operation cancelled") }
            throw CloudError(.network, "connection failed (\(e.code.rawValue))")
        } catch is CancellationError { throw CloudError(.cancelled, "operation cancelled") }
    }

    private static func tag(_ xml: String, _ name: String) -> String? {
        guard let a = xml.range(of: "<\(name)>"), let b = xml.range(of: "</\(name)>", range: a.upperBound..<xml.endIndex) else { return nil }
        return String(xml[a.upperBound..<b.lowerBound])
    }

    private static func error(_ res: HTTPURLResponse, _ data: Data) -> CloudError {
        let body = String(decoding: data, as: UTF8.self)
        let pc = tag(body, "Code")
        let code = pc.flatMap { providerCodes[$0] } ?? statusCodes[res.statusCode] ?? .providerError
        let ra = Double(res.value(forHTTPHeaderField: "Retry-After") ?? "").map { Int($0 * 1000) }
        return CloudError(code, "provider answered HTTP \(res.statusCode)" + (pc.map { " \($0)" } ?? ""), providerCode: pc,
                          requestId: res.value(forHTTPHeaderField: "x-amz-request-id"), retryAfterMs: ra)
    }

    public func listPage(prefix: String, delimiter: String?, token: String?, maxKeys: Int) async throws -> BackendPage {
        var q = [("list-type", "2"), ("max-keys", String(maxKeys)), ("prefix", prefix)]
        if let d = delimiter { q.append(("delimiter", d)) }
        if let t = token { q.append(("continuation-token", t)) }
        let (data, _) = try await send("GET", query: q)
        let p = ListParser()
        let xml = XMLParser(data: data)
        xml.delegate = p
        guard xml.parse() else { throw CloudError(.providerError, "unreadable list answer") }
        return BackendPage(objects: p.objects, prefixes: p.prefixes, nextToken: p.truncated ? p.next : nil)
    }

    public func head(_ key: String) async throws -> BackendObject? {
        do {
            let (_, r) = try await send("HEAD", key)
            return BackendObject(key: key, size: Int64(r.value(forHTTPHeaderField: "Content-Length") ?? "") ?? 0,
                                 modified: r.value(forHTTPHeaderField: "Last-Modified"),
                                 etag: (r.value(forHTTPHeaderField: "ETag") ?? "").replacingOccurrences(of: "\"", with: ""))
        } catch let e as CloudError where e.code == .notFound { return nil }
    }

    public func get(_ key: String) async throws -> Data { try await send("GET", key).0 }

    public func put(_ key: String, _ data: Data) async throws -> BackendObject {
        _ = try await send("PUT", key, body: data, headers: ["content-length": String(data.count)])
        guard let o = try await head(key) else { throw CloudError(.providerError, "upload did not appear") }
        return o
    }

    public func copy(_ src: String, to dst: String) async throws {
        _ = try await send("PUT", dst, headers: ["x-amz-copy-source": "/" + SigV4.encode(config.root, keepSlash: false) + "/" + SigV4.encode(src, keepSlash: true)])
    }

    public func delete(_ key: String) async throws { _ = try await send("DELETE", key) }
}

/// ListObjectsV2 answer: Contents (Key, Size, LastModified, ETag) and CommonPrefixes.
private final class ListParser: NSObject, XMLParserDelegate {
    var objects: [BackendObject] = []
    var prefixes: [String] = []
    var truncated = false
    var next: String?
    private var stack: [String] = []
    private var text = ""
    private var cur: (key: String, size: Int64, modified: String?, etag: String) = ("", 0, nil, "")

    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?, qualifiedName: String?, attributes: [String: String] = [:]) {
        stack.append(name); text = ""
        if name == "Contents" { cur = ("", 0, nil, "") }
    }
    func parser(_ parser: XMLParser, foundCharacters string: String) { text += string }
    func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName: String?) {
        defer { stack.removeLast() }
        let parent = stack.count >= 2 ? stack[stack.count - 2] : ""
        switch (parent, name) {
        case ("Contents", "Key"): cur.key = text
        case ("Contents", "Size"): cur.size = Int64(text) ?? 0
        case ("Contents", "LastModified"): cur.modified = text
        case ("Contents", "ETag"): cur.etag = text.replacingOccurrences(of: "\"", with: "")
        case ("CommonPrefixes", "Prefix"): prefixes.append(text)
        case (_, "Contents"): objects.append(BackendObject(key: cur.key, size: cur.size, modified: cur.modified, etag: cur.etag))
        case ("ListBucketResult", "IsTruncated"): truncated = text == "true"
        case ("ListBucketResult", "NextContinuationToken"): next = text
        default: break
        }
    }
}
