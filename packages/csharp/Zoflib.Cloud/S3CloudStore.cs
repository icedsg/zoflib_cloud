using Amazon;
using Amazon.Runtime;
using Amazon.S3;
using Amazon.S3.Model;
using System.Globalization;
using System.Net;
using System.Text;
using System.Xml;

namespace Zoflib.Cloud;

public sealed class S3CloudStore : ICloudStore, IDisposable
{
    const long MultipartThreshold = 16L * 1024 * 1024, PartSize = 8L * 1024 * 1024;
    readonly S3ConnectionConfig config;
    readonly IAmazonS3 s3;
    static readonly IReadOnlySet<string> caps = new HashSet<string> { "list", "stat", "search", "upload", "multipart_upload", "download", "range_download", "copy", "move", "rename", "delete" };

    public S3CloudStore(S3ConnectionConfig config, CredentialResolver credentials) : this(config, Build(config, credentials)) { }
    internal S3CloudStore(S3ConnectionConfig config, IAmazonS3 client) { config.Validate(); this.config = config; s3 = client; }
    static IAmazonS3 Build(S3ConnectionConfig c, CredentialResolver resolver)
    {
        c.Validate(); var secret = resolver(c.CredentialReference, c.SessionTokenReference, CancellationToken.None).AsTask().GetAwaiter().GetResult();
        AWSCredentials creds = secret.SessionToken is null ? new BasicAWSCredentials(secret.AccessKeyId, secret.SecretAccessKey) : new SessionAWSCredentials(secret.AccessKeyId, secret.SecretAccessKey, secret.SessionToken);
        var cfg = new AmazonS3Config { ServiceURL = c.Endpoint.ToString().TrimEnd('/'), ForcePathStyle = c.Addressing != S3Addressing.Virtual, AuthenticationRegion = c.SigningRegion ?? c.Region };
        return new AmazonS3Client(creds, cfg);
    }
    public void Dispose() => s3.Dispose();
    static string Name(string p) => p.TrimEnd('/').Split('/').LastOrDefault() ?? "";
    static CloudItem Item(string root, S3Object x) => new(root, x.Key, Name(x.Key), CloudItemKind.File, x.Size, x.LastModified, x.ETag?.Trim('"'));
    static CloudItem Folder(string root, string p) => new(root, p, Name(p), CloudItemKind.Folder);
    static int CompareUtf8(CloudItem a, CloudItem b) => ((ReadOnlySpan<byte>)Encoding.UTF8.GetBytes(a.Path)).SequenceCompareTo(Encoding.UTF8.GetBytes(b.Path));
    async Task<T> Safe<T>(Func<Task<T>> call)
    {
        try { return await call().ConfigureAwait(false); }
        catch (OperationCanceledException e) { throw new CloudException(CloudErrorCode.Cancelled, "Operation cancelled.", inner: e); }
        catch (AmazonS3Exception e) { throw Normalize(e); }
        catch (HttpRequestException e) { throw new CloudException(CloudErrorCode.Network, "S3 endpoint could not be reached.", inner: e); }
    }
    static CloudException Normalize(AmazonS3Exception e)
    {
        var code = e.StatusCode switch { HttpStatusCode.Unauthorized => CloudErrorCode.Authentication, HttpStatusCode.Forbidden => CloudErrorCode.Permission, HttpStatusCode.NotFound => CloudErrorCode.NotFound, HttpStatusCode.Conflict => CloudErrorCode.Conflict, HttpStatusCode.TooManyRequests => CloudErrorCode.Throttled, _ => e.ErrorCode switch { "NoSuchKey" or "NoSuchBucket" => CloudErrorCode.NotFound, "AccessDenied" => CloudErrorCode.Permission, "InvalidAccessKeyId" or "SignatureDoesNotMatch" => CloudErrorCode.Authentication, "SlowDown" => CloudErrorCode.Throttled, _ => CloudErrorCode.ProviderError } };
        return new CloudException(code, $"S3 request failed ({e.StatusCode}).", e.ErrorCode, e.RequestId, e);
    }
    public async Task<CloudCapabilities> TestConnectionAsync(CancellationToken ct = default) { await ListRootsAsync(ct); return new(caps); }
    public async Task<IReadOnlyList<CloudItem>> ListRootsAsync(CancellationToken ct = default)
    {
        if (config.Root is not null) return [Folder(config.Root, "") with { Name = config.Root }];
        var r = await Safe(() => s3.ListBucketsAsync(ct)); return r.Buckets.Select(b => Folder(b.BucketName, "") with { Name = b.BucketName }).ToArray();
    }
    public async Task<CloudPage> ListAsync(string root, string path = "", string? token = null, OperationOptions? o = null, CancellationToken ct = default)
    {
        o ??= new(); var prefix = path.Length == 0 || path.EndsWith('/') ? path : path + "/";
        var r = await Safe(() => s3.ListObjectsV2Async(new ListObjectsV2Request { BucketName = root, Prefix = prefix, Delimiter = "/", ContinuationToken = token, MaxKeys = Math.Clamp(o.PageSize, 1, 1000) }, ct));
        var items = r.S3Objects.Select(x => Item(root, x)).Concat(r.CommonPrefixes.Select(p => Folder(root, p))).ToList(); items.Sort(CompareUtf8);
        return new(items, r.IsTruncated ? r.NextContinuationToken : null);
    }
    public async Task<CloudItem> StatAsync(string root, string path, CancellationToken ct = default)
    {
        try { var r = await Safe(() => s3.GetObjectMetadataAsync(new GetObjectMetadataRequest { BucketName = root, Key = path }, ct)); return new(root, path, Name(path), CloudItemKind.File, r.ContentLength, r.LastModified, r.ETag?.Trim('"'), r.VersionId, r.Headers.ContentType); }
        catch (CloudException e) when (e.Code == CloudErrorCode.NotFound) { var p = path.EndsWith('/') ? path : path + "/"; var page = await ListAsync(root, p, o: new(PageSize: 1), ct: ct); if (page.Items.Count > 0) return Folder(root, p); throw; }
    }
    public async Task<SearchResult> SearchAsync(string root, string under, string query, OperationOptions? o = null, CancellationToken ct = default)
    {
        o ??= new(); var found = new List<CloudItem>(); string? token = null; var q = query.Normalize().ToUpperInvariant();
        do { ct.ThrowIfCancellationRequested(); var r = await Safe(() => s3.ListObjectsV2Async(new ListObjectsV2Request { BucketName = root, Prefix = under, ContinuationToken = token, MaxKeys = Math.Clamp(o.PageSize, 1, 1000) }, ct)); foreach (var x in r.S3Objects) { if (!Name(x.Key).Normalize().ToUpperInvariant().Contains(q, StringComparison.Ordinal)) continue; if (found.Count >= o.Limit) return new(found, true); found.Add(Item(root, x)); } token = r.IsTruncated ? r.NextContinuationToken : null; } while (token is not null);
        found.Sort(CompareUtf8); return new(found, false);
    }
    public async Task DownloadAsync(string root, string path, Stream destination, OperationOptions? o = null, CancellationToken ct = default)
    {
        using var r = await Safe(() => s3.GetObjectAsync(new GetObjectRequest { BucketName = root, Key = path }, ct)); if (o?.MaxBytes is long m && r.ContentLength > m) throw new CloudException(CloudErrorCode.Quota, "Object exceeds max_bytes."); await r.ResponseStream.CopyToAsync(destination, ct);
    }
    async Task<string> FreeName(string root, string path, CancellationToken ct) { try { await StatAsync(root, path, ct); } catch (CloudException e) when (e.Code == CloudErrorCode.NotFound) { return path; } var slash=path.LastIndexOf('/');var dir=slash<0?"":path[..(slash+1)];var n=slash<0?path:path[(slash+1)..];var dot=n.LastIndexOf('.');var stem=dot>0?n[..dot]:n;var ext=dot>0?n[dot..]:"";for(var i=1;;i++){var p=$"{dir}{stem} ({i}){ext}";try{await StatAsync(root,p,ct);}catch(CloudException e)when(e.Code==CloudErrorCode.NotFound){return p;}} }
    async Task<string> Target(string root,string path,OverwriteMode mode,CancellationToken ct){try{await StatAsync(root,path,ct);if(mode==OverwriteMode.Fail)throw new CloudException(CloudErrorCode.Conflict,"Target exists.");if(mode==OverwriteMode.Rename)return await FreeName(root,path,ct);return path;}catch(CloudException e)when(e.Code==CloudErrorCode.NotFound){return path;}}
    public async Task<OperationReceipt> UploadAsync(string root, string path, Stream content, OperationOptions? o = null, CancellationToken ct = default)
    {
        o ??= new(); var target = await Target(root,path,o.Overwrite,ct); if (!content.CanSeek || content.Length < MultipartThreshold) { var r=await Safe(()=>s3.PutObjectAsync(new PutObjectRequest{BucketName=root,Key=target,InputStream=content,AutoCloseStream=false},ct)); return new("upload","completed",[await StatAsync(root,target,ct)],r.ResponseMetadata?.RequestId); }
        var init=await Safe(()=>s3.InitiateMultipartUploadAsync(new InitiateMultipartUploadRequest{BucketName=root,Key=target},ct));var parts=new List<PartETag>();try{for(var n=1;content.Position<content.Length;n++){ct.ThrowIfCancellationRequested();var size=Math.Min(PartSize,content.Length-content.Position);var p=await Safe(()=>s3.UploadPartAsync(new UploadPartRequest{BucketName=root,Key=target,UploadId=init.UploadId,PartNumber=n,PartSize=size,InputStream=content},ct));parts.Add(new(n,p.ETag));}var done=await Safe(()=>s3.CompleteMultipartUploadAsync(new CompleteMultipartUploadRequest{BucketName=root,Key=target,UploadId=init.UploadId,PartETags=parts},ct));return new("upload","completed",[await StatAsync(root,target,ct)],done.ResponseMetadata?.RequestId);}catch{await s3.AbortMultipartUploadAsync(new AbortMultipartUploadRequest{BucketName=root,Key=target,UploadId=init.UploadId},CancellationToken.None);throw;}
    }
    public async Task<OperationReceipt> CopyAsync(string root,string path,string to,OperationOptions? o=null,CancellationToken ct=default){o??=new();await StatAsync(root,path,ct);var target=await Target(root,to,o.Overwrite,ct);var r=await Safe(()=>s3.CopyObjectAsync(new CopyObjectRequest{SourceBucket=root,SourceKey=path,DestinationBucket=root,DestinationKey=target},ct));return new("copy","completed",[await StatAsync(root,target,ct)],r.ResponseMetadata?.RequestId);}
    public async Task<OperationReceipt> MoveAsync(string root,string path,string to,OperationOptions? o=null,CancellationToken ct=default){o??=new();if(!o.Destructive)throw new CloudException(CloudErrorCode.ConfirmationRequired,"Move deletes the source.");var c=await CopyAsync(root,path,to,o,ct);try{await Safe(()=>s3.DeleteObjectAsync(root,path,ct));return new("move","source_deleted",c.Items,c.RequestId);}catch(CloudException){return new("move","copied",c.Items,c.RequestId);}}
    public async Task<OperationReceipt> DeleteAsync(string root,string path,OperationOptions? o=null,CancellationToken ct=default){o??=new();if(!o.Destructive)throw new CloudException(CloudErrorCode.ConfirmationRequired,"Delete needs destructive=true.");var st=await StatAsync(root,path,ct);if(st.Kind==CloudItemKind.Folder){if(!o.Recursive)throw new CloudException(CloudErrorCode.Conflict,"Folder has contents.");var keys=new List<string>();string? token=null;do{var r=await Safe(()=>s3.ListObjectsV2Async(new ListObjectsV2Request{BucketName=root,Prefix=st.Path,ContinuationToken=token},ct));keys.AddRange(r.S3Objects.Select(x=>x.Key));token=r.IsTruncated?r.NextContinuationToken:null;}while(token is not null);foreach(var k in keys)await Safe(()=>s3.DeleteObjectAsync(root,k,ct));return new("delete","completed",keys.Select(k=>new CloudItem(root,k,Name(k),CloudItemKind.File)).ToArray());}var d=await Safe(()=>s3.DeleteObjectAsync(root,path,ct));return new("delete","completed",[st],d.ResponseMetadata?.RequestId);}
}
