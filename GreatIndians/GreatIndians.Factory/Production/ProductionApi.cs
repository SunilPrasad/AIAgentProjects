using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Schema;
using Microsoft.Extensions.Logging;
using SkiaSharp;

namespace GreatIndians.Factory.Production;

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
                var response = await Post("chat/completions", body, ct);
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

    public async Task<string> GenerateAsync(
        string stage, string prompt, string aspectRatio, IReadOnlyList<string> references,
        Artifacts files, CancellationToken ct, string? model = null)
    {
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

        var body = new
        {
            model = imageModel, prompt, n = 1,
            resolution = config.ImageResolution, aspect_ratio = aspectRatio, output_format = "png",
            input_references = references.Select(path => new { type = "image_url", image_url = new { url = DataUrl(path) } }).ToArray()
        };
        await files.Save($"provenance/{stage}-request.json", input);
        log.LogInformation("[PDF][{Stage}][GENERATE] OpenRouter/{Model}; aspect={Ratio}; resolution={Resolution}",
            stage, imageModel, aspectRatio, config.ImageResolution);
        var response = await Post("images", body, ct);
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

    private async Task<JsonElement> Post(string route, object body, CancellationToken ct)
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
                if (((int)response.StatusCode >= 500 || response.StatusCode is HttpStatusCode.TooManyRequests or HttpStatusCode.RequestTimeout)
                    && attempt < config.MaxApiAttempts)
                {
                    var wait = response.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(Math.Pow(2, attempt));
                    log.LogWarning("[PDF][API][RETRY] HTTP {Status}; attempt={Attempt}", (int)response.StatusCode, attempt);
                    await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(wait.TotalSeconds, 1, 45)), ct);
                    continue;
                }
                response.EnsureSuccessStatusCode();
                using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(ct));
                if (document.RootElement.TryGetProperty("error", out _))
                {
                    throw new InvalidDataException("OpenRouter returned an API error; finalisation stopped.");
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
