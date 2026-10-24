using Microsoft.Extensions.Logging;
namespace GreatIndians.Factory;

public sealed class Artifacts(string root, ILogger logger)
{
    public string Root { get; } = root;
    private sealed record Entry(string InputHash, string OutputHash, string Content);
    public Task Save(string name, string content) => Data.SaveAsync(Path.Combine(Root, name), content);
    public async Task<string> Cached(string name, string inputs, Func<Task<string>> produce)
    {
        var path = Path.Combine(Root, name);
        var hash = Data.Hash(inputs);
        if (File.Exists(path))
        {
            try
            {
                var entry = Data.Read<Entry>(await File.ReadAllTextAsync(path));
                if (entry.InputHash == hash && Data.Hash(entry.Content) == entry.OutputHash)
                {
                    logger.LogInformation("[{Chapter}][Storage][RESUME] Reusing {Stage}", Path.GetFileName(Root), name);
                    return entry.Content;
                }
            }
            catch (System.Text.Json.JsonException) { }
        }
        var content = await produce();
        await Data.SaveAsync(path, Data.Write(new Entry(hash, Data.Hash(content), content)));
        return content;
    }
}
public sealed class FileLogProvider(string path) : ILoggerProvider
{
    private readonly object gate = new();
    private readonly string logPath = path;
    public ILogger CreateLogger(string categoryName) => new FileLogger(this);
    public void Dispose() { }
    private sealed class FileLogger(FileLogProvider owner) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
        public bool IsEnabled(LogLevel level) => level >= LogLevel.Information;
        public void Log<TState>(LogLevel level, EventId id, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(level)) return;
            lock (owner.gate) File.AppendAllText(owner.logPath, $"{DateTimeOffset.UtcNow:O} {level} {formatter(state, exception)}{Environment.NewLine}");
        }
    }
}
