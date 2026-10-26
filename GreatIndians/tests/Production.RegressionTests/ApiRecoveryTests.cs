using System.Net;
using System.Text;
using System.Text.Json;
using GreatIndians.Factory;
using GreatIndians.Factory.Production;
using Microsoft.Extensions.Logging.Abstractions;
using SkiaSharp;

internal static class ApiRecoveryTests
{
    private static void Check(bool value, string message)
    {
        if (!value) throw new Exception("API recovery: " + message);
    }
    public static async Task RunAsync()
    {
        string root = Path.Combine(AppContext.BaseDirectory, "api-tests", Guid.NewGuid().ToString("N")[..10]);
        var config = new ProductionConfig { MaxApiAttempts = 1 };
        var handler = new Handler(config);
        using var http = new HttpClient(handler);
        using var api = new ProductionApi(config, "secret-fixture-key", NullLogger.Instance, http);
        var files = new Artifacts(root, NullLogger.Instance);
        var image = await api.GenerateAsync("I04-attempt-1", "An educational historical scene", "4:3", [], files, default, config.DraftImageModel);
        Check(File.Exists(image) && handler.Models.SequenceEqual([config.DraftImageModel, config.ImageModel]),
            "Rejected draft did not escalate exactly once to configured main model.");
        string error = File.ReadAllText(Path.Combine(root, "provenance/I04-attempt-1-draft-http-error-1.json"));
        Check(error.Contains("unsupported aspect ratio") && !error.Contains("secret-fixture-key"), "Useful provider error missing or credential exposed.");
        await api.GenerateAsync("I04-attempt-1", "An educational historical scene", "4:3", [], files, default, config.DraftImageModel);
        Check(handler.Models.Count == 2, "Rerun retried rejected draft or repurchased saved fallback image.");
        int callsBeforeWebOnly = handler.Models.Count;
        using (var webOnlyApi = new ProductionApi(config with { ImageMode = "webOnly" }, "offline", NullLogger.Instance, http))
        {
            bool blockedGeneration = false;
            try { await webOnlyApi.GenerateAsync("I04-attempt-1", "An educational historical scene", "4:3", [], files, default, config.ImageModel); }
            catch (InvalidOperationException ex) { blockedGeneration = ex.Message.Contains("webOnly"); }
            Check(blockedGeneration && handler.Models.Count == callsBeforeWebOnly, "webOnly permitted generated cache reuse or a generation request.");
        }
        await api.GenerateAsync("I04-attempt-1", "A different historical scene", "4:3", [], files, default, config.DraftImageModel);
        Check(handler.Models.Count == 4, "Rejection from different prompt was reused.");

        foreach (var status in new[] { HttpStatusCode.Unauthorized, HttpStatusCode.PaymentRequired,
            HttpStatusCode.Forbidden, HttpStatusCode.BadRequest, HttpStatusCode.TooManyRequests, HttpStatusCode.InternalServerError })
        {
            var stopped = new Handler(config) { Failure = status, RejectMain = true };
            using var stoppedHttp = new HttpClient(stopped);
            using var stoppedApi = new ProductionApi(config, "secret-fixture-key", NullLogger.Instance, stoppedHttp);
            bool failed = false;
            try { await stoppedApi.GenerateAsync("I04", "A scene", "4:3", [],
                new Artifacts(root + "-" + (int)status, NullLogger.Instance), default, config.DraftImageModel); }
            catch (ProductionApiException ex) { failed = ex.Message.Contains("unsupported aspect ratio") && ex.StatusCode == status; }
            Check(failed && stopped.Models.Count == (status == HttpStatusCode.BadRequest ? 2 : 1),
                "Failure lost provider details, exceeded one fallback, or retried auth/billing errors.");
        }
        var safety = new Handler(config) { Message = "Content policy safety rejection" };
        using var safetyHttp = new HttpClient(safety);
        using var safetyApi = new ProductionApi(config, "offline", NullLogger.Instance, safetyHttp);
        bool safetyStopped = false;
        try { await safetyApi.GenerateAsync("I04", "A scene", "4:3", [], new Artifacts(root + "-safety", NullLogger.Instance), default, config.DraftImageModel); }
        catch (ProductionApiException) { safetyStopped = true; }
        Check(safetyStopped && safety.Models.Count == 1, "Safety rejection triggered model fallback.");
        Console.WriteLine("PASS API recovery: provider error details and redaction, one draft-to-main fallback, cached resume, changed inputs and bounded failures; no network calls");
    }

    private sealed class Handler(ProductionConfig config) : HttpMessageHandler
    {
        public List<string> Models = [];
        public HttpStatusCode Failure = HttpStatusCode.BadRequest;
        public bool RejectMain;
        public string Message = "unsupported aspect ratio for this model; secret-fixture-key";
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            using var body = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(ct));
            string model = body.RootElement.GetProperty("model").GetString()!;
            Models.Add(model);
            if (model == config.DraftImageModel || RejectMain)
                return new HttpResponseMessage(Failure) { Content = new StringContent(JsonSerializer.Serialize(new
                { error = new { message = "Provider returned error", metadata = new { raw = Message, provider_name = "Offline fixture" } } }), Encoding.UTF8, "application/json") };
            using var bitmap = new SKBitmap(32, 32);
            using var canvas = new SKCanvas(bitmap);
            canvas.Clear(SKColors.Blue);
            using var png = bitmap.Encode(SKEncodedImageFormat.Png, 100);
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(JsonSerializer.Serialize(new
            { data = new[] { new { b64_json = Convert.ToBase64String(png.ToArray()) } } }), Encoding.UTF8, "application/json") };
        }
    }
}
