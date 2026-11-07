using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Zoflib.Cloud;

var store = new MemoryCloudStore();
var json = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
json.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower));
while (Console.ReadLine() is { } line)
{
    if (string.IsNullOrWhiteSpace(line)) continue;
    using var doc = JsonDocument.Parse(line); var req = doc.RootElement; var id = req.GetProperty("id").GetInt32();
    try
    {
        var op=req.GetProperty("op").GetString()!;var a=req.GetProperty("args");var o=req.GetProperty("options");
        if(o.TryGetProperty("cancel",out var cancel)&&cancel.ValueKind==JsonValueKind.String&&cancel.GetString()=="before"&&op is not("reset"or"dump"))throw new CloudException(CloudErrorCode.Cancelled,"Cancelled before start.");
        object result=op switch{
            "reset"=>Reset(a),"dump"=>store.Dump(),"testConnection"=>new{capabilities=(await store.TestConnectionAsync()).Values},"listRoots"=>await store.ListRootsAsync(),
            "list"=>await store.ListAsync(S(a,"root"),S(a,"path",""),S(a,"token",null),Opts(o)),"stat"=>await store.StatAsync(S(a,"root"),S(a,"path")),
            "search"=>await Search(a,o),"download"=>await Download(a,o),"upload"=>await Upload(a,o),
            "copy"=>await store.CopyAsync(S(a,"root"),S(a,"path"),S(a,"to"),Opts(o)),"move"=>await store.MoveAsync(S(a,"root"),S(a,"path"),S(a,"to"),Opts(o)),
            "delete"=>await store.DeleteAsync(S(a,"root"),S(a,"path"),Opts(o)),_=>throw new CloudException(CloudErrorCode.Unsupported,"Unknown operation.")};
        Console.WriteLine(JsonSerializer.Serialize(new{id,ok=true,result},json));
    }
    catch(CloudException e){Console.WriteLine(JsonSerializer.Serialize(new{id,ok=false,error=new{code=Code(e.Code),message=e.Message,provider_code=e.ProviderCode,request_id=e.RequestId}},json));}
    catch(OperationCanceledException){Console.WriteLine(JsonSerializer.Serialize(new{id,ok=false,error=new{code="cancelled",message="Operation cancelled."}},json));}
}

object Reset(JsonElement a){var seed=new List<(string,byte[])>();foreach(var x in a.GetProperty("seed").EnumerateArray()){var b=x.TryGetProperty("content_b64",out var v)?Convert.FromBase64String(v.GetString()!):Encoding.UTF8.GetBytes(S(x,"content",""));seed.Add((S(x,"path"),b));}store.Reset(seed);return new{count=seed.Count};}
async Task<object> Download(JsonElement a,JsonElement o){using var m=new MemoryStream();await store.DownloadAsync(S(a,"root"),S(a,"path"),m,Opts(o));return new{content_b64=Convert.ToBase64String(m.ToArray()),size=m.Length};}
async Task<object> Upload(JsonElement a,JsonElement o){var b=a.TryGetProperty("content_b64",out var v)?Convert.FromBase64String(v.GetString()!):Encoding.UTF8.GetBytes(S(a,"content",""));using var m=new MemoryStream(b);return await store.UploadAsync(S(a,"root"),S(a,"path"),m,Opts(o));}
async Task<object> Search(JsonElement a,JsonElement o){var r=await store.SearchAsync(S(a,"root"),S(a,"under",""),S(a,"query"),Opts(o));if(o.TryGetProperty("cancel",out var c)&&c.ValueKind==JsonValueKind.Object&&c.TryGetProperty("after_items",out var n)&&r.Items.Count>=n.GetInt32())throw new CloudException(CloudErrorCode.Cancelled,$"Cancelled after {n.GetInt32()} items.");return r;}
OperationOptions Opts(JsonElement o)=>new(PageSize:I(o,"page_size",1000),Limit:I(o,"limit",1000),MaxBytes:o.TryGetProperty("max_bytes",out var m)?m.GetInt64():null,Overwrite:S(o,"overwrite","fail")switch{"replace"=>OverwriteMode.Replace,"rename"=>OverwriteMode.Rename,_=>OverwriteMode.Fail},Destructive:B(o,"destructive"),Recursive:B(o,"recursive"));
static string S(JsonElement e,string n,string? d=null)=>e.TryGetProperty(n,out var v)&&v.ValueKind!=JsonValueKind.Null?v.GetString()!:d!;
static int I(JsonElement e,string n,int d)=>e.TryGetProperty(n,out var v)?v.GetInt32():d;
static bool B(JsonElement e,string n)=>e.TryGetProperty(n,out var v)&&v.GetBoolean();
static string Code(CloudErrorCode c)=>c switch{CloudErrorCode.NotFound=>"not_found",CloudErrorCode.InvalidConfig=>"invalid_config",CloudErrorCode.ProviderError=>"provider_error",CloudErrorCode.ConfirmationRequired=>"confirmation_required",_=>c.ToString().ToLowerInvariant()};
