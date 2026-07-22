using Microsoft.Agents.AI;
using PizzaAgent.Core.Agent;

// Supports OpenAI or any OpenAI-compatible provider (e.g. OpenRouter)
string apiKey;
string? baseUrl;
string model;

if (Environment.GetEnvironmentVariable("OPENROUTER_API_KEY") is { Length: > 0 } orKey)
{
    apiKey  = orKey;
    baseUrl = "https://openrouter.ai/api/v1";
    model   = Environment.GetEnvironmentVariable("OPENROUTER_MODEL") ?? "openai/gpt-4o-mini";
    Console.WriteLine("[Provider: OpenRouter]");
}
else if (Environment.GetEnvironmentVariable("OPENAI_API_KEY") is { Length: > 0 } oaiKey)
{
    apiKey  = oaiKey;
    baseUrl = null;
    model   = Environment.GetEnvironmentVariable("OPENAI_MODEL") ?? "gpt-4o-mini";
    Console.WriteLine("[Provider: OpenAI]");
}
else
{
    throw new InvalidOperationException(
        "No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY.");
}

Console.ForegroundColor = ConsoleColor.Yellow;
Console.WriteLine("╔══════════════════════════════════════╗");
Console.WriteLine("║       Mario's Pizzeria - Order       ║");
Console.WriteLine("╚══════════════════════════════════════╝");
Console.ResetColor();
Console.WriteLine();

var (agent, _) = PizzaAgentBuilder.Build(apiKey, model, baseUrl, toolLog =>
{
    var prev = Console.ForegroundColor;
    Console.ForegroundColor = ConsoleColor.DarkYellow;
    Console.WriteLine($"\n  >> [tool] {toolLog}");
    Console.ForegroundColor = prev;
});
AgentSession session = await agent.CreateSessionAsync();

Console.ForegroundColor = ConsoleColor.Green;
Console.WriteLine("Mario: Welcome to Mario's Pizzeria! I'm Mario, your ordering assistant.");
Console.WriteLine("       What can I get for you today?");
Console.ResetColor();
Console.WriteLine();
Console.WriteLine("(Type 'quit' or 'exit' to leave)\n");

while (true)
{
    Console.ForegroundColor = ConsoleColor.Cyan;
    Console.Write("You: ");
    Console.ResetColor();

    var input = Console.ReadLine();

    if (string.IsNullOrWhiteSpace(input))
        continue;

    if (input.Equals("quit", StringComparison.OrdinalIgnoreCase) ||
        input.Equals("exit", StringComparison.OrdinalIgnoreCase))
    {
        Console.ForegroundColor = ConsoleColor.Yellow;
        Console.WriteLine("\nMario: Grazie! Come back soon! Ciao!");
        Console.ResetColor();
        break;
    }

    Console.ForegroundColor = ConsoleColor.Green;
    Console.Write("\nMario: ");
    Console.ResetColor();

    try
    {
        await foreach (var update in agent.RunStreamingAsync(input, session))
        {
            Console.Write(update);
        }
    }
    catch (Exception ex)
    {
        Console.ForegroundColor = ConsoleColor.Red;
        Console.WriteLine($"\n[Error] {ex.Message}");
        Console.ResetColor();
    }

    Console.WriteLine("\n");
}
