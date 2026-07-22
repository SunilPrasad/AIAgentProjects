using System.ClientModel;
using System.Text.Json;
using CalculateTotalRevenue.Agents;
using CalculateTotalRevenue.Configuration;
using CalculateTotalRevenue.Models;
using CalculateTotalRevenue.Services;
using CalculateTotalRevenue.Tools;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using OpenAI;
using OpenAI.Chat;

var builder = Host.CreateApplicationBuilder(args);

builder.Logging.ClearProviders();
builder.Logging.AddSimpleConsole(o =>
{
    o.SingleLine = true;
    o.TimestampFormat = "HH:mm:ss ";
});
builder.Logging.SetMinimumLevel(LogLevel.Information);
// Native framework logging middleware (UseFunctionInvocation/UseLogging) emits tool-call detail at Debug.
builder.Logging.AddFilter("Microsoft.Extensions.AI", LogLevel.Debug);

builder.Services.Configure<AgentOptions>(builder.Configuration.GetSection("Agent"));
builder.Services.PostConfigure<AgentOptions>(o =>
    o.ApiKey = Environment.GetEnvironmentVariable("OPENROUTER_API_KEY"));

builder.Services.Configure<ExchangeRateOptions>(builder.Configuration.GetSection("ExchangeRate"));

builder.Services.AddHttpClient<IExchangeRateProvider, FrankfurterExchangeRateProvider>((sp, client) =>
{
    var options = sp.GetRequiredService<IOptions<ExchangeRateOptions>>().Value;
    client.BaseAddress = new Uri(options.BaseUrl);
    client.Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds);
})
.AddStandardResilienceHandler();

builder.Services.AddSingleton<CurrencyConversionTool>();
builder.Services.AddSingleton<ProfitCalculationTool>();

builder.Services.AddSingleton<IChatClient>(sp =>
{
    var options = sp.GetRequiredService<IOptions<AgentOptions>>().Value;
    if (string.IsNullOrWhiteSpace(options.ApiKey))
    {
        throw new InvalidOperationException(
            "The OPENROUTER_API_KEY environment variable is not set. Set it before running, e.g. " +
            "`setx OPENROUTER_API_KEY \"sk-or-...\"` on Windows (then restart your shell).");
    }

    var chatClient = new ChatClient(
        options.ModelId,
        new ApiKeyCredential(options.ApiKey),
        new OpenAIClientOptions { Endpoint = new Uri(options.Endpoint) });

    return chatClient.AsIChatClient();
});

builder.Services.AddSingleton(sp => ProfitAgentFactory.Create(
    sp.GetRequiredService<IChatClient>(),
    sp.GetRequiredService<CurrencyConversionTool>(),
    sp.GetRequiredService<ProfitCalculationTool>(),
    sp.GetRequiredService<ILoggerFactory>()));

using IHost host = builder.Build();

var logger = host.Services.GetRequiredService<ILogger<Program>>();

AIAgent agent;
try
{
    agent = host.Services.GetRequiredService<AIAgent>();
}
catch (InvalidOperationException ex)
{
    logger.LogCritical("Startup configuration error: {Message}", ex.Message);
    return 1;
}

string[] examples =
[
    "Our profits this quarter were 1200 USD, 850 EUR, and 300 GBP. What is the total profit in USD?",
    "Profits were 500 USD and 700 USD. What is the total profit in USD?",
    "Convert 100 XYZ to USD and add it to 50 USD. What is the total profit in USD?"
];

foreach (var prompt in examples)
{
    Console.WriteLine();
    Console.WriteLine(new string('=', 80));
    logger.LogInformation("Prompt: {Prompt}", prompt);

    try
    {
        AgentResponse response = await agent.RunAsync(prompt);
        PrintReport(response.Text, logger);
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Agent run failed for prompt: {Prompt}", prompt);
    }
}

return 0;

static void PrintReport(string responseText, ILogger logger)
{
    TotalProfitReport? report;
    try
    {
        report = JsonSerializer.Deserialize<TotalProfitReport>(responseText, ReportSerialization.Options);
    }
    catch (JsonException)
    {
        logger.LogWarning("Could not parse a structured report from the agent's response.");
        Console.WriteLine(responseText);
        return;
    }

    if (report is null)
    {
        Console.WriteLine(responseText);
        return;
    }

    Console.WriteLine($"Success         : {report.Success}");
    Console.WriteLine($"Target currency : {report.TargetCurrency}");

    var originalEntries = report.OriginalEntries ?? [];
    var convertedEntries = report.ConvertedEntries ?? [];

    Console.WriteLine("Original values :");
    foreach (var entry in originalEntries)
    {
        Console.WriteLine($"  - {entry.Amount} {entry.Currency}");
    }

    if (convertedEntries.Count > 0)
    {
        Console.WriteLine("Converted values:");
        foreach (var entry in convertedEntries)
        {
            Console.WriteLine(
                $"  - {entry.OriginalAmount} {entry.OriginalCurrency} -> " +
                $"{entry.ConvertedAmount} {report.TargetCurrency} " +
                $"(rate {entry.ExchangeRate} as of {entry.RateDate})");
        }
    }

    Console.WriteLine(
        report.FinalTotalProfit is { } total
            ? $"Final total     : {total} {report.TargetCurrency}"
            : "Final total     : (not produced)");

    Console.WriteLine($"Notes           : {report.Notes}");
}
