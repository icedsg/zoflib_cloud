import XCTest
@testable import ZoflibCloud

final class StoreTests: XCTestCase {
    func store(_ files: [String: String] = [:]) async -> (CloudStore, MemoryBackend) {
        let m = MemoryBackend()
        for (k, v) in files { await m.seed(k, Data(v.utf8)) }
        return (CloudStore(backend: m, root: "b"), m)
    }

    func testListSortsFoldersAndFiles() async throws {
        let (s, _) = await store(["a/x.txt": "1", "a/sub/y.txt": "2", "b.txt": "3"])
        let page = try await s.list("a")
        XCTAssertEqual(page.items.map(\.path), ["a/sub/", "a/x.txt"])
        XCTAssertEqual(page.items.map(\.isFolder), [true, false])
    }

    func testPagingFollowsTokens() async throws {
        let (s, _) = await store(Dictionary(uniqueKeysWithValues: (0..<5).map { ("k\($0)", "x") }))
        var o = OperationOptions(); o.pageSize = 2
        var seen: [String] = []
        repeat {
            let p = try await s.list("", o)
            seen += p.items.map(\.path); o.token = p.nextToken
        } while o.token != nil
        XCTAssertEqual(seen, ["k0", "k1", "k2", "k3", "k4"])
    }

    func testSearchIgnoresCaseAndAccentsSpelling() async throws {
        let (s, _) = await store(["d/Café.txt": "x", "d/other.txt": "y"])
        let r = try await s.search("CAFÉ")
        XCTAssertEqual(r.items.map(\.name), ["Café.txt"])
    }

    func testUploadConflictRenameReplace() async throws {
        let (s, m) = await store(["a/r.pdf": "v1"])
        do { _ = try await s.upload("a/r.pdf", Data("v2".utf8)); XCTFail() } catch let e as CloudError { XCTAssertEqual(e.code, .conflict) }
        var o = OperationOptions(); o.overwrite = .rename
        let r = try await s.upload("a/r.pdf", Data("v2".utf8), o)
        XCTAssertEqual(r.items[0].path, "a/r (1).pdf")
        o.overwrite = .replace
        _ = try await s.upload("a/r.pdf", Data("v3".utf8), o)
        let keys = await m.keys()
        XCTAssertEqual(keys, ["a/r (1).pdf", "a/r.pdf"])
    }

    func testDeleteAndMoveNeedConfirmation() async throws {
        let (s, m) = await store(["a.txt": "1"])
        do { _ = try await s.delete("a.txt"); XCTFail() } catch let e as CloudError { XCTAssertEqual(e.code, .confirmationRequired) }
        do { _ = try await s.move("a.txt", to: "b.txt"); XCTFail() } catch let e as CloudError { XCTAssertEqual(e.code, .confirmationRequired) }
        let keys = await m.keys()
        XCTAssertEqual(keys, ["a.txt"])
        var o = OperationOptions(); o.destructive = true
        let r = try await s.move("a.txt", to: "b.txt", o)
        XCTAssertEqual(r.state, .sourceDeleted)
        let after = await m.keys()
        XCTAssertEqual(after, ["b.txt"])
    }

    func testFolderDeleteNeedsRecursive() async throws {
        let (s, m) = await store(["f/a": "1", "f/b": "2"])
        var o = OperationOptions(); o.destructive = true
        do { _ = try await s.delete("f", o); XCTFail() } catch let e as CloudError { XCTAssertEqual(e.code, .conflict) }
        o.recursive = true
        _ = try await s.delete("f", o)
        let keys = await m.keys()
        XCTAssertTrue(keys.isEmpty)
    }

    func testCancelledBeforeStartChangesNothing() async throws {
        let (s, m) = await store(["a": "1"])
        var o = OperationOptions(); o.destructive = true
        let t = Task { () -> Error? in
            while !Task.isCancelled { await Task.yield() }
            do { _ = try await s.delete("a", o); return nil } catch { return error }
        }
        t.cancel()
        let err = await t.value as? CloudError
        XCTAssertEqual(err?.code, .cancelled)
        let keys = await m.keys()
        XCTAssertEqual(keys, ["a"])
    }

    func testConfigRefusesPlainHttpExceptLoopbackOptIn() throws {
        func cfg(_ e: String, _ allow: Bool) -> S3Config { S3Config(endpoint: e, region: "r", credentialRef: "c", root: "b", allowInsecureHttp: allow) }
        XCTAssertThrowsError(try cfg("http://example.com", true).validate())
        XCTAssertThrowsError(try cfg("http://127.0.0.1:9000", false).validate())
        XCTAssertNoThrow(try cfg("http://127.0.0.1:9000", true).validate())
        XCTAssertNoThrow(try cfg("https://s3.example.com", false).validate())
    }

    func testSecretsNeverPrintOrReachErrors() {
        let c = Credential(accessKeyId: "AKIA" + "ABCDEFGHIJKLMNOP", secretAccessKey: "topsecret")
        XCTAssertEqual("\(c)", "Credential(<redacted>)")
        let e = CloudError(.providerError, "failed AKIA" + "ABCDEFGHIJKLMNOP at ?X-Amz-Signature=abc123&x=1")
        XCTAssertFalse(e.message.contains("AKIA"))
        XCTAssertFalse(e.message.contains("abc123"))
    }

    func testSigV4MatchesAwsExample() {
        // AWS documentation, "GET Object" example (examplebucket/test.txt, Range header).
        let h = ["host": "examplebucket.s3.amazonaws.com", "range": "bytes=0-9", "x-amz-content-sha256": SigV4.sha256Hex(Data()),
                 "x-amz-date": "20130524T000000Z"]
        let a = SigV4.authorization(method: "GET", path: "/test.txt", query: [], headers: h, payloadHash: SigV4.sha256Hex(Data()),
                                    cred: Credential(accessKeyId: "AKIA" + "IOSFODNN7EXAMPLE", secretAccessKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"), region: "us-east-1")
        XCTAssertTrue(a.hasSuffix("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"), a)
    }
}
