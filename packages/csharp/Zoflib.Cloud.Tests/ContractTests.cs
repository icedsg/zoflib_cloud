using System.Text;
using Zoflib.Cloud;
using Xunit;

public class ContractTests
{
    [Fact] public void LoadsAllS3Presets(){var p=ProviderPresets.Load(Path.Combine(Repo(),"spec","providers.json"));Assert.Equal(24,p.Count);Assert.Equal("auto",p["cloudflare-r2"].Region);Assert.Equal(S3Addressing.Virtual,p["tigris"].Addressing);}
    [Fact] public void RejectsNonLoopbackHttp(){var c=new S3ConnectionConfig("minio",new("http://example.test"),"us-east-1","ref",AllowInsecureHttp:true);var e=Assert.Throws<CloudException>(c.Validate);Assert.Equal(CloudErrorCode.InvalidConfig,e.Code);}
    [Fact] public async Task MemoryStoreHonorsUtf8PaginationAndSafety(){var s=new MemoryCloudStore();s.Reset([("é.txt",[1]),("𐀀.txt",[2]),("z.txt",[3])]);var p=await s.ListAsync("test-bucket",o:new(PageSize:2));Assert.Equal(2,p.Items.Count);Assert.NotNull(p.NextToken);await Assert.ThrowsAsync<CloudException>(()=>s.DeleteAsync("test-bucket","z.txt"));}
    [Fact] public async Task CancellationChangesNothing(){var s=new MemoryCloudStore();s.Reset([("a",[1])]);using var c=new CancellationTokenSource();c.Cancel();await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>s.UploadAsync("test-bucket","b",new MemoryStream([2]),ct:c.Token));Assert.Equal(["a"],s.Dump());}
    static string Repo(){var d=new DirectoryInfo(AppContext.BaseDirectory);while(d is not null&&!File.Exists(Path.Combine(d.FullName,"spec","contract.json")))d=d.Parent;return d?.FullName??throw new InvalidOperationException("repo root not found");}
}
