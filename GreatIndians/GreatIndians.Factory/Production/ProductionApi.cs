using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Schema;
using Microsoft.Extensions.Logging;
using SkiaSharp;

namespace GreatIndians.Factory.Production;

public sealed class ProductionApiException(HttpStatusCode status, string detail)
    : HttpRequestException($"OpenRouter HTTP {(int)status}: {detail}", null, status)
{
    public bool CanEscalateDraft => status is HttpStatusCode.BadRequest or HttpStatusCode.NotFound or HttpStatusCode.UnprocessableEntity
        && !System.Text.RegularExpressions.Regex.IsMatch(detail, "safety|content.?policy|content.?filter|prohibited|moderation", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
}

public sealed class ProductionApi : IDisposable
{
    private readonly ProductionConfig config;
    private readonly string key;
    private readonly ILogger log;
    private readonly HttpClient http;
    private readonly bool ownsHttp;
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        TypeInfoResolver = new System.Text.Json.Serialization.Metadata.DefaultJsonTypeInfoResolver(),
        WriteIndented = true
    };

    public ProductionApi(ProductionConfig config, string key, ILogger log, HttpClient? http = null)
    {
        this.config = config;
        this.key = key;
        this.log = log;
        ownsHttp = http is null;
        this.http = http ?? new HttpClient { Timeout = TimeSpan.FromMinutes(10) };
    }

    public async Task<T> JsonAsync<T>(
        string stage, string model, string instructions, string input,
        IReadOnlyList<string> images, Artifacts files, CancellationToken ct, int maxImageEdge = 0)
    {
        var schema = JsonSchemaExporter.GetJsonSchemaAsNode(Json, typeof(T), new JsonSchemaExporterOptions
        {
            TreatNullObliviousAsNonNullable = true
        });
        MakeStrict(schema);
        var content = new List<object> { new { type = "text", text = input } };
        var imageHashes = new List<string>();
        foreach (var path in images)
        {
            imageHashes.Add(ManuscriptReader.HashFile(path));
            content.Add(new { type = "image_url", image_url = new { url = DataUrl(path, maxImageEdge) } });
        }
        var body = new
        {
            model, max_tokens = 6500, stream = false,
            messages = new object[]
            {
                new { role = "system", content = instructions },
                new { role = "user", content }
            },
            response_format = new { type = "json_schema", json_schema = new { name = typeof(T).Name, strict = true, schema } },
            provider = new { require_parameters = true }
        };
        // Original image hashes identify the review; the edge limit only changes the transmitted copy.
        var cacheInput = maxImageEdge > 0
            ? Data.Write(new { model, instructions, input, imageHashes, maxImageEdge, schema })
            : Data.Write(new { model, instructions, input, imageHashes, schema });
        var json = await files.Cached($"cache/{stage}.json", cacheInput, async () =>
        {
            await files.Save($"provenance/{stage}-request.json", cacheInput);
            log.LogInformation("[PDF][{Stage}][START] OpenRouter/{Model}; images={Count}", stage, model, images.Count);
            for (int attempt = 1; attempt <= config.MaxApiAttempts; attempt++)
            {
                var response = await Post("chat/completions", body, files, stage, ct);
                await files.Save($"provenance/{stage}-response-{attempt}.json", response.GetRawText());
                LogUsage(stage, response);
                try
                {
                    var choice = response.GetProperty("choices")[0];
                    if (choice.GetProperty("finish_reason").GetString() != "stop")
                        throw new InvalidDataException($"Incomplete structured response at {stage}.");
                    var text = Data.JsonObject(choice.GetProperty("message").GetProperty("content").GetString() ?? "");
                    _ = System.Text.Json.JsonSerializer.Deserialize<T>(text, Json)
                        ?? throw new InvalidDataException($"Empty structured response at {stage}.");
                    return text;
                }
                catch (Exception ex) when (attempt < config.MaxApiAttempts && ex is JsonException or InvalidDataException)
                {
                    log.LogWarning("[PDF][{Stage}][RETRY] Invalid structured response; attempt={Attempt}", stage, attempt);
                }
            }
            throw new InvalidDataException($"Structured response attempts exhausted at {stage}.");
        });
        return System.Text.Json.JsonSerializer.Deserialize<T>(json, Json)
            ?? throw new InvalidDataException($"Invalid cached response at {stage}.");
    }

    private sealed record ImageReceipt(string InputHash, string OutputHash, string Path);
    private sealed record DraftRejection(string InputHash, string FallbackModel, string Reason);

    public async Task<string> GenerateAsync(
        string stage, string prompt, string aspectRatio, IReadOnlyList<string> references,
        Artifacts files, CancellationToken ct, string? model = null)
    {
        if (config.ImageMode == "webOnly")
            throw new InvalidOperationException("Image generation and reuse of generated-image caches are disabled by imageMode=webOnly. Only reviewed Wikimedia photographs are permitted.");
        var imageModel = model ?? config.ImageModel;
        var referenceHashes = references.Select(ManuscriptReader.HashFile).ToArray();
        // Property name kept as ImageModel so receipts made before per-attempt models remain reusable.
        var input = Data.Write(new { ImageModel = imageModel, config.ImageResolution, prompt, aspectRatio, referenceHashes });
        var receiptPath = Path.Combine(files.Root, "cache", stage + "-image.json");
        foreach (var candidateReceipt in new[] { receiptPath }
            .Concat(files.PreviousRoots.Select(root => Path.Combine(root, "cache", stage + "-image.json"))))
        {
            if (!File.Exists(candidateReceipt)) continue;
            try
            {
                var old = Data.Read<ImageReceipt>(await File.ReadAllTextAsync(candidateReceipt, ct));
                if (old.InputHash == Data.Hash(input) && File.Exists(old.Path)
                    && old.OutputHash == ManuscriptReader.HashFile(old.Path))
                {
                    log.LogInformation("[PDF][{Stage}][RESUME] Reusing image with matching prompt/reference hashes", stage);
                    var destination = Path.Combine(files.Root, "artwork", stage + ".png");
                    Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                    if (!destination.Equals(old.Path, StringComparison.OrdinalIgnoreCase))
                        File.Copy(old.Path, destination, true);
                    await files.Save($"cache/{stage}-image.json", Data.Write(old with { Path = destination }));
                    if (candidateReceipt != receiptPath)
                        await files.Save($"provenance/{stage}-reused.json", Data.Write(new { previousReceipt = candidateReceipt, old.InputHash, old.OutputHash }));
                    return destination;
                }
            }
            catch (JsonException)
            {
            }
        }

        bool canEscalate = imageModel == config.DraftImageModel && imageModel != config.ImageModel;
        string rejectionName = $"cache/{stage}-draft-rejection.json";
        if (canEscalate)
        {
            foreach (var sourceRoot in new[] { files.Root }.Concat(files.PreviousRoots))
            {
                string rejectionPath = Path.Combine(sourceRoot, rejectionName);
                if (!File.Exists(rejectionPath)) continue;
                DraftRejection? rejected = null;
                try { rejected = Data.Read<DraftRejection>(await File.ReadAllTextAsync(rejectionPath, ct)); }
                catch (JsonException) { }
                if (rejected is null) continue;
                if (rejected.InputHash == Data.Hash(input) && rejected.FallbackModel == config.ImageModel)
                {
                    if (sourceRoot != files.Root) await files.Save(rejectionName, Data.Write(rejected));
                    log.LogInformation("[PDF][{Stage}][MODEL FALLBACK] Reusing recorded draft rejection; use {Model}", stage, config.ImageModel);
                    return await GenerateAsync(stage, prompt, aspectRatio, references, files, ct, config.ImageModel);
                }
            }
        }

        var body = new
        {
            model = imageModel, prompt, n = 1,
            resolution = config.ImageResolution, aspect_ratio = aspectRatio, output_format = "png",
            input_references = references.Select(path => new { type = "image_url", image_url = new { url = DataUrl(path) } }).ToArray()
        };
        await files.Save($"provenance/{stage}-request.json", input);
        log.LogInformation("[PDF][{Stage}][GENERATE] OpenRouter/{Model}; aspect={Ratio}; resolution={Resolution}",
            stage, imageModel, aspectRatio, config.ImageResolution);
        JsonElement response;
        try
        {
            response = await Post("images", body, files, canEscalate ? stage + "-draft" : stage, ct);
        }
        catch (ProductionApiException ex) when (canEscalate && ex.CanEscalateDraft && !ct.IsCancellationRequested)
        {
            await files.Save(rejectionName, Data.Write(new DraftRejection(Data.Hash(input), config.ImageModel, ex.Message)));
            log.LogWarning("[PDF][{Stage}][MODEL FALLBACK] {Draft} rejected this request: {Reason}. Trying configured main model {Model} once; review requirements unchanged",
                stage, imageModel, ex.Message, config.ImageModel);
            return await GenerateAsync(stage, prompt, aspectRatio, references, files, ct, config.ImageModel);
        }
        LogUsage(stage, response);
        var bytes = Convert.FromBase64String(response.GetProperty("data")[0].GetProperty("b64_json").GetString() ?? "");
        using var bitmap = SKBitmap.Decode(bytes) ?? throw new InvalidDataException("Image response is not a decodable raster image.");
        if (bitmap.Width > 12000 || bitmap.Height > 12000)
        {
            throw new InvalidDataException("Generated image dimensions exceed the supported bounds.");
        }
        int expectedShortEdge = config.ImageResolution switch { "4K" => 2000, "2K" => 1400, _ => 0 };
        if (Math.Min(bitmap.Width, bitmap.Height) < expectedShortEdge)
        {
            log.LogWarning("[PDF][{Stage}][RESOLUTION] Requested {Resolution} but {Model} returned {Width}x{Height}; the same price was charged",
                stage, config.ImageResolution, imageModel, bitmap.Width, bitmap.Height);
        }
        using var encoded = bitmap.Encode(SKEncodedImageFormat.Png, 100);
        var path = Path.Combine(files.Root, "artwork", stage + ".png");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllBytesAsync(path, encoded.ToArray(), ct);
        var receipt = new ImageReceipt(Data.Hash(input), ManuscriptReader.HashFile(path), path);
        await files.Save($"cache/{stage}-image.json", Data.Write(receipt));
        await files.Save($"provenance/{stage}-response.json", Data.Write(new
        {
            image = path, sha256 = receipt.OutputHash, width = bitmap.Width, height = bitmap.Height,
            usage = response.TryGetProperty("usage", out var usage) ? usage : (JsonElement?)null
        }));
        return path;
    }

    private async Task<JsonElement> Post(string route, object body, Artifacts files, string stage, CancellationToken ct)
    {
        for (int attempt = 1; ; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, "https://openrouter.ai/api/v1/" + route);
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
                request.Headers.Add("X-OpenRouter-Title", "Legends of Ancient India Production");
                request.Content = new StringContent(System.Text.Json.JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
                using var response = await http.SendAsync(request, ct);
                if (!response.IsSuccessStatusCode)
                {
                    string error = Redact(await response.Content.ReadAsStringAsync(ct));
                    await files.Save($"provenance/{stage}-http-error-{attempt}.json", Data.Write(new
                    {
                        route, status = (int)response.StatusCode, response.ReasonPhrase, body = error
                    }));
                    if (!((int)response.StatusCode >= 500 || response.StatusCode is HttpStatusCode.TooManyRequests or HttpStatusCode.RequestTimeout)
                        || attempt >= config.MaxApiAttempts)
                        throw new ProductionApiException(response.StatusCode, ErrorDetail(error));
                }
                if (((int)response.StatusCode >= 500 || response.StatusCode is HttpStatusCode.TooManyRequests or HttpStatusCode.RequestTimeout)
                    && attempt < config.MaxApiAttempts)
                {
                    var wait = response.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(Math.Pow(2, attempt));
                    log.LogWarning("[PDF][API][RETRY] HTTP {Status}; attempt={Attempt}", (int)response.StatusCode, attempt);
                    await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(wait.TotalSeconds, 1, 45)), ct);
                    continue;
                }
                using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(ct));
                if (document.RootElement.TryGetProperty("error", out _))
                {
                    string error = Redact(document.RootElement.GetRawText());
                    await files.Save($"provenance/{stage}-http-error-{attempt}.json", error);
                    throw new ProductionApiException(response.StatusCode, ErrorDetail(error));
                }
                return document.RootElement.Clone();
            }
            catch (Exception exception) when (attempt < config.MaxApiAttempts && !ct.IsCancellationRequested
                && (exception is TaskCanceledException || exception is HttpRequestException { StatusCode: null }))
            {
                log.LogWarning("[PDF][API][RETRY] Transport failure; attempt={Attempt}", attempt);
                await Task.Delay(TimeSpan.FromSeconds(Math.Pow(2, attempt)), ct);
            }
        }
    }

    private string Redact(string value)
    {
        if (key.Length > 0) value = value.Replace(key, "[REDACTED]", StringComparison.Ordinal);
        value = System.Text.RegularExpressions.Regex.Replace(value, @"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+", "[IMAGE REDACTED]");
        return value.Length > 16000 ? value[..16000] + " [truncated]" : value;
    }

    private static string ErrorDetail(string raw)
    {
        string detail = raw;
        try
        {
            using var parsed = JsonDocument.Parse(raw);
            if (parsed.RootElement.TryGetProperty("error", out var error) && error.ValueKind == JsonValueKind.Object)
            {
                detail = error.TryGetProperty("message", out var message) ? message.ToString() : error.ToString();
                if (error.TryGetProperty("metadata", out var metadata)) detail += "; " + metadata.ToString();
            }
        }
        catch (JsonException) { }
        detail = Data.Normalize(detail);
        return detail.Length > 2000 ? detail[..2000] + " [truncated; see provenance error file]" : detail;
    }

    private void LogUsage(string stage, JsonElement response)
    {
        if (response.TryGetProperty("usage", out var usage))
        {
            CostMeter.Record("PDF", stage, response.TryGetProperty("model", out var model) ? model.GetString() ?? "" : "", usage);
            log.LogInformation("[PDF][{Stage}][USAGE] {Usage}", stage, usage.GetRawText());
        }
    }

    private static string DataUrl(string path) => DataUrl(path, 0);

    // Vision models bill by image area. Review copies are reduced; generation references stay full size.
    private static string DataUrl(string path, int maxEdge)
    {
        var bytes = File.ReadAllBytes(path);
        if (maxEdge <= 0) return "data:image/png;base64," + Convert.ToBase64String(bytes);
        using var bitmap = SKBitmap.Decode(bytes) ?? throw new InvalidDataException("Cannot decode review image.");
        if (Math.Max(bitmap.Width, bitmap.Height) <= maxEdge) return "data:image/png;base64," + Convert.ToBase64String(bytes);
        double scale = (double)maxEdge / Math.Max(bitmap.Width, bitmap.Height);
        using var resized = bitmap.Resize(new SKImageInfo((int)Math.Round(bitmap.Width * scale), (int)Math.Round(bitmap.Height * scale)),
            new SKSamplingOptions(SKCubicResampler.Mitchell)) ?? throw new InvalidDataException("Cannot resize review image.");
        using var encoded = resized.Encode(SKEncodedImageFormat.Jpeg, 90);
        return "data:image/jpeg;base64," + Convert.ToBase64String(encoded.ToArray());
    }

    private static void MakeStrict(JsonNode? node)
    {
        if (node is JsonObject obj)
        {
            if (obj["properties"] is JsonObject properties)
            {
                obj["additionalProperties"] = false;
                obj["required"] = new JsonArray(properties.Select(property => (JsonNode?)JsonValue.Create(property.Key)).ToArray());
            }
            foreach (var child in obj.ToList())
            {
                MakeStrict(child.Value);
            }
        }
        else if (node is JsonArray array)
        {
            foreach (var child in array)
            {
                MakeStrict(child);
            }
        }
    }

    public void Dispose()
    {
        if (ownsHttp)
        {
            http.Dispose();
        }
    }
}
