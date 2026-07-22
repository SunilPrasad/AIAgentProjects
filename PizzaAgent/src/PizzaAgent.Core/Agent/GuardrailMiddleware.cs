using System.Runtime.CompilerServices;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace PizzaAgent.Core.Agent;

public static class GuardrailMiddleware
{
    private const int MaxInputLength = 500;

    private static readonly string[] InjectionPatterns =
    [
        "ignore previous instructions",
        "ignore all instructions",
        "you are now",
        "pretend you are",
        "act as if you are",
        "your new instructions",
        "disregard your",
        "override your",
        "forget your instructions",
        "reveal your instructions",
        "show your system prompt",
        "repeat your system prompt",
        "what are your instructions",
        "### instruction",
        "[system]",
        "<system>",
        "jailbreak",
        "dan mode",
    ];

    private const string BlockedResponse =
        "I'm just here to help with pizza orders! What can I get for you?";

    private const string TooLongResponse =
        "That message is a bit long for me! Could you keep it under 500 characters?";

    /// <summary>
    /// Wraps the agent with a guardrail middleware that blocks prompt injection
    /// and oversized inputs before they reach the LLM.
    ///
    /// Production upgrade: replace this with AgentGuard's ML-based classifier:
    ///   agent.AsBuilder().UseAgentGuard(g => g.BlockPromptInjectionWithDefender()).Build()
    /// </summary>
    public static AIAgent Apply(AIAgent agent, Action<string>? log = null) =>
        agent.AsBuilder()
             .Use(
                 runFunc: (messages, session, options, inner, ct) =>
                     RunGuarded(messages, session, options, inner, ct, log),
                 runStreamingFunc: (messages, session, options, inner, ct) =>
                     StreamGuarded(messages, session, options, inner, ct, log))
             .Build();

    private static (bool Blocked, string Message) Check(string input, Action<string>? log)
    {
        if (input.Length > MaxInputLength)
        {
            log?.Invoke($"[guard:too_long] length={input.Length}");
            return (true, TooLongResponse);
        }

        var lower = input.ToLowerInvariant();
        foreach (var pattern in InjectionPatterns)
        {
            if (lower.Contains(pattern))
            {
                log?.Invoke($"[guard:injection] matched=\"{pattern}\"");
                return (true, BlockedResponse);
            }
        }

        return (false, string.Empty);
    }

    private static async Task<AgentResponse> RunGuarded(
        IEnumerable<ChatMessage> messages,
        AgentSession? session,
        AgentRunOptions? options,
        AIAgent inner,
        CancellationToken ct,
        Action<string>? log)
    {
        var text = messages.LastOrDefault()?.Text ?? string.Empty;
        var (blocked, message) = Check(text, log);

        if (blocked)
            return new AgentResponse([new ChatMessage(ChatRole.Assistant, message)]);

        return await inner.RunAsync(messages, session, options, ct);
    }

    private static async IAsyncEnumerable<AgentResponseUpdate> StreamGuarded(
        IEnumerable<ChatMessage> messages,
        AgentSession? session,
        AgentRunOptions? options,
        AIAgent inner,
        [EnumeratorCancellation] CancellationToken ct,
        Action<string>? log)
    {
        var text = messages.LastOrDefault()?.Text ?? string.Empty;
        var (blocked, message) = Check(text, log);

        if (blocked)
        {
            yield return new AgentResponseUpdate
            {
                Role = ChatRole.Assistant,
                Contents = [new TextContent(message)],
                ResponseId = Guid.NewGuid().ToString(),
                MessageId = Guid.NewGuid().ToString(),
            };
            yield break;
        }

        await foreach (var update in inner.RunStreamingAsync(messages, session, options, ct))
            yield return update;
    }
}
