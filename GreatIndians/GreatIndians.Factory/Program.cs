using GreatIndians.Factory;
using Microsoft.Extensions.Logging;

using var cancellation = new CancellationTokenSource();

Console.CancelKeyPress += (_, eventArgs) =>
{
    eventArgs.Cancel = true;
    cancellation.Cancel();
};

try
{
    string configFile;

    if (args.Length > 0)
    {
        configFile = args[0];
    }
    else if (File.Exists("book.json"))
    {
        configFile = "book.json";
    }
    else
    {
        configFile = Path.Combine(AppContext.BaseDirectory, "book.json");
    }

    var configPath = Path.GetFullPath(configFile);
    var configDirectory = Path.GetDirectoryName(configPath)!;
    var configJson = await File.ReadAllTextAsync(configPath);
    var config = Data.Read<BookConfig>(configJson);

    config.Validate();

    var stylePath = Path.Combine(configDirectory, config.StyleBible);
    var style = await File.ReadAllTextAsync(stylePath);

    if (string.IsNullOrWhiteSpace(style))
    {
        throw new InvalidDataException("Style Bible is empty.");
    }

    var outputDirectory = Path.GetFullPath(config.OutputDirectory, configDirectory);
    Directory.CreateDirectory(outputDirectory);

    using var runLock = new FileStream(
        Path.Combine(outputDirectory, ".run.lock"),
        FileMode.OpenOrCreate,
        FileAccess.ReadWrite,
        FileShare.None);

    using var logging = LoggerFactory.Create(builder =>
    {
        builder.AddSimpleConsole(options =>
        {
            options.TimestampFormat = "[HH:mm:ss] ";
            options.SingleLine = true;
        });

        builder.AddProvider(new FileLogProvider(
            Path.Combine(outputDirectory, "execution.log")));
    });

    var logger = logging.CreateLogger("BookFactory");

    Console.WriteLine(
        "GREAT INDIANS — AI BOOK WRITING FACTORY | Microsoft Agent Framework | .NET 10");

    logger.LogInformation(
        "[BOOK][Startup][LOAD] {Title}; {Count} chapters; automatic mode; Style Bible loaded",
        config.BookTitle,
        config.Personalities.Count);

    var openaiKey = Environment.GetEnvironmentVariable("OPENAI_API_KEY");
    var anthropicKey = Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY");

    if (string.IsNullOrWhiteSpace(openaiKey) || string.IsNullOrWhiteSpace(anthropicKey))
    {
        throw new InvalidOperationException(
            "Set OPENAI_API_KEY and ANTHROPIC_API_KEY before running. No Azure account is required.");
    }

    using var api = new ModelGateway(config, openaiKey, anthropicKey, logger);
    var factory = new BookFactory(config, style, outputDirectory, api, logger);

    Environment.ExitCode = await factory.RunAsync(cancellation.Token);
}
catch (OperationCanceledException)
{
    Console.Error.WriteLine("Cancelled. Saved stages will be reused on restart.");
    Environment.ExitCode = 130;
}
catch (Exception exception)
{
    Console.Error.WriteLine(
        $"Startup/execution failed: {exception.GetType().Name}: {exception.Message}");

    Environment.ExitCode = 1;
}
