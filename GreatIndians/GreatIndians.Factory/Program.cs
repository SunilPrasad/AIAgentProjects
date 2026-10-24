using GreatIndians.Factory;
using Microsoft.Extensions.Logging;

using var cancellation = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancellation.Cancel(); };
try
{
    var configPath = Path.GetFullPath(args.Length == 0 ? (File.Exists("book.json") ? "book.json" : Path.Combine(AppContext.BaseDirectory, "book.json")) : args[0]);
    var config = Data.Read<BookConfig>(await File.ReadAllTextAsync(configPath));
    config.Validate();
    var style = await File.ReadAllTextAsync(Path.Combine(Path.GetDirectoryName(configPath)!, config.StyleBible));
    if (string.IsNullOrWhiteSpace(style)) throw new InvalidDataException("Style Bible is empty.");
    var root = Path.GetFullPath(config.OutputDirectory, Path.GetDirectoryName(configPath)!);
    Directory.CreateDirectory(root);
    using var runLock = new FileStream(Path.Combine(root, ".run.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    using var logging = LoggerFactory.Create(b => b.AddSimpleConsole(o => { o.TimestampFormat = "[HH:mm:ss] "; o.SingleLine = true; })
        .AddProvider(new FileLogProvider(Path.Combine(root, "execution.log"))));
    var logger = logging.CreateLogger("BookFactory");
    Console.WriteLine("GREAT INDIANS — AI BOOK WRITING FACTORY | Microsoft Agent Framework | .NET 10");
    logger.LogInformation("[BOOK][Startup][LOAD] {Title}; {Count} chapters; automatic mode; Style Bible loaded", config.BookTitle, config.Personalities.Count);
    var openai = Environment.GetEnvironmentVariable("OPENAI_API_KEY");
    var anthropic = Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY");
    if (string.IsNullOrWhiteSpace(openai) || string.IsNullOrWhiteSpace(anthropic))
        throw new InvalidOperationException("Set OPENAI_API_KEY and ANTHROPIC_API_KEY before running. No Azure account is required.");
    using var api = new ModelGateway(config, openai, anthropic, logger);
    var factory = new BookFactory(config, style, root, api, logger);
    Environment.ExitCode = await factory.RunAsync(cancellation.Token);
}
catch (OperationCanceledException) { Console.Error.WriteLine("Cancelled. Saved stages will be reused on restart."); Environment.ExitCode = 130; }
catch (Exception ex) { Console.Error.WriteLine($"Startup/execution failed: {ex.GetType().Name}: {ex.Message}"); Environment.ExitCode = 1; }
