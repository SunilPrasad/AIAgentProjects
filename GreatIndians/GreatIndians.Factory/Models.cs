using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory;

// OpenRouter supplies a shared transport; each role remains a real Microsoft Agent Framework agent.
public sealed class ModelGateway : IDisposable
{
    private const string Endpoint = "https://openrouter.ai/api/v1/chat/completions";
    private const string Provider = "openrouter";

    private readonly BookConfig config;
    private readonly string apiKey;
    private readonly ILogger log;
    private readonly HttpClient http = new()
    {
        Timeout = TimeSpan.FromMinutes(4)
    };

    public ModelGateway(BookConfig config, string apiKey, ILogger log)
    {
        this.config = config;
        this.apiKey = apiKey;
        this.log = log;
    }

    public async Task<string> Agent(
        string subject,
        string name,
        string provider,
        string model,
        string instructions,
        string prompt,
        Artifacts files,
        string stage,
        CancellationToken ct)
    {
        if (provider != Provider)
        {
            throw new ArgumentException("All model calls must use OpenRouter.", nameof(provider));
        }

        var inputs = Data.Write(new { provider, model, instructions, prompt });

        return await files.Cached($"cache/{stage}.json", inputs, async () =>
        {
            for (int attempt = 1; ; attempt++)
            {
                log.LogInformation(
                    "[{Chapter}][{Agent}][{Stage}] START OpenRouter/{Model}",
                    subject, name, stage, model);

                var requestStage = $"{stage}-attempt-{attempt}-{Guid.NewGuid():N}";
                using var adapter = new OpenRouterChatClient(
                    this, model, subject, name, files, requestStage);

                AIAgent agent = adapter.AsAIAgent(instructions: instructions, name: name);

                try
                {
                    var response = await agent.RunAsync(prompt, cancellationToken: ct);
                    var text = response.Text;

                    if (string.IsNullOrWhiteSpace(text))
                    {
                        throw new InvalidDataException("Model returned an empty response.");
                    }

                    if (stage.Contains("review") || stage == "ledger")
                    {
                        text = Data.JsonObject(text);

                        if (stage.Contains("review"))
                        {
                            Data.Read<Review>(text).Validate();
                        }
                        else if (Data.Read<Evidence>(text).Claims is not { Count: > 0 })
                        {
                            throw new InvalidDataException("Empty evidence ledger.");
                        }
                    }

                    log.LogInformation(
                        "[{Chapter}][{Agent}][{Stage}] COMPLETE", subject, name, stage);

                    return text;
                }
                catch (Exception exception) when (
                    attempt < config.MaxAttempts && exception is JsonException or InvalidDataException)
                {
                    log.LogWarning(
                        "[{Chapter}][{Agent}][{Stage}] Invalid model output; retry {Attempt}",
                        subject, name, stage, attempt);
                }
            }
        });
    }

    public async Task<JsonElement> Search(string subject, Artifacts files, CancellationToken ct)
    {
        var parameters = new Dictionary<string, object>
        {
            ["engine"] = "exa",
            ["max_results"] = config.MaxSources,
            ["max_total_results"] = config.MaxSources * 2,
            ["max_uses"] = 3
        };

        if (config.AllowedSourceDomains.Count > 0)
        {
            parameters["allowed_domains"] = config.AllowedSourceDomains;
        }

        var prompt = $"Research {subject} for a responsible children's historical biography. " +
            $"Search the web now and cite at least {config.MaxSources} genuine accessible sources. " +
            "Prefer universities, museums, archives, scholarly biographies and government institutions. " +
            "Cover life chronology, context, achievements and contested claims. " +
            "Use the web-search tool and include its source citations. Do not invent references.";

        var body = new
        {
            model = config.ResearchModel,
            messages = new[] { new { role = "user", content = prompt } },
            tools = new[] { new { type = "openrouter:web_search", parameters } },
            tool_choice = "required",
            max_tool_calls = 3,
            max_tokens = 5000,
            stream = false
        };

        var text = await files.Cached("cache/search.json", Data.Write(body), async () =>
        {
            for (int attempt = 1; ; attempt++)
            {
                log.LogInformation(
                    "[{Chapter}][ResearchAgent][SEARCH] START OpenRouter/{Model}",
                    subject, config.ResearchModel);

                var requestStage = $"search-attempt-{attempt}-{Guid.NewGuid():N}";
                await files.Save($"provenance/{requestStage}-request.json", Data.Write(body));

                var response = await Post(body, subject, "ResearchAgent", "SEARCH", ct);
                await files.Save($"provenance/{requestStage}-response.json", response.GetRawText());
                await files.Save("research/search-response.json", response.GetRawText());
                LogUsage(response, subject, "ResearchAgent", config.ResearchModel);

                try
                {
                    ReadText(response);
                    var citations = ReadCitations(response);

                    if (citations.Count == 0)
                    {
                        throw new InvalidDataException(
                            "OpenRouter research returned no web-search citation metadata; drafting blocked.");
                    }

                    log.LogInformation(
                        "[{Chapter}][ResearchAgent][SEARCH] COMPLETE: {Count} cited sources",
                        subject, citations.Count);

                    // Only structured search citations can become source candidates.
                    // URLs invented in the model's prose are never used for retrieval.
                    return Data.Write(new { sources = citations });
                }
                catch (InvalidDataException) when (attempt < config.MaxAttempts)
                {
                    log.LogWarning(
                        "[{Chapter}][ResearchAgent][SEARCH] Incomplete search or missing citations; retry {Attempt}",
                        subject, attempt);
                }
            }
        });

        using var document = JsonDocument.Parse(text);
        return document.RootElement.Clone();
    }

    private sealed record SearchCitation(string Url, string Title);

    private static List<SearchCitation> ReadCitations(JsonElement response)
    {
        var citations = new List<SearchCitation>();
        var message = ReadChoice(response).GetProperty("message");

        if (!message.TryGetProperty("annotations", out var annotations)
            || annotations.ValueKind != JsonValueKind.Array)
        {
            return citations;
        }

        foreach (var annotation in annotations.EnumerateArray())
        {
            if (!annotation.TryGetProperty("type", out var type)
                || type.GetString() != "url_citation"
                || !annotation.TryGetProperty("url_citation", out var citation)
                || !citation.TryGetProperty("url", out var urlValue)
                || urlValue.ValueKind != JsonValueKind.String)
            {
                continue;
            }

            var url = urlValue.GetString();

            if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)
                || uri.Scheme != Uri.UriSchemeHttps)
            {
                continue;
            }

            var title = citation.TryGetProperty("title", out var titleValue)
                && titleValue.ValueKind == JsonValueKind.String
                    ? titleValue.GetString() ?? uri.Host
                    : uri.Host;

            if (citations.All(existing => existing.Url != uri.AbsoluteUri))
            {
                citations.Add(new SearchCitation(uri.AbsoluteUri, title));
            }
        }

        return citations;
    }

    private async Task<ChatResponse> Chat(
        string model,
        IEnumerable<ChatMessage> messages,
        string subject,
        string name,
        Artifacts files,
        string stage,
        CancellationToken ct)
    {
        var body = new
        {
            model,
            max_tokens = 6000,
            stream = false,
            messages = messages.Select(message => new
            {
                role = message.Role.Value,
                content = message.Text
            }).ToArray()
        };

        await files.Save($"provenance/{stage}-request.json", Data.Write(new
        {
            provider = Provider,
            model,
            body
        }));

        var response = await Post(body, subject, name, stage, ct);
        await files.Save($"provenance/{stage}-response.json", response.GetRawText());
        LogUsage(response, subject, name, model);

        return new ChatResponse(new ChatMessage(ChatRole.Assistant, ReadText(response)));
    }

    private static JsonElement ReadChoice(JsonElement response)
    {
        if (!response.TryGetProperty("choices", out var choices)
            || choices.ValueKind != JsonValueKind.Array
            || choices.GetArrayLength() == 0)
        {
            throw new InvalidDataException("OpenRouter returned no completion choices.");
        }

        return choices[0];
    }

    private static string ReadText(JsonElement response)
    {
        var choice = ReadChoice(response);

        if (!choice.TryGetProperty("finish_reason", out var finishReason)
            || finishReason.GetString() != "stop")
        {
            throw new InvalidDataException("OpenRouter response incomplete, refused or awaiting tools.");
        }

        if (!choice.TryGetProperty("message", out var message)
            || !message.TryGetProperty("content", out var content)
            || content.ValueKind != JsonValueKind.String
            || string.IsNullOrWhiteSpace(content.GetString()))
        {
            throw new InvalidDataException("OpenRouter returned no text content.");
        }

        return content.GetString()!;
    }

    private void LogUsage(JsonElement response, string chapter, string agent, string requestedModel)
    {
        var actualModel = response.TryGetProperty("model", out var model)
            && model.ValueKind == JsonValueKind.String
                ? model.GetString() ?? requestedModel
                : requestedModel;

        if (response.TryGetProperty("usage", out var usage) && usage.ValueKind == JsonValueKind.Object)
        {
            var cost = usage.TryGetProperty("cost", out var value)
                && value.ValueKind == JsonValueKind.Number
                    ? $"{value.GetRawText()} USD (reported by OpenRouter)"
                    : "unavailable";

            log.LogInformation(
                "[{Chapter}][{Agent}][USAGE] OpenRouter/{Model}; usage={Usage}; cost={Cost}",
                chapter, agent, actualModel, usage.GetRawText(), cost);
        }
    }

    private async Task<JsonElement> Post(
        object body,
        string chapter,
        string agent,
        string stage,
        CancellationToken ct)
    {
        for (int attempt = 1; ; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, Endpoint);
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
                request.Headers.Add("X-OpenRouter-Title", "Great Indians Book Factory");
                request.Content = new StringContent(
                    JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");

                using var response = await http.SendAsync(request, ct);

                var transient = response.StatusCode is HttpStatusCode.TooManyRequests
                    or HttpStatusCode.RequestTimeout
                    || (int)response.StatusCode >= 500;

                if (transient && attempt < config.MaxAttempts)
                {
                    var delay = response.Headers.RetryAfter?.Delta
                        ?? TimeSpan.FromSeconds(Math.Pow(2, attempt) + Random.Shared.NextDouble());

                    log.LogWarning(
                        "[{Chapter}][{Agent}][{Stage}] OpenRouter HTTP {Status}; retry {Attempt}",
                        chapter, agent, stage, (int)response.StatusCode, attempt);

                    await Task.Delay(
                        TimeSpan.FromSeconds(Math.Clamp(delay.TotalSeconds, 1, 45)), ct);

                    continue;
                }

                // Error bodies may echo sensitive inputs, so keep them out of logs.
                response.EnsureSuccessStatusCode();
                using var document = JsonDocument.Parse(
                    await response.Content.ReadAsStringAsync(ct));

                if (document.RootElement.TryGetProperty("error", out _))
                {
                    throw new InvalidDataException("OpenRouter returned an API error; no approval granted.");
                }

                return document.RootElement.Clone();
            }
            catch (Exception exception) when (
                attempt < config.MaxAttempts
                && !ct.IsCancellationRequested
                && (exception is TaskCanceledException
                    || exception is HttpRequestException { StatusCode: null }))
            {
                log.LogWarning(
                    "[{Chapter}][{Agent}][{Stage}] OpenRouter transport failure; retry {Attempt}",
                    chapter, agent, stage, attempt);

                await Task.Delay(TimeSpan.FromSeconds(Math.Pow(2, attempt)), ct);
            }
        }
    }

    public void Dispose() => http.Dispose();

    private sealed class OpenRouterChatClient(
        ModelGateway gateway,
        string model,
        string subject,
        string name,
        Artifacts files,
        string stage) : IChatClient
    {
        public Task<ChatResponse> GetResponseAsync(
            IEnumerable<ChatMessage> messages,
            ChatOptions? options = null,
            CancellationToken cancellationToken = default)
            => gateway.Chat(model, messages, subject, name, files, stage, cancellationToken);

        public IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
            IEnumerable<ChatMessage> messages,
            ChatOptions? options = null,
            CancellationToken cancellationToken = default)
            => throw new NotSupportedException(
                "This application uses non-streaming model responses and live workflow event logging.");

        public object? GetService(Type serviceType, object? serviceKey = null)
            => serviceKey is null && serviceType.IsInstanceOfType(this) ? this : null;

        public void Dispose()
        {
        }
    }
}
