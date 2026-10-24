using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory;

// Direct public OpenAI/Anthropic endpoints. This adapter lets both providers run as real MAF AIAgents.
public sealed class ModelGateway : IDisposable
{
    private readonly BookConfig config;
    private readonly string openai, anthropic;
    private readonly ILogger log;
    private readonly HttpClient http = new() { Timeout = TimeSpan.FromMinutes(4) };
    public ModelGateway(BookConfig config, string openai, string anthropic, ILogger log)
        => (this.config, this.openai, this.anthropic, this.log) = (config, openai, anthropic, log);

    public async Task<string> Agent(string subject, string name, string provider, string model, string instructions,
        string prompt, Artifacts files, string stage, CancellationToken ct)
    {
        var inputs = Data.Write(new
        {
            provider,
            model,
            instructions,
            prompt
        });
        return await files.Cached($"cache/{stage}.json", inputs, async () =>
        {
            for (int attempt = 1; ; attempt++)
            {
                log.LogInformation("[{Chapter}][{Agent}][{Stage}] START {Provider}/{Model}", subject, name, stage, provider, model);
                var adapter = new ProviderChatClient(this, provider, model, subject, name, files, stage + $"-attempt-{attempt}-{Guid.NewGuid():N}");
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
                    log.LogInformation("[{Chapter}][{Agent}][{Stage}] COMPLETE", subject, name, stage);
                    return text;
                }
                catch (Exception ex) when (attempt < config.MaxAttempts && ex is JsonException or InvalidDataException)
                {
                    log.LogWarning("[{Chapter}][{Agent}][{Stage}] Invalid structured output; retry {Attempt}", subject, name, stage, attempt);
                }
            }
        });
    }

    public async Task<JsonElement> Search(string subject, Artifacts files, CancellationToken ct)
    {
        var tool = new Dictionary<string, object> { ["type"] = "web_search" };
        if (config.AllowedSourceDomains.Count > 0)
        {
            tool["filters"] = new
            {
                allowed_domains = config.AllowedSourceDomains
            };
        }

        var prompt = $"Research {subject} for a responsible children's historical biography. Find at least {config.MaxSources} genuine accessible sources. " +
            "Prefer universities, museums, archives, scholarly biographies and government institutions. Cover life chronology, context, achievements and contested claims. " +
            "Cite each source URL. Do not invent references. Search the web now.";
        var text = await files.Cached("cache/search.json", config.ResearchModel + prompt + Data.Write(tool), async () =>
        {
            log.LogInformation("[{Chapter}][ResearchAgent][SEARCH] START OpenAI/{Model}", subject, config.ResearchModel);
            var response = await Post("openai", "https://api.openai.com/v1/responses", new
            {
                model = config.ResearchModel,
                tools = new[] { tool },
                tool_choice = "required",
                max_output_tokens = 5000,
                input = prompt,
                include = new[] { "web_search_call.action.sources" }
            }, ct);
            await files.Save("research/search-response.json", response.GetRawText());
            Usage(response, subject, "ResearchAgent", "openai", config.ResearchModel);
            if (response.GetProperty("status").GetString() != "completed"
                || !response.GetProperty("output").EnumerateArray().Any(x => x.GetProperty("type").GetString() == "web_search_call"))
            {
                throw new InvalidDataException("Research did not complete a real web search.");
            }

            return response.GetRawText();
        });
        return JsonDocument.Parse(text).RootElement.Clone();
    }

    private async Task<ChatResponse> Chat(string provider, string model, IEnumerable<ChatMessage> messages,
        string subject, string name, Artifacts files, string stage, CancellationToken ct)
    {
        var list = messages.ToList();
        object body;
        string endpoint;
        if (provider == "anthropic")
        {
            endpoint = "https://api.anthropic.com/v1/messages";
            body = new
            {
                model,
                max_tokens = 5000,
                system = string.Join("\n", list.Where(m => m.Role == ChatRole.System).Select(m => m.Text)),
                messages = list.Where(m => m.Role != ChatRole.System).Select(m => new { role = m.Role == ChatRole.Assistant ? "assistant" : "user", content = m.Text }).ToArray()
            };
        }
        else
        {
            endpoint = "https://api.openai.com/v1/chat/completions";
            body = new
            {
                model,
                max_completion_tokens = 6000,
                messages = list.Select(m => new { role = m.Role.Value, content = m.Text }).ToArray()
            };
        }
        await files.Save($"provenance/{stage}-request.json", Data.Write(new
        {
            provider,
            model,
            body
        }));
        var response = await Post(provider, endpoint, body, ct);
        await files.Save($"provenance/{stage}-response.json", response.GetRawText());
        Usage(response, subject, name, provider, model);
        string text;
        if (provider == "anthropic")
        {
            if (response.GetProperty("stop_reason").GetString() != "end_turn")
            {
                throw new InvalidDataException("Anthropic response incomplete or refused.");
            }

            text = string.Join("\n", response.GetProperty("content").EnumerateArray().Where(x => x.GetProperty("type").GetString() == "text").Select(x => x.GetProperty("text").GetString()));
        }
        else
        {
            var choice = response.GetProperty("choices")[0];
            if (choice.GetProperty("finish_reason").GetString() != "stop")
            {
                throw new InvalidDataException("OpenAI response incomplete or refused.");
            }

            text = choice.GetProperty("message").GetProperty("content").GetString() ?? "";
        }
        return new ChatResponse(new ChatMessage(ChatRole.Assistant, text));
    }
    private void Usage(JsonElement response, string chapter, string agent, string provider, string model)
    {
        if (response.TryGetProperty("usage", out var usage))
        {
            log.LogInformation("[{Chapter}][{Agent}][USAGE] {Provider}/{Model} tokens={Usage}; estimated cost unavailable (no price table configured)", chapter, agent, provider, model, usage.GetRawText());
        }
    }
    private async Task<JsonElement> Post(string provider, string url, object body, CancellationToken ct)
    {
        for (int attempt = 1; ; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, url);
                if (provider == "anthropic")
                {
                    request.Headers.Add("x-api-key", anthropic);
                    request.Headers.Add("anthropic-version", "2023-06-01");
                }
                else
                {
                    request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", openai);
                }

                request.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
                using var response = await http.SendAsync(request, ct);
                if ((response.StatusCode == HttpStatusCode.TooManyRequests || (int)response.StatusCode >= 500 || response.StatusCode == HttpStatusCode.RequestTimeout) && attempt < config.MaxAttempts)
                {
                    var delay = response.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(Math.Pow(2, attempt) + Random.Shared.NextDouble());
                    log.LogWarning("[API][{Provider}][RETRY] HTTP {Status}; attempt {Attempt}", provider, (int)response.StatusCode, attempt);
                    await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(delay.TotalSeconds, 1, 45)), ct);
                    continue;
                }
                // Do not log response error bodies: upstream errors may echo sensitive inputs.
                response.EnsureSuccessStatusCode();
                using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(ct));
                return document.RootElement.Clone();
            }
            catch (Exception ex) when (attempt < config.MaxAttempts && !ct.IsCancellationRequested
                && (ex is TaskCanceledException || ex is HttpRequestException { StatusCode: null }))
            {
                log.LogWarning("[API][{Provider}][RETRY] Transport failure; attempt {Attempt}", provider, attempt);
                await Task.Delay(TimeSpan.FromSeconds(Math.Pow(2, attempt)), ct);
            }
        }
    }
    public void Dispose() => http.Dispose();
    private sealed class ProviderChatClient(ModelGateway gateway, string provider, string model, string subject, string name, Artifacts files, string stage) : IChatClient
    {
        public Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
            => gateway.Chat(provider, model, messages, subject, name, files, stage, cancellationToken);
        public IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
            => throw new NotSupportedException("This application uses non-streaming model responses and live workflow event logging.");
        public object? GetService(Type serviceType, object? serviceKey = null) => serviceKey is null && serviceType.IsInstanceOfType(this) ? this : null;
        public void Dispose()
        {
        }
    }
}
