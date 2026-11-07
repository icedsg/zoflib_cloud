using Zoflib.Cloud;
using Xunit;

public class S3IntegrationTests
{
    [Fact]
    public async Task GenericS3OperationsAndMultipart()
    {
        var endpoint=Environment.GetEnvironmentVariable("ZOFLIB_S3_ENDPOINT");
        if(string.IsNullOrEmpty(endpoint)) return;
        var access=Environment.GetEnvironmentVariable("ZOFLIB_S3_ACCESS")??throw new InvalidOperationException("test access id missing");
        var secret=Environment.GetEnvironmentVariable("ZOFLIB_S3_SECRET")??throw new InvalidOperationException("test secret missing");
        var bucket="zoflib-"+Guid.NewGuid().ToString("N");
        var cfg=new S3ConnectionConfig("minio",new(endpoint),"us-east-1","integration",Root:bucket,AllowInsecureHttp:true);
        using var store=new S3CloudStore(cfg,(r,t,c)=>ValueTask.FromResult(new CloudCredential(access,secret)));
        using var admin=new Amazon.S3.AmazonS3Client(new Amazon.Runtime.BasicAWSCredentials(access,secret),new Amazon.S3.AmazonS3Config{ServiceURL=endpoint,ForcePathStyle=true,AuthenticationRegion="us-east-1"});
        await admin.PutBucketAsync(bucket);
        try
        {
            await store.UploadAsync(bucket,"docs/a.txt",new MemoryStream("hello"u8.ToArray()));
            using var large=new MemoryStream(new byte[17*1024*1024]);await store.UploadAsync(bucket,"large.bin",large);
            Assert.Equal(2,(await store.SearchAsync(bucket,"",".")).Items.Count);
            Assert.Equal(5,(await store.StatAsync(bucket,"docs/a.txt")).Size);
            using var downloaded=new MemoryStream();await store.DownloadAsync(bucket,"docs/a.txt",downloaded);Assert.Equal("hello",System.Text.Encoding.UTF8.GetString(downloaded.ToArray()));
            await store.CopyAsync(bucket,"docs/a.txt","docs/b.txt");
            await store.MoveAsync(bucket,"docs/b.txt","docs/c.txt",new(Destructive:true));
            await store.DeleteAsync(bucket,"docs/",new(Destructive:true,Recursive:true));
            await store.DeleteAsync(bucket,"large.bin",new(Destructive:true));
        }
        finally { await admin.DeleteBucketAsync(bucket); }
    }
}
