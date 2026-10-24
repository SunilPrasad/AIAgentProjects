using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory;

public sealed class Artifacts(string root, ILogger logger, string[]? previousResearchRoots = null)
{
    public string Root { get; } = root;

    private sealed record Entry(string InputHash, string OutputHash, string Content);

    public Task Save(string name, string content)
        => Data.SaveAsync(Path.Combine(Root, name), content);

    public async Task<string> Cached(string name, string inputs, Func<Task<string>> produce)
    {
        var path = Path.Combine(Root, name);
        var hash = Data.Hash(inputs);
        var entry = await ReadEntry(path, hash);

        if (entry is not null)
        {
            logger.LogInformation(
                "[{Chapter}][Storage][RESUME] Reusing {Stage}", Path.GetFileName(Root), name);

            return entry.Content;
        }

        // A successful model result may survive application fixes only when its exact inputs and output hash match.
        // Revalidate all reused results; approvals and checkpoints are never transferred between run versions.
        var reusableResearch = name.StartsWith("cache/", StringComparison.Ordinal);

        if (reusableResearch)
        {
            foreach (var previousRoot in previousResearchRoots ?? [])
            {
                var previousPath = Path.Combine(previousRoot, name);
                entry = await ReadEntry(previousPath, hash);

                if (entry is null)
                {
                    continue;
                }

                await Data.SaveAsync(path, Data.Write(entry));
                await Save(
                    $"provenance/reused-{Path.GetFileName(name)}",
                    Data.Write(new { previousPath, entry.InputHash, entry.OutputHash }));

                logger.LogInformation(
                    "[{Chapter}][Storage][RESUME] Reusing identical stage inputs for {Stage} from previous run",
                    Path.GetFileName(Root), name);

                return entry.Content;
            }
        }

        var content = await produce();
        await Data.SaveAsync(path, Data.Write(new Entry(hash, Data.Hash(content), content)));

        return content;
    }

    private static async Task<Entry?> ReadEntry(string path, string expectedHash)
    {
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            var entry = Data.Read<Entry>(await File.ReadAllTextAsync(path));

            return entry.InputHash == expectedHash && Data.Hash(entry.Content) == entry.OutputHash
                ? entry
                : null;
        }
        catch (System.Text.Json.JsonException)
        {
            return null;
        }
    }
}

public sealed class FileLogProvider(string path) : ILoggerProvider
{
    private readonly object gate = new();
    private readonly string logPath = path;

    public ILogger CreateLogger(string categoryName) => new FileLogger(this);

    public void Dispose()
    {
    }

    private sealed class FileLogger(FileLogProvider owner) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel level) => level >= LogLevel.Information;

        public void Log<TState>(
            LogLevel level,
            EventId id,
            TState state,
            Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(level))
            {
                return;
            }

            lock (owner.gate)
            {
                File.AppendAllText(
                    owner.logPath,
                    $"{DateTimeOffset.UtcNow:O} {level} {formatter(state, exception)}{Environment.NewLine}");
            }
        }
    }
}
