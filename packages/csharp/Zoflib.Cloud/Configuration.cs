using System.Text.Json;
using System.Text.Json.Serialization;

namespace Zoflib.Cloud;

public enum S3Addressing { Path, Virtual, Both, Unknown }
public sealed record CloudCredential(string AccessKeyId, string SecretAccessKey, string? SessionToken = null);
public delegate ValueTask<CloudCredential> CredentialResolver(string credentialReference, string? sessionTokenReference, CancellationToken cancellationToken);
public sealed record S3ConnectionConfig(string Provider, Uri Endpoint, string Region, string CredentialReference,
    string? SigningRegion = null, S3Addressing Addressing = S3Addressing.Path, string? Root = null,
    string? SessionTokenReference = null, bool AllowInsecureHttp = false)
{
    public void Validate()
    {
        if (Endpoint.Scheme != Uri.UriSchemeHttps && !(AllowInsecureHttp && Endpoint.IsLoopback))
            throw new CloudException(CloudErrorCode.InvalidConfig, "HTTPS is required; HTTP is allowed only for an explicit loopback development endpoint.");
        if (string.IsNullOrWhiteSpace(Region) || string.IsNullOrWhiteSpace(CredentialReference))
            throw new CloudException(CloudErrorCode.InvalidConfig, "Region and credential reference are required.");
    }
}

public sealed record ProviderPreset(string Id, string Name, string Protocol, string Classification,
    [property: JsonPropertyName("endpoint_template")] string? EndpointTemplate, string? Region,
    S3Addressing? Addressing, string Caveats);

public static class ProviderPresets
{
    public static IReadOnlyDictionary<string, ProviderPreset> Load(string providersJson)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(providersJson));
        var map = new Dictionary<string, ProviderPreset>(StringComparer.Ordinal);
        foreach (var p in doc.RootElement.GetProperty("providers").EnumerateArray())
        {
            if (p.GetProperty("protocol").GetString() != "s3") continue;
            var a = p.GetProperty("addressing").GetString();
            map[p.GetProperty("id").GetString()!] = new ProviderPreset(
                p.GetProperty("id").GetString()!, p.GetProperty("name").GetString()!, "s3",
                p.GetProperty("classification").GetString()!,
                p.GetProperty("endpoint_template").ValueKind == JsonValueKind.Null ? null : p.GetProperty("endpoint_template").GetString(),
                p.GetProperty("region").ValueKind == JsonValueKind.Null ? null : p.GetProperty("region").GetString(),
                a switch { "path" => S3Addressing.Path, "virtual" => S3Addressing.Virtual, "both" => S3Addressing.Both, _ => S3Addressing.Unknown },
                p.GetProperty("caveats").GetString() ?? "");
        }
        return map;
    }
}
