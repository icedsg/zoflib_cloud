using System.Globalization;
using System.Text;

namespace Zoflib.Cloud;

public sealed class MemoryCloudStore(string root = "test-bucket") : ICloudStore
{
    readonly Dictionary<string, byte[]> objects = new(StringComparer.Ordinal);
    static readonly IReadOnlySet<string> capabilities = new HashSet<string> { "list", "stat", "search", "upload", "download", "range_download", "copy", "move", "rename", "delete" };
    static int CompareUtf8(string a, string b) => ((ReadOnlySpan<byte>)Encoding.UTF8.GetBytes(a)).SequenceCompareTo(Encoding.UTF8.GetBytes(b));
    static string Name(string p) => p.TrimEnd('/').Split('/').LastOrDefault() ?? "";
    CloudItem Item(string p) => new(root, p, Name(p), CloudItemKind.File, objects[p].LongLength);
    static CloudItem Folder(string r, string p) => new(r, p, Name(p), CloudItemKind.Folder);
    void Root(string r) { if (r != root) throw new CloudException(CloudErrorCode.NotFound, "Unknown root."); }
    public void Reset(IEnumerable<(string Path, byte[] Content)> seed) { objects.Clear(); foreach (var x in seed) objects[x.Path] = x.Content; }
    public IReadOnlyList<string> Dump() => objects.Keys.Order(Comparer<string>.Create(CompareUtf8)).ToArray();
    public Task<CloudCapabilities> TestConnectionAsync(CancellationToken ct = default) { ct.ThrowIfCancellationRequested(); return Task.FromResult(new CloudCapabilities(capabilities)); }
    public Task<IReadOnlyList<CloudItem>> ListRootsAsync(CancellationToken ct = default) { ct.ThrowIfCancellationRequested(); return Task.FromResult<IReadOnlyList<CloudItem>>([Folder(root, "") with { Name = root }]); }
    public Task<CloudPage> ListAsync(string r, string path = "", string? token = null, OperationOptions? o = null, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested(); Root(r); o ??= new(); var prefix = path.Length == 0 || path.EndsWith('/') ? path : path + "/";
        var rows = new Dictionary<string, CloudItem>(StringComparer.Ordinal);
        foreach (var k in objects.Keys.Where(k => k.StartsWith(prefix, StringComparison.Ordinal) && k != prefix)) { var rest = k[prefix.Length..]; var slash = rest.IndexOf('/'); var p = slash < 0 ? k : prefix + rest[..(slash + 1)]; rows[p] = slash < 0 ? Item(k) : Folder(root, p); }
        var all = rows.Values.OrderBy(x => x.Path, Comparer<string>.Create(CompareUtf8)).ToArray(); var start = token is null ? 0 : int.Parse(Encoding.UTF8.GetString(Convert.FromBase64String(token)).Split(':')[1], CultureInfo.InvariantCulture);
        var page = all.Skip(start).Take(Math.Max(1, o.PageSize)).ToArray(); var next = start + page.Length < all.Length ? Convert.ToBase64String(Encoding.UTF8.GetBytes($"o:{start + page.Length}")) : null;
        return Task.FromResult(new CloudPage(page, next));
    }
    public Task<CloudItem> StatAsync(string r, string p, CancellationToken ct = default) { ct.ThrowIfCancellationRequested(); Root(r); if (objects.ContainsKey(p)) return Task.FromResult(Item(p)); var prefix = p.EndsWith('/') ? p : p + "/"; if (objects.Keys.Any(k => k.StartsWith(prefix, StringComparison.Ordinal))) return Task.FromResult(Folder(root, prefix)); throw new CloudException(CloudErrorCode.NotFound, "No such item."); }
    public Task<SearchResult> SearchAsync(string r, string under, string query, OperationOptions? o = null, CancellationToken ct = default) { Root(r); o ??= new(); var q = query.Normalize().ToUpperInvariant(); var all = new List<CloudItem>(); foreach (var k in Dump()) { ct.ThrowIfCancellationRequested(); if (k.StartsWith(under, StringComparison.Ordinal) && Name(k).Normalize().ToUpperInvariant().Contains(q, StringComparison.Ordinal)) all.Add(Item(k)); if (all.Count > o.Limit) return Task.FromResult(new SearchResult(all.Take(o.Limit).ToArray(), true)); } return Task.FromResult(new SearchResult(all, false)); }
    public async Task DownloadAsync(string r, string p, Stream d, OperationOptions? o = null, CancellationToken ct = default) { Root(r); if (!objects.TryGetValue(p, out var b)) throw new CloudException(CloudErrorCode.NotFound, "No such item."); if (o?.MaxBytes is long m && b.Length > m) throw new CloudException(CloudErrorCode.Quota, "Object exceeds max_bytes."); await d.WriteAsync(b, ct); }
    string Target(string p, OverwriteMode mode) { if (!objects.ContainsKey(p)) return p; if (mode == OverwriteMode.Replace) return p; if (mode == OverwriteMode.Fail) throw new CloudException(CloudErrorCode.Conflict, "Target exists."); var slash=p.LastIndexOf('/'); var dir=slash<0?"":p[..(slash+1)]; var n=slash<0?p:p[(slash+1)..]; var dot=n.LastIndexOf('.'); var stem=dot>0?n[..dot]:n; var ext=dot>0?n[dot..]:""; for(var i=1;;i++){var c=$"{dir}{stem} ({i}){ext}";if(!objects.ContainsKey(c))return c;} }
    public async Task<OperationReceipt> UploadAsync(string r,string p,Stream s,OperationOptions? o=null,CancellationToken ct=default){Root(r);o??=new();var t=Target(p,o.Overwrite);using var m=new MemoryStream();await s.CopyToAsync(m,ct);objects[t]=m.ToArray();return new("upload","completed",[Item(t)]);}
    public Task<OperationReceipt> CopyAsync(string r,string p,string to,OperationOptions? o=null,CancellationToken ct=default){ct.ThrowIfCancellationRequested();Root(r);if(!objects.TryGetValue(p,out var b))throw new CloudException(CloudErrorCode.NotFound,"No such item.");var t=Target(to,o?.Overwrite??OverwriteMode.Fail);objects[t]=b.ToArray();return Task.FromResult(new OperationReceipt("copy","completed",[Item(t)]));}
    public async Task<OperationReceipt> MoveAsync(string r,string p,string to,OperationOptions? o=null,CancellationToken ct=default){o??=new();if(!o.Destructive)throw new CloudException(CloudErrorCode.ConfirmationRequired,"Move deletes the source.");var x=await CopyAsync(r,p,to,o,ct);objects.Remove(p);return new("move","source_deleted",x.Items);}
    public Task<OperationReceipt> DeleteAsync(string r,string p,OperationOptions? o=null,CancellationToken ct=default){ct.ThrowIfCancellationRequested();Root(r);o??=new();if(!o.Destructive)throw new CloudException(CloudErrorCode.ConfirmationRequired,"Delete needs destructive=true.");var keys=objects.ContainsKey(p)?[p]:objects.Keys.Where(k=>k.StartsWith(p.EndsWith('/')?p:p+"/",StringComparison.Ordinal)).ToArray();if(keys.Length==0)throw new CloudException(CloudErrorCode.NotFound,"No such item.");if(keys.Length>1&&!o.Recursive)throw new CloudException(CloudErrorCode.Conflict,"Folder has contents.");var items=keys.Order(Comparer<string>.Create(CompareUtf8)).Select(k=>new CloudItem(root,k,Name(k),CloudItemKind.File)).ToArray();foreach(var k in keys)objects.Remove(k);return Task.FromResult(new OperationReceipt("delete","completed",items));}
}
