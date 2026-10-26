using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using AngleSharp.Html.Parser;
using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory;

public sealed class Researcher(BookConfig config, ModelGateway api, ILogger log,
    Func<Uri, CancellationToken, Task<(string Html, string Url)>>? sourceFetcher = null)
{
    public async Task<List<Source>> Gather(string subject, Artifacts files, CancellationToken ct, string? researchPurpose = null,
        int replacementSearches = 0)
    {
        if (replacementSearches is < 0 or > 2)
            throw new ArgumentOutOfRangeException(nameof(replacementSearches));
        var result = new List<Source>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var failures = new List<object>();
        var failedHosts = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var attemptedHosts = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (int round = 0; round <= replacementSearches; round++)
        {
            string? purpose = researchPurpose;
            if (round > 0)
            {
                purpose = (researchPurpose ?? $"Research {subject}. " + ContentProfiles.Guidance(config.Profile)) +
                    " REPLACEMENT SEARCH: Earlier citations did not provide enough independently accessible source domains. " +
                    "Find alternative public, readable HTML or text-based PDF sources on different domains. Avoid login/paywall/anti-bot pages. " +
                    "Prefer universities, museums, government institutions and accessible scientific biographies. " +
                    "Avoid these previously attempted URLs: " + string.Join(", ", seen.Order()) +
                    ". Prefer domains other than: " + string.Join(", ", attemptedHosts.Order()) +
                    ". These domains had failed downloads: " + string.Join(", ", failedHosts.Order()) + ".";
                log.LogWarning("[{Chapter}][ResearchAgent][RECOVER] {Domains}/{Required} accessible domains; replacement search {Round}/{Limit}",
                    subject, result.Select(s => new Uri(s.Url).Host).Distinct(StringComparer.OrdinalIgnoreCase).Count(), config.MinSources, round, replacementSearches);
            }
            var search = await api.Search(subject, files, ct, purpose, round == 0 ? "search" : $"search-recovery-{round}");
            var urls = new List<string>();
            CollectUrls(search, urls);
            // Try each domain once before its second/third citation, so one host cannot fill the quota.
            var ordered = urls.Distinct().Where(u => !seen.Contains(u)).GroupBy(u => Uri.TryCreate(u, UriKind.Absolute, out var uri) ? uri.Host : "")
                .SelectMany(g => g.Select((url, index) => (url, index))).OrderBy(x => x.index).Select(x => x.url).Take(20);
            foreach (var url in ordered)
            {
                if (result.Count >= config.MaxSources)
                    break;
                seen.Add(url);
                if (Uri.TryCreate(url, UriKind.Absolute, out var attempted))
                    attemptedHosts.Add(attempted.Host);

                try
                {
                    var fetched = await files.Cached($"cache/source-{Data.Hash(url)[..16]}.json", url, async () =>
                    {
                        var uri = new Uri(url);
                        if (config.AllowedSourceDomains.Count > 0 && !config.AllowedSourceDomains.Any(d => uri.Host.Equals(d, StringComparison.OrdinalIgnoreCase) || uri.Host.EndsWith("." + d, StringComparison.OrdinalIgnoreCase)))
                        {
                            throw new InvalidDataException("Source outside configured domain list.");
                        }

                        log.LogInformation("[{Chapter}][ResearchAgent][FETCH] Retrieving source {Host}", subject, uri.Host);
                        var (html, finalUrl) = await (sourceFetcher is null ? Fetch(uri, ct, config.MaxSourceCharacters) : sourceFetcher(uri, ct));
                        var finalHost = new Uri(finalUrl).Host;
                        if (config.AllowedSourceDomains.Count > 0 && !config.AllowedSourceDomains.Any(d => finalHost.Equals(d, StringComparison.OrdinalIgnoreCase) || finalHost.EndsWith("." + d, StringComparison.OrdinalIgnoreCase)))
                        {
                            throw new InvalidDataException("Redirected source outside configured domain list.");
                        }

                        using var document = await new HtmlParser().ParseDocumentAsync(html, ct);
                        foreach (var element in document.QuerySelectorAll("script,style,nav,footer,header,noscript"))
                        {
                            element.Remove();
                        }

                        var text = Data.Normalize((document.QuerySelector("main,article") ?? document.Body)?.TextContent ?? "");
                        if (text.Length < 400)
                        {
                            throw new InvalidDataException("Source has insufficient accessible text.");
                        }

                        text = text[..Math.Min(text.Length, config.MaxSourceCharacters)];
                        return Data.Write(new Source("", finalUrl, document.Title ?? uri.Host, text, Data.Hash(text), DateTimeOffset.UtcNow));
                    });
                    var source = Data.Read<Source>(fetched) with
                    {
                        Id = $"S{result.Count + 1}"
                    };
                    if (source.Sha256 != Data.Hash(source.Text))
                    {
                        throw new InvalidDataException("Source snapshot hash mismatch.");
                    }

                    if (result.Any(s => s.Url == source.Url))
                        continue;
                    // Reserve capacity for the required independent domains even if search favours one host.
                    int domains = result.Select(s => new Uri(s.Url).Host).Distinct(StringComparer.OrdinalIgnoreCase).Count();
                    bool existingHost = result.Any(s => new Uri(s.Url).Host.Equals(new Uri(source.Url).Host, StringComparison.OrdinalIgnoreCase));
                    if (existingHost && result.Count >= config.MaxSources - (config.MinSources - domains))
                        continue;
                    result.Add(source);
                    await files.Save($"research/{source.Id}.json", Data.Write(source));
                }
                catch (Exception ex) when (!ct.IsCancellationRequested && ex is HttpRequestException or InvalidDataException or TaskCanceledException or UriFormatException or SocketException)
                {
                    if (Uri.TryCreate(url, UriKind.Absolute, out var failed))
                        failedHosts.Add(failed.Host);
                    failures.Add(new
                    {
                        url,
                        type = ex.GetType().Name,
                        reason = ex.Message
                    });
                    log.LogWarning("[{Chapter}][ResearchAgent][FETCH] Source unavailable ({Type}): {Reason}; trying next source", subject, ex.GetType().Name, ex.Message);
                }
            }
            await files.Save("research/fetch-failures.json", Data.Write(failures));
            if (result.Select(s => new Uri(s.Url).Host).Distinct(StringComparer.OrdinalIgnoreCase).Count() >= config.MinSources)
                break;
        }
        if (result.Select(s => new Uri(s.Url).Host).Distinct(StringComparer.OrdinalIgnoreCase).Count() < config.MinSources)
        {
            throw new EditorialException($"Fewer than {config.MinSources} accessible source domains after {replacementSearches} replacement search(es). Retained downloads and search results will be reused. See research/fetch-failures.json.");
        }

        await files.Save("research/sources.json", Data.Write(result));
        return result;
    }
    private static void CollectUrls(JsonElement element, List<string> urls)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject())
            {
                if (property.Name.Equals("url", StringComparison.OrdinalIgnoreCase) && property.Value.ValueKind == JsonValueKind.String && property.Value.GetString() is { } url)
                {
                    urls.Add(url);
                }
                else
                {
                    CollectUrls(property.Value, urls);
                }
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var child in element.EnumerateArray())
            {
                CollectUrls(child, urls);
            }
        }
    }
    // Resolve at connection time to prevent source URLs/redirects reaching local services.
    private static async Task<(string Html, string Url)> Fetch(Uri uri, CancellationToken ct, int maxCharacters)
    {
        using var handler = new SocketsHttpHandler { AllowAutoRedirect = false, AutomaticDecompression = DecompressionMethods.All };
        handler.ConnectCallback = async (context, token) =>
        {
            var addresses = await Dns.GetHostAddressesAsync(context.DnsEndPoint.Host, token);
            if (addresses.Length == 0 || addresses.Any(IsPrivate))
            {
                throw new InvalidDataException("Source resolves to a non-public address.");
            }

            var socket = new Socket(SocketType.Stream, ProtocolType.Tcp);
            try
            {
                await socket.ConnectAsync(addresses, context.DnsEndPoint.Port, token);
                return new NetworkStream(socket, ownsSocket: true);
            }
            catch
            {
                socket.Dispose();
                throw;
            }
        };
        using var http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(35) };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("GreatIndiansResearch/1.0");
        for (int redirect = 0; redirect < 5; redirect++)
        {
            if (uri.Scheme != "https" || uri.Port != 443 || !string.IsNullOrEmpty(uri.UserInfo))
            {
                throw new InvalidDataException("Only public HTTPS sources are supported.");
            }

            using var response = await http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, ct);
            if ((int)response.StatusCode is >= 300 and < 400 && response.Headers.Location is { } location)
            {
                uri = location.IsAbsoluteUri ? location : new Uri(uri, location);
                continue;
            }
            response.EnsureSuccessStatusCode();
            var media = response.Content.Headers.ContentType?.MediaType;
            bool pdf = media == "application/pdf";
            if (!pdf && media is not ("text/html" or "application/xhtml+xml" or "text/plain"))
            {
                throw new InvalidDataException($"Unsupported source media type: {media ?? "missing"}. Expected HTML, plain text or PDF.");
            }

            await using var stream = await response.Content.ReadAsStreamAsync(ct);
            using var bytes = new MemoryStream();
            var buffer = new byte[8192];
            int read;
            while ((read = await stream.ReadAsync(buffer, ct)) > 0)
            {
                if (bytes.Length + read > (pdf ? 10_000_000 : 2_000_000))
                {
                    throw new InvalidDataException("Source exceeds download limit.");
                }

                await bytes.WriteAsync(buffer.AsMemory(0, read), ct);
            }
            if (pdf)
            {
                string text = ExtractPdfText(bytes.ToArray(), maxCharacters, ct);
                return ($"<html><head><title>{WebUtility.HtmlEncode(Path.GetFileName(uri.AbsolutePath))}</title></head><body><article>{WebUtility.HtmlEncode(text)}</article></body></html>", uri.AbsoluteUri);
            }
            var encoding = Encoding.UTF8;
            try
            {
                if (response.Content.Headers.ContentType?.CharSet is { } charset)
                {
                    encoding = Encoding.GetEncoding(charset.Trim('"'));
                }
            }
            catch (ArgumentException)
            {
            }
            return (encoding.GetString(bytes.ToArray()), uri.AbsoluteUri);
        }
        throw new InvalidDataException("Too many source redirects.");
    }
    public static string ExtractPdfText(byte[] bytes, int maxCharacters, CancellationToken ct)
    {
        if (bytes.Length > 10_000_000 || maxCharacters is < 1000 or > 50000)
            throw new InvalidDataException("PDF source exceeds extraction limits.");
        try
        {
            using var pdf = UglyToad.PdfPig.PdfDocument.Open(bytes);
            var text = new StringBuilder();
            foreach (var page in pdf.GetPages().Take(200))
            {
                ct.ThrowIfCancellationRequested();
                text.Append(' ').Append(UglyToad.PdfPig.DocumentLayoutAnalysis.TextExtractor.ContentOrderTextExtractor.GetText(page));
                if (text.Length >= maxCharacters)
                    break;
            }
            string normalized = Data.Normalize(text.ToString());
            if (normalized.Length < 400)
                throw new InvalidDataException("PDF has insufficient extractable text; scanned/image-only PDFs are not evidence substitutes.");
            return normalized[..Math.Min(normalized.Length, maxCharacters)];
        }
        catch (Exception ex) when (ex is not OperationCanceledException and not OutOfMemoryException and not InvalidDataException)
        {
            throw new InvalidDataException("PDF text extraction failed: " + ex.GetType().Name, ex);
        }
    }
    private static bool IsPrivate(IPAddress address)
    {
        if (address.IsIPv4MappedToIPv6)
        {
            address = address.MapToIPv4();
        }

        if (IPAddress.IsLoopback(address))
        {
            return true;
        }

        if (address.AddressFamily == AddressFamily.InterNetworkV6)
        {
            var bytes = address.GetAddressBytes();
            return address.IsIPv6LinkLocal || address.IsIPv6SiteLocal || address.IsIPv6Multicast || address.Equals(IPAddress.IPv6Any) || (bytes[0] & 0xfe) == 0xfc;
        }
        var b = address.GetAddressBytes();
        return b[0] is 0 or 10 or 127 or >= 224 || (b[0] == 169 && b[1] == 254) || (b[0] == 172 && b[1] is >= 16 and <= 31)
            || (b[0] == 192 && b[1] == 168) || (b[0] == 100 && b[1] is >= 64 and <= 127);
    }
    public void Validate(Evidence evidence, List<Source> sources)
    {
        if (evidence.Claims is null || evidence.Claims.Count < config.MinClaims || evidence.Claims.Any(c => c is null)
            || evidence.Claims.Select(c => c.Id).Distinct().Count() != evidence.Claims.Count)
        {
            throw new EditorialException("Evidence ledger is insufficient or has duplicate claim IDs.");
        }

        foreach (var claim in evidence.Claims)
        {
            var source = sources.SingleOrDefault(s => s.Id == claim.SourceId);
            if (source is null || string.IsNullOrWhiteSpace(claim.Id) || string.IsNullOrWhiteSpace(claim.Text)
                || string.IsNullOrWhiteSpace(claim.Quote) || Data.Normalize(claim.Quote).Length < 30
                || !source.Text.Contains(Data.Normalize(claim.Quote), StringComparison.Ordinal))
            {
                throw new EditorialException($"Evidence excerpt for {claim.Id} is missing from its retained source. Research blocked.");
            }
        }
        if (evidence.Claims.Select(c => sources.Single(s => s.Id == c.SourceId)).Select(s => new Uri(s.Url).Host).Distinct().Count() < config.MinSources)
        {
            throw new EditorialException("Evidence ledger does not use enough independent source domains.");
        }
    }
}
