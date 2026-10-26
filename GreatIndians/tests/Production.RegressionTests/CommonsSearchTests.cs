using System.Net;
using System.Text;
using System.Text.Json;
using GreatIndians.Factory;
using GreatIndians.Factory.Production;
using Microsoft.Extensions.Logging.Abstractions;

internal static class CommonsSearchTests
{
    private static void Check(bool valid, string message)
    {
        if (!valid) throw new Exception("Commons search: " + message);
    }
    public static async Task RunAsync()
    {
        string root = Path.Combine(AppContext.BaseDirectory, "commons-tests", Guid.NewGuid().ToString("N")[..10]);
        var subject = new SubjectDefinition { Id = "bose", Name = "Sir Jagadish Chandra Bose", Aliases = ["J. C. Bose"],
            ImageQuery = "Sir Jagadish Chandra Bose scientist portrait", CommonsFiles = ["File:Curated.jpg"] };
        var manuscript = new Manuscript("unused", "unused", subject.Name, subject.Name, 1, [], []);
        var files = new Artifacts(root, NullLogger.Instance);
        // Reproduce the old permanently empty search. The new version must not let this suppress alternatives.
        string oldUri = "https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2&prop=imageinfo" +
            "&iiprop=url%7Csize%7Cmime%7Cextmetadata&iiextmetadatafilter=Artist%7CCredit%7CLicenseShortName%7CLicenseUrl%7CRestrictions%7CImageDescription%7CCategories" +
            "&generator=search&gsrnamespace=6&gsrlimit=12&gsrsearch=" + Uri.EscapeDataString(subject.ImageQuery + " filetype:bitmap");
        await files.Cached("cache/commons-" + Data.Hash(oldUri)[..16] + ".json", oldUri, () => Task.FromResult("{\"batchcomplete\":true}"));
        var handler = new Handler();
        using var http = new HttpClient(handler);
        using var source = new CommonsImageSource(http);
        var results = await source.FindAsync(manuscript, subject, files, default);
        Check(CommonsImageSource.SearchQueries(subject.Name, subject).First() == "Jagadish Chandra Bose", "Honorific not stripped from plain-name query.");
        Check(handler.Queries.Contains("Jagadish Chandra Bose") && handler.Queries.Contains("J. C. Bose")
            && handler.Queries.All(q => !q.Contains("filetype:bitmap")), "Broad/alias fallback missing or restrictive suffix returned.");
        Check(results.Select(c => c.Title).ToHashSet().SetEquals(["File:Curated.jpg", "File:Portrait.jpg", "File:Institute.jpg"]),
            "Curated, alias or Wikipedia-linked sources missing, duplicated or unfiltered.");
        Check(handler.SawWikipedia && handler.SawWikipediaOriginals, "Wikipedia files were not resolved through Commons metadata.");
        int calls = handler.Calls;
        await source.FindAsync(manuscript, subject, files, default);
        Check(handler.Calls == calls, "Repeated scene search did not use metadata cache.");
        string provenance = File.ReadAllText(Path.Combine(root, "provenance/commons-candidates.json"));
        Check(provenance.Contains("Wikipedia article images") && provenance.Contains("Commons name search"), "Search diagnostics missing.");
        var portrait = results.Single(c => c.Title.Contains("Portrait"));
        var equipment = portrait with { Title = "File:Microwave apparatus.jpg", Description = "Original microwave apparatus and radio wave detector in a museum", DownloadUrl = "https://upload.wikimedia.org/apparatus.jpg" };
        Check(CommonsImageSource.RankForPassage([portrait, equipment], "His microwave apparatus detected radio waves", "Research equipment").First() == equipment,
            "Relevant equipment photo did not outrank generic portrait for research passage.");
        Check(!CommonsImageSource.AllowedUri("https://en.wikipedia.org/w/api.php"), "Wikipedia metadata host was allowed as an image download source.");

        var unavailable = new Handler { WikipediaUnavailable = true };
        using var unavailableHttp = new HttpClient(unavailable);
        using var unavailableSource = new CommonsImageSource(unavailableHttp);
        var partial = await unavailableSource.FindAsync(manuscript, subject, new Artifacts(root + "-partial", NullLogger.Instance), default);
        Check(partial.Count == 2, "Wikipedia failure discarded valid Commons results.");
        Console.WriteLine("PASS web image discovery: plain names, aliases, Wikipedia original files, curated files, deduplication, licensing filters, old empty-cache recovery, cached rerun and passage ranking; no network calls");
    }
    private sealed class Handler : HttpMessageHandler
    {
        public int Calls;
        public List<string> Queries = [];
        public bool SawWikipedia, SawWikipediaOriginals, WikipediaUnavailable;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Calls++;
            string uri = Uri.UnescapeDataString(request.RequestUri!.AbsoluteUri);
            object answer = new { batchcomplete = true };
            if (request.RequestUri.Host == "en.wikipedia.org")
            {
                SawWikipedia = true;
                if (WikipediaUnavailable) return Task.FromResult(new HttpResponseMessage(HttpStatusCode.ServiceUnavailable));
                answer = new { query = new { pages = new[] { new { title = "Jagadish Chandra Bose", images = new[]
                { new { title = "File:Institute.jpg" }, new { title = "File:Signature.svg" }, new { title = "File:Portrait.jpg" } } } } } };
            }
            else if (uri.Contains("&titles=File:Curated.jpg")) answer = Metadata("Curated", "Historical science image");
            else if (uri.Contains("&titles=File:Institute.jpg"))
            {
                SawWikipediaOriginals = true;
                Check(!uri.Contains("Signature.svg"), "Unsupported Wikipedia file requested.");
                answer = Metadata("Institute", "Bose Institute building");
            }
            else if (uri.Contains("&gsrsearch="))
            {
                string query = uri[(uri.IndexOf("&gsrsearch=", StringComparison.Ordinal) + 11)..];
                Queries.Add(query);
                if (query == "J. C. Bose") answer = Metadata("Portrait", "Photograph of the scientist");
            }
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            { Content = new StringContent(JsonSerializer.Serialize(answer), Encoding.UTF8, "application/json") });
        }
        private static object Metadata(string title, string description) => new { query = new { pages = new[] { new
        {
            pageid = 123, title = "File:" + title + ".jpg", imageinfo = new[] { new
            {
                url = "https://upload.wikimedia.org/" + title + ".jpg", width = 2400, height = 1800, mime = "image/jpeg",
                extmetadata = new { Artist = new { value = "Fixture photographer" }, LicenseShortName = new { value = "CC BY 4.0" },
                    LicenseUrl = new { value = "https://creativecommons.org/licenses/by/4.0/" }, ImageDescription = new { value = description } }
            } }
        } } } };
    }
}
