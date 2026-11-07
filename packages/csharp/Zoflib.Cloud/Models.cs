namespace Zoflib.Cloud;

public static class Contract { public const string Version = "0.1.0"; }
public enum CloudItemKind { File, Folder }
public enum OverwriteMode { Fail, Replace, Rename }

public sealed record CloudItem(string Root, string Path, string Name, CloudItemKind Kind,
    long? Size = null, DateTimeOffset? Modified = null, string? ETag = null,
    string? VersionId = null, string? ContentType = null,
    IReadOnlyDictionary<string, string>? Metadata = null);
public sealed record CloudPage(IReadOnlyList<CloudItem> Items, string? NextToken);
public sealed record SearchResult(IReadOnlyList<CloudItem> Items, bool Truncated);
public sealed record OperationReceipt(string Operation, string State, IReadOnlyList<CloudItem> Items,
    string? RequestId = null, IReadOnlyDictionary<string, string>? Undo = null);
public sealed record CloudCapabilities(IReadOnlySet<string> Values);
public sealed record OperationOptions(int PageSize = 1000, int Limit = 1000, long? MaxBytes = null,
    OverwriteMode Overwrite = OverwriteMode.Fail, bool Destructive = false, bool Recursive = false);

public enum CloudErrorCode { Authentication, Permission, NotFound, Conflict, Throttled, Quota,
    InvalidConfig, Network, Cancelled, Unsupported, ProviderError, ConfirmationRequired }
public sealed class CloudException(CloudErrorCode code, string message, string? providerCode = null,
    string? requestId = null, Exception? inner = null) : Exception(message, inner)
{
    public CloudErrorCode Code { get; } = code;
    public string? ProviderCode { get; } = providerCode;
    public string? RequestId { get; } = requestId;
}

public interface ICloudStore
{
    Task<CloudCapabilities> TestConnectionAsync(CancellationToken cancellationToken = default);
    Task<IReadOnlyList<CloudItem>> ListRootsAsync(CancellationToken cancellationToken = default);
    Task<CloudPage> ListAsync(string root, string path = "", string? token = null, OperationOptions? options = null, CancellationToken cancellationToken = default);
    Task<CloudItem> StatAsync(string root, string path, CancellationToken cancellationToken = default);
    Task<SearchResult> SearchAsync(string root, string under, string query, OperationOptions? options = null, CancellationToken cancellationToken = default);
    Task DownloadAsync(string root, string path, Stream destination, OperationOptions? options = null, CancellationToken cancellationToken = default);
    Task<OperationReceipt> UploadAsync(string root, string path, Stream content, OperationOptions? options = null, CancellationToken cancellationToken = default);
    Task<OperationReceipt> CopyAsync(string root, string path, string to, OperationOptions? options = null, CancellationToken cancellationToken = default);
    Task<OperationReceipt> MoveAsync(string root, string path, string to, OperationOptions? options = null, CancellationToken cancellationToken = default);
    Task<OperationReceipt> DeleteAsync(string root, string path, OperationOptions? options = null, CancellationToken cancellationToken = default);
}
