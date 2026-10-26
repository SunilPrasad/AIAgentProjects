using System.Net;
using System.Text;
using System.Text.Json;
using GreatIndians.Factory;
using Microsoft.Extensions.Logging.Abstractions;

internal static class ResearchRecoveryTests
{
    private static void Check(bool valid, string message)
    {
        if (!valid) throw new Exception("Research recovery: " + message);
    }

    public static async Task RunAsync()
    {
        string root = Path.Combine(AppContext.BaseDirectory, "research-tests", Guid.NewGuid().ToString("N")[..10]);
        var config = new BookConfig { Personalities = ["Modern Science"], MaxSources = 2 };
        string paragraph = string.Join(" ", Enumerable.Repeat("Modern scientists made documented contributions in several scientific fields.", 12));
        byte[] pdf = Pdf(paragraph);
        string extracted = Researcher.ExtractPdfText(pdf, 18000, default);
        Check(extracted.Contains("Modern scientists") && extracted.Length >= 400, "Text-based PDF extraction failed.");
        bool scannedRejected = false;
        try { Researcher.ExtractPdfText(Pdf(""), 18000, default); }
        catch (InvalidDataException) { scannedRejected = true; }
        Check(scannedRejected, "Image-only/empty PDF passed evidence checks.");
        bool corruptRejected = false;
        try { Researcher.ExtractPdfText(Encoding.ASCII.GetBytes("not a PDF"), 18000, default); }
        catch (InvalidDataException) { corruptRejected = true; }
        Check(corruptRejected, "Malformed PDF was not reported as unavailable.");
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        bool cancelledExtraction = false;
        try { Researcher.ExtractPdfText(pdf, 18000, cancelled.Token); }
        catch (OperationCanceledException) { cancelledExtraction = true; }
        Check(cancelledExtraction, "Cancelled PDF extraction continued.");

        var handler = new SearchHandler();
        using var http = new HttpClient(handler);
        using var api = new ModelGateway(config, "offline", NullLogger.Instance, http);
        int successfulDownloads = 0;
        Task<(string Html, string Url)> Fetch(Uri uri, CancellationToken ct)
        {
            if (uri.Host == "blocked.example") throw new HttpRequestException("403 Forbidden fixture");
            successfulDownloads++;
            return Task.FromResult(($"<html><title>Science</title><article>{paragraph}</article></html>", uri.AbsoluteUri));
        }
        var research = new Researcher(config, api, NullLogger.Instance, Fetch);
        var files = new Artifacts(root, NullLogger.Instance);
        var sources = await research.Gather("Modern Science", files, default, "Modern scientists only", replacementSearches: 2);
        Check(handler.Calls == 2 && handler.SawRecoveryConstraints, "Recovery did not use one targeted replacement search.");
        Check(sources.Count == 2 && sources.Select(s => new Uri(s.Url).Host).Distinct().Count() == 2,
            "Same-domain citations filled the independent-source quota.");
        Check(sources.All(s => s.Sha256 == Data.Hash(s.Text)), "Retained evidence hashes changed.");
        Check(File.ReadAllText(Path.Combine(root, "research/fetch-failures.json")).Contains("403 Forbidden fixture"),
            "Actual source failure reason was lost.");
        int previousDownloads = successfulDownloads;
        await research.Gather("Modern Science", files, default, "Modern scientists only", replacementSearches: 2);
        Check(handler.Calls == 2 && successfulDownloads == previousDownloads, "Resume repeated paid search or successful downloads.");

        var blocked = new SearchHandler { AlwaysBlocked = true };
        using var blockedHttp = new HttpClient(blocked);
        using var blockedApi = new ModelGateway(config, "offline", NullLogger.Instance, blockedHttp);
        var blockedResearch = new Researcher(config, blockedApi, NullLogger.Instance, Fetch);
        bool boundedStop = false;
        try { await blockedResearch.Gather("Modern Science", new Artifacts(root + "-blocked", NullLogger.Instance), default,
            "Modern scientists only", replacementSearches: 2); }
        catch (EditorialException) { boundedStop = true; }
        Check(boundedStop && blocked.Calls == 3, "Recovery exceeded its two-search limit or fabricated evidence.");

        var pdfHandler = new SearchHandler { InitialPdf = true };
        using var pdfHttp = new HttpClient(pdfHandler);
        using var pdfApi = new ModelGateway(config, "offline", NullLogger.Instance, pdfHttp);
        var pdfResearch = new Researcher(config, pdfApi, NullLogger.Instance, (uri, ct) => Task.FromResult(
            ($"<article>{(uri.AbsolutePath.EndsWith(".pdf") ? Researcher.ExtractPdfText(pdf, 18000, ct) : paragraph)}</article>", uri.AbsoluteUri)));
        await pdfResearch.Gather("Modern Science", new Artifacts(root + "-pdf", NullLogger.Instance), default, "Modern scientists only", replacementSearches: 2);
        Check(pdfHandler.Calls == 1, "Replacement search was bought despite sufficient initial evidence.");
        Console.WriteLine("PASS research: PDF text extraction, unreadable PDF rejection, two-domain quota, bounded replacement search, failure diagnostics and cache-only resume; no network calls");
    }

    private static byte[] Pdf(string text)
    {
        string stream = $"BT /F1 10 Tf 30 700 Td ({text}) Tj ET";
        string[] objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", $"<< /Length {stream.Length} >>\nstream\n{stream}\nendstream"];
        var content = new StringBuilder("%PDF-1.4\n");
        var offsets = new List<int>();
        for (int i = 0; i < objects.Length; i++)
        {
            offsets.Add(content.Length);
            content.Append($"{i + 1} 0 obj\n{objects[i]}\nendobj\n");
        }
        int xref = content.Length;
        content.Append("xref\n0 6\n0000000000 65535 f \n");
        foreach (var offset in offsets) content.Append($"{offset:D10} 00000 n \n");
        content.Append($"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF");
        return Encoding.ASCII.GetBytes(content.ToString());
    }

    private sealed class SearchHandler : HttpMessageHandler
    {
        public int Calls;
        public bool AlwaysBlocked, InitialPdf, SawRecoveryConstraints;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Calls++;
            string body = await request.Content!.ReadAsStringAsync(ct);
            if (Calls > 1) SawRecoveryConstraints = body.Contains("REPLACEMENT SEARCH") && body.Contains("Modern scientists only") && body.Contains("blocked.example");
            string[] urls = AlwaysBlocked ? [$"https://blocked.example/unavailable-{Calls}"]
                : Calls > 1 ? ["https://alternative.example/scientists"]
                : InitialPdf ? ["https://nios.example/scientists.pdf", "https://museum.example/scientists"]
                : ["https://blocked.example/unavailable", "https://museum.example/one", "https://museum.example/two", "https://museum.example/three"];
            string json = JsonSerializer.Serialize(new
            {
                choices = new[] { new { finish_reason = "stop", message = new { role = "assistant", content = "Cited sources.",
                    annotations = urls.Select(url => new { type = "url_citation", url_citation = new { url, title = "Science" } }) } } }
            });
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
        }
    }
}
