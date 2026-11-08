import Foundation

/// Contract version this package implements.
public let contractVersion = "0.1.0"

/// Normalized error codes (spec/errors.json).
public enum CloudErrorCode: String, Sendable, CaseIterable {
    case authentication, permission, conflict, throttled, quota, network, cancelled, unsupported
    case notFound = "not_found"
    case confirmationRequired = "confirmation_required"
    case invalidConfig = "invalid_config"
    case providerError = "provider_error"

    public var retryable: Bool { self == .throttled || self == .network || self == .providerError }
}

/// Messages never carry credentials, headers, signed URLs or response bodies.
public struct CloudError: Error, LocalizedError, Sendable, Equatable {
    public let code: CloudErrorCode
    public let message: String
    public let providerCode: String?
    public let requestId: String?
    public let retryAfterMs: Int?

    public init(_ code: CloudErrorCode, _ message: String = "", providerCode: String? = nil, requestId: String? = nil,
                retryAfterMs: Int? = nil) {
        self.code = code
        self.message = redact(message)
        self.providerCode = providerCode
        self.requestId = requestId
        self.retryAfterMs = retryAfterMs
    }

    public var errorDescription: String? { message }
    public var retry: Bool { code.retryable }
}

public func redact(_ text: String) -> String {
    var s = text
    for (pattern, template) in [("X-Amz-[A-Za-z-]+=[^&\\s]+", "X-Amz-...=<redacted>"),
                                ("(?i)(authorization:\\s*)\\S+(\\s+\\S+)*", "$1<redacted>"),
                                ("AKIA[0-9A-Z]{16}", "<redacted>")] {
        s = s.replacingOccurrences(of: pattern, with: template, options: .regularExpression)
    }
    return s
}

/// A cancelled task turns into the contract's `cancelled` error.
func checkCancelled() throws {
    if Task.isCancelled { throw CloudError(.cancelled, "operation cancelled") }
}
