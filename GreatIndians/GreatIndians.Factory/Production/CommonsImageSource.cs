using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.RegularExpressions;
using SkiaSharp;

namespace GreatIndians.Factory.Production;

public sealed record WebImageCredit(string Title, string Creator, string License, string LicenseUrl,
    string SourceUrl, string DownloadUrl, string CreditLine, string OriginalSha256)
{
    public string Text(string sceneId) => $"{sceneId}: {Title}. Creator: {Creator}. {CreditLine} " +
        $"License: {License} ({LicenseUrl}). Source: {SourceUrl}. " +
        "Original photograph; encoding and proportional print sizing only. Image remains under its stated source license.";
}
public sealed record CommonsCandidate(string Title, string Creator, string License, string LicenseUrl,
    string SourceUrl, string DownloadUrl, string CreditLine, int Width, int Height, string Description = "");
public sealed record DownloadedWebImage(string Path, int Width, int Height, WebImageCredit Credit);
public sealed record WebImageReview(
    [property: System.Text.Json.Serialization.JsonRequired] bool IsRealPhotograph,
    [property: System.Text.Json.Serialization.JsonRequired] bool NoArtificialGenerationEvidence,
    [property: System.Text.Json.Serialization.JsonRequired] ImageReview Review);

/// <summary>Restricts automated reuse to raster files with explicit Commons attribution/license metadata.</summary>
public sealed class CommonsImageSource : IDisposable
{
    private readonly HttpClient http;
    private readonly bool ownsHttp;
    public CommonsImageSource(HttpClient? client = null)
    {
        ownsHttp = client is null;
        http = client ?? new HttpClient(new SocketsHttpHandler
        {
            AllowAutoRedirect = false,
            AutomaticDecompression = DecompressionMethods.All,
            ConnectCallback = async (context, ct) =>
            {
                var addresses = await Dns.GetHostAddressesAsync(context.DnsEndPoint.Host, ct);
                if (addresses.Length == 0 || addresses.Any(IsPrivate)) throw new InvalidDataException("Non-public image host address.");
                var socket = new Socket(SocketType.Stream, ProtocolType.Tcp);
                try { await socket.ConnectAsync(addresses, context.DnsEndPoint.Port, ct); return new NetworkStream(socket, true); }
                catch { socket.Dispose(); throw; }
            }
        }) { Timeout = TimeSpan.FromSeconds(45) };
    }

    public async Task<List<CommonsCandidate>> FindAsync(Manuscript manuscript, SubjectDefinition? subject,
        Artifacts files, CancellationToken ct)
    {
        string query = string.IsNullOrWhiteSpace(subject?.ImageQuery) ? $"\"{manuscript.Subject}\"" : subject.ImageQuery;
        string parameters = subject?.CommonsFiles is { Length: > 0 }
            ? "titles=" + Uri.EscapeDataString(string.Join('|', subject.CommonsFiles))
            : "generator=search&gsrnamespace=6&gsrlimit=12&gsrsearch=" + Uri.EscapeDataString(query + " filetype:bitmap");
        var uri = new Uri("https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2&prop=imageinfo" +
            "&iiprop=url%7Csize%7Cmime%7Cextmetadata&iiextmetadatafilter=Artist%7CCredit%7CLicenseShortName%7CLicenseUrl%7CRestrictions%7CImageDescription%7CCategories" +
            "&" + parameters);
        var raw = await files.Cached("cache/commons-" + Data.Hash(uri.AbsoluteUri)[..16] + ".json", uri.AbsoluteUri,
            async () => System.Text.Encoding.UTF8.GetString(await GetAsync(uri, 2_000_000, false, ct)));
        using var doc = JsonDocument.Parse(raw);
        if (doc.RootElement.TryGetProperty("error", out _)) throw new InvalidDataException("Commons search returned an error.");
        var results = Parse(doc.RootElement);
        await files.Save("provenance/commons-candidates.json", Data.Write(new { query, candidates = results }));
        return results;
    }

    public static List<CommonsCandidate> Parse(JsonElement root)
    {
        var result = new List<CommonsCandidate>();
        if (!root.TryGetProperty("query", out var query) || !query.TryGetProperty("pages", out var pages)) return result;
        foreach (var page in pages.EnumerateArray())
        {
            if (!page.TryGetProperty("imageinfo", out var info) || info.GetArrayLength() == 0) continue;
            var image = info[0];
            if (!image.TryGetProperty("extmetadata", out var metadata)) continue;
            string Field(string key) => metadata.TryGetProperty(key, out var value) && value.TryGetProperty("value", out var text)
                ? Plain(text.GetString() ?? "") : "";
            string license = Field("LicenseShortName"), licenseUrl = Field("LicenseUrl"), creator = Field("Artist");
            string url = image.TryGetProperty("url", out var u) ? u.GetString() ?? "" : "";
            int width = image.TryGetProperty("width", out var w) ? w.GetInt32() : 0;
            int height = image.TryGetProperty("height", out var h) ? h.GetInt32() : 0;
            string mime = image.TryGetProperty("mime", out var m) ? m.GetString() ?? "" : "";
            if (!ReusableLicense(license, licenseUrl) || string.IsNullOrWhiteSpace(creator) || creator.Length > 4000
                || Regex.IsMatch(Field("Categories") + " " + Field("ImageDescription"), "(?i)\\b(ai[- ]generated|stable diffusion|midjourney|digital reconstruction)\\b")
                || !string.IsNullOrWhiteSpace(Field("Restrictions")) || !AllowedUri(url)
                || new Uri(url).Host != "upload.wikimedia.org" || mime is not ("image/jpeg" or "image/png")
                || Math.Min(width, height) < 768 || Math.Max(width, height) > 12000
                || (double)width / height is < 0.333 or > 3) continue;
            result.Add(new CommonsCandidate(Plain(page.GetProperty("title").GetString() ?? ""), creator, license, licenseUrl,
                "https://commons.wikimedia.org/?curid=" + page.GetProperty("pageid").GetInt64(), url, Field("Credit"), width, height,
                Field("ImageDescription")[..Math.Min(Field("ImageDescription").Length, 8000)]));
        }
        return result;
    }

    public static bool ReusableLicense(string name, string url)
    {
        if (string.IsNullOrWhiteSpace(name) || !Uri.TryCreate(url, UriKind.Absolute, out var uri)
            || uri.Scheme != "https" || uri.Host != "creativecommons.org" || !string.IsNullOrEmpty(uri.UserInfo)) return false;
        return Regex.IsMatch(uri.AbsolutePath, "^/(licenses/(by|by-sa)/(1\\.0|2\\.0|2\\.5|3\\.0|4\\.0)|publicdomain/(zero|mark)/1\\.0)/?$")
            && !Regex.IsMatch(name, "(?i)(non.?commercial|no.?derivatives|fair.?use|all rights reserved|\\bNC\\b|\\bND\\b)");
    }

    public async Task<DownloadedWebImage> DownloadAsync(CommonsCandidate candidate, string stage, Artifacts files, CancellationToken ct)
    {
        var cached = await files.Cached("cache/commons-download-" + Data.Hash(candidate.DownloadUrl)[..16] + ".json",
            Data.Write(candidate), async () => Convert.ToBase64String(await GetAsync(new Uri(candidate.DownloadUrl), 20_000_000, true, ct)));
        var bytes = Convert.FromBase64String(cached);
        using var codec = SKCodec.Create(new SKMemoryStream(bytes)) ?? throw new InvalidDataException("Invalid web image codec.");
        if (Math.Min(codec.Info.Width, codec.Info.Height) < 768 || Math.Max(codec.Info.Width, codec.Info.Height) > 12000
            || (long)codec.Info.Width * codec.Info.Height > 50_000_000) throw new InvalidDataException("Unsupported web image dimensions.");
        using var bitmap = SKBitmap.Decode(bytes) ?? throw new InvalidDataException("Invalid web image.");
        var path = Path.Combine(files.Root, "artwork", stage + ".png");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        using var png = bitmap.Encode(SKEncodedImageFormat.Png, 100);
        await File.WriteAllBytesAsync(path, png.ToArray(), ct);
        var originalHash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
        var credit = new WebImageCredit(candidate.Title, candidate.Creator, candidate.License, candidate.LicenseUrl,
            candidate.SourceUrl, candidate.DownloadUrl, candidate.CreditLine, originalHash);
        await files.Save($"provenance/{stage}-web-source.json", Data.Write(new { credit, downloadedAt = DateTimeOffset.UtcNow,
            decodedWidth = bitmap.Width, decodedHeight = bitmap.Height, outputSha256 = ManuscriptReader.HashFile(path) }));
        return new DownloadedWebImage(path, bitmap.Width, bitmap.Height, credit);
    }

    public static bool AllowedUri(string url) => Uri.TryCreate(url, UriKind.Absolute, out var uri)
        && uri.Scheme == "https" && uri.Port == 443 && string.IsNullOrEmpty(uri.UserInfo)
        && uri.Host is "commons.wikimedia.org" or "upload.wikimedia.org";

    private async Task<byte[]> GetAsync(Uri uri, int limit, bool image, CancellationToken ct)
    {
        for (int redirects = 0; redirects < 4; redirects++)
        {
            if (!AllowedUri(uri.AbsoluteUri)) throw new InvalidDataException("Only public Wikimedia Commons/image hosts are supported.");
            using var request = new HttpRequestMessage(HttpMethod.Get, uri);
            request.Headers.UserAgent.ParseAdd("GreatIndiansPublishing/1.0 (+https://github.com/SunilPrasad/AIAgentProjects)");
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
            if ((int)response.StatusCode is >= 300 and < 400 && response.Headers.Location is { } location)
            { uri = location.IsAbsoluteUri ? location : new Uri(uri, location); continue; }
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength > limit) throw new InvalidDataException("Web response exceeds download limit.");
            if (image && response.Content.Headers.ContentType?.MediaType is not ("image/png" or "image/jpeg"))
                throw new InvalidDataException("Web image must be PNG or JPEG.");
            await using var stream = await response.Content.ReadAsStreamAsync(ct);
            using var output = new MemoryStream();
            var buffer = new byte[8192];
            int count;
            while ((count = await stream.ReadAsync(buffer, ct)) > 0)
            {
                if (output.Length + count > limit) throw new InvalidDataException("Web response exceeds download limit.");
                await output.WriteAsync(buffer.AsMemory(0, count), ct);
            }
            return output.ToArray();
        }
        throw new InvalidDataException("Too many web image redirects.");
    }

    private static string Plain(string value) => Data.Normalize(WebUtility.HtmlDecode(Regex.Replace(value, "<[^>]+>", " ")));
    private static bool IsPrivate(IPAddress address)
    {
        if (address.IsIPv4MappedToIPv6) address = address.MapToIPv4();
        if (IPAddress.IsLoopback(address)) return true;
        var b = address.GetAddressBytes();
        if (address.AddressFamily == AddressFamily.InterNetworkV6)
            return address.IsIPv6LinkLocal || address.IsIPv6SiteLocal || address.IsIPv6Multicast
                || address.Equals(IPAddress.IPv6Any) || (b[0] & 0xfe) == 0xfc;
        return b[0] is 0 or 10 or 127 or >= 224 || b[0] == 169 && b[1] == 254
            || b[0] == 172 && b[1] is >= 16 and <= 31 || b[0] == 192 && b[1] == 168 || b[0] == 100 && b[1] is >= 64 and <= 127;
    }
    public void Dispose() { if (ownsHttp) http.Dispose(); }
}
