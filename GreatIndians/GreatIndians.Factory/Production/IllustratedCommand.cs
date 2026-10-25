using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory.Production;

public static class IllustratedCommand
{
    public static async Task<int> RunAsync(string[] args, CancellationToken ct)
    {
        string configPath = File.Exists("production.json") ? Path.GetFullPath("production.json") : Path.Combine(AppContext.BaseDirectory, "production.json");
        string? chapter = null;
        bool all = false, inspect = false, epub = false;
        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--config" when i + 1 < args.Length: configPath = Path.GetFullPath(args[++i]); break;
                case "--chapter" when i + 1 < args.Length: chapter = args[++i]; break;
                case "--all": all = true; break;
                case "--inspect": inspect = true; break;
                case "--epub": epub = true; break;
                default: throw new ArgumentException("Usage: dotnet run -- pdf --chapter Bhaskaracharya [--inspect] [--epub] [--config production.json], or --all");
            }
        }
        if (all == (chapter is not null)) throw new ArgumentException("Select either --chapter <subject-or-md-path> or --all.");
        var directory = Path.GetDirectoryName(configPath)!;
        var config = Data.Read<ProductionConfig>(await File.ReadAllTextAsync(configPath, ct));
        if (epub) config = config with { CreateEpub = true };
        config.Validate();
        var inputRoot = Path.GetFullPath(config.ManuscriptsDirectory, directory);
        var paths = Directory.GetFiles(inputRoot, "*.md").Order().ToList();
        if (chapter is not null)
        {
            if (File.Exists(chapter)) paths = [Path.GetFullPath(chapter)];
            else paths = paths.Where(p => ManuscriptReader.Load(p, config).Subject.Equals(chapter, StringComparison.OrdinalIgnoreCase)).ToList();
            if (paths.Count != 1) throw new InvalidDataException("Chapter must resolve to exactly one existing final Markdown manuscript.");
        }
        if (paths.Count == 0) throw new InvalidDataException("No final Markdown manuscripts found.");
        var manuscripts = paths.Select(path => ManuscriptReader.Load(path, config)).ToList();
        if (inspect)
        {
            foreach (var m in manuscripts) Console.WriteLine($"{m.Subject}: {m.Paragraphs.Count} paragraphs; {m.SuppressedHeadings.Count} secondary headings suppressed in layout; SHA-256={m.SourceSha256}; source={m.SourcePath}");
            return 0;
        }
        var key = Environment.GetEnvironmentVariable("OPENROUTER_API_KEY");
        if (string.IsNullOrWhiteSpace(key)) throw new InvalidOperationException("Set OPENROUTER_API_KEY. PDF production uses paid image and vision models; --inspect uses no API.");
        var style = await File.ReadAllTextAsync(Path.GetFullPath(config.IllustrationStyle, directory), ct);
        if (string.IsNullOrWhiteSpace(style)) throw new InvalidDataException("Illustration style is empty.");
        var output = Path.GetFullPath(config.OutputDirectory, directory);
        Directory.CreateDirectory(output);
        using var runLock = new FileStream(Path.Combine(output, ".production.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        using var logging = LoggerFactory.Create(b => b.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "[HH:mm:ss] "; })
            .AddProvider(new FileLogProvider(Path.Combine(output, "production.log"))));
        var logger = logging.CreateLogger("IllustratedProduction");
        using var api = new ProductionApi(config, key, logger);
        var pipeline = new IllustratedPipeline(config, style, api, logger);
        int failed = 0;
        foreach (var manuscript in manuscripts)
        {
            try { await pipeline.RunAsync(manuscript, output, ct); }
            catch (OperationCanceledException) { throw; }
            catch (Exception exception)
            { failed++; logger.LogError("[PDF][{Subject}][REQUIRES_ATTENTION] {Message}", manuscript.Subject, exception.Message); }
        }
        return failed == 0 ? 0 : 2;
    }
}
