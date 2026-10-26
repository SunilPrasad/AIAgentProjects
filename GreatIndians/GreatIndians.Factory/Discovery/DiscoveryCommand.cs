using System.Text.Json.Nodes;
using Microsoft.Extensions.Logging;

namespace GreatIndians.Factory.Discovery;

public static class DiscoveryConfigStore
{
    private static JsonNode Node<T>(T value) => System.Text.Json.JsonSerializer.SerializeToNode(value,
        new System.Text.Json.JsonSerializerOptions { PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase })!;
    private static string Key(JsonObject obj, string name) => obj.Select(p => p.Key)
        .FirstOrDefault(k => k.Equals(name, StringComparison.OrdinalIgnoreCase)) ?? name;
    private static void Set(JsonObject obj, string name, JsonNode? value) => obj[Key(obj, name)] = value;

    public static BookDefinition Read(string? original, string? title)
    {
        var book = original is null ? new BookDefinition { Id = Data.Slug(title ?? ""), Title = title ?? "" }
            : Data.Read<BookDefinition>(original);
        if (title is not null) book = book with { Title = title };
        if (book.Subjects is null || book.Discovery is null)
            throw new InvalidDataException("Subjects and discovery settings cannot be null.");
        // Discovery can repair an out-of-date selection certificate or start from a title alone.
        (book with { RequireDiscoveryApproval = false, Subjects = book.Subjects.Length > 0 ? book.Subjects
            : [new SubjectDefinition { Id = "validation-placeholder", Name = "Validation placeholder" }] }).Validate();
        return book;
    }

    public static async Task<bool> ApplyAsync(string path, string? original, BookDefinition book,
        DiscoverySettings settings, TopicDiscoveryResult result, CancellationToken ct)
    {
        if (result.Selected.Count != settings.ChapterCount || result.Selected.Any(d => d.YesVotes < 2)
            || result.Fingerprint != TopicDiscoveryPipeline.Fingerprint(book, settings, result.RequestedProfile, result.RunNonce))
            throw new InvalidDataException("Cannot apply an incomplete, minority-only or mismatched discovery result.");
        var subjects = result.Selected.Select(d =>
        {
            var old = book.Subjects.FirstOrDefault(s => s.Id == d.Candidate.Id);
            return new SubjectDefinition
            {
                Id = d.Candidate.Id, Name = d.Candidate.Name, Aliases = d.Candidate.Aliases,
                ImageQuery = old is not null && old.ImageQuery.Length > 0 ? old.ImageQuery : d.Candidate.ImageQuery,
                CommonsFiles = old?.CommonsFiles ?? []
            };
        }).ToArray();
        string hash = DiscoveryPolicy.SubjectHash(book.Title, result.Profile, subjects);
        bool sameList = DiscoveryPolicy.SubjectHash(book.Title, book.Profile, book.Subjects) == hash;
        var approval = new DiscoveryApproval
        {
            InputFingerprint = result.Fingerprint, RequestedProfile = result.RequestedProfile,
            Prompt = settings.Prompt,
            SubjectListHash = hash, JurorModels = settings.JurorModels, RunNonce = result.RunNonce,
            ReportPath = Path.Combine(result.Root, "selection-report.md"),
            Topics = result.Selected.Select(d => new ApprovedTopic(d.Candidate.Id, d.Candidate.Name, d.ApprovingJurors)).ToArray()
        };
        var updated = book with
        {
            Profile = result.Profile, Subjects = subjects, Discovery = settings,
            Production = original is null && result.Profile == "scientific-biography"
                ? book.Production with { ImageMode = "webOnly", MissingWebImagePolicy = "skip" } : book.Production,
            SelectionId = sameList ? book.SelectionId : "jury-" + hash[..12],
            RequireDiscoveryApproval = true, DiscoveryApproval = approval
        };
        updated.Validate();
        JsonObject obj = original is null ? Node(updated).AsObject()
            : JsonNode.Parse(original)!.AsObject();
        Set(obj, "title", JsonValue.Create(updated.Title));
        Set(obj, "profile", JsonValue.Create(updated.Profile));
        Set(obj, "selectionId", JsonValue.Create(updated.SelectionId));
        Set(obj, "requireDiscoveryApproval", JsonValue.Create(true));
        Set(obj, "discovery", Node(settings));
        Set(obj, "discoveryApproval", Node(approval));
        // Keep unknown per-subject properties such as manually curated art settings.
        var oldNodes = original is null ? null : obj[Key(obj, "subjects")] as JsonArray;
        var nodes = new JsonArray();
        foreach (var subject in subjects)
        {
            var oldNode = oldNodes?.OfType<JsonObject>().FirstOrDefault(n =>
                n[Key(n, "id")]?.GetValue<string>() == subject.Id)?.DeepClone() as JsonObject
                ?? new JsonObject();
            var data = Node(subject).AsObject();
            foreach (var property in data) Set(oldNode, property.Key, property.Value?.DeepClone());
            nodes.Add(oldNode);
        }
        Set(obj, "subjects", nodes);
        var output = obj.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
        Data.Read<BookDefinition>(output).Validate();
        ct.ThrowIfCancellationRequested();
        if (File.Exists(path) != (original is not null)
            || (original is not null && await File.ReadAllTextAsync(path, ct) != original))
            throw new IOException("Book JSON changed during discovery. It was not overwritten. Rerun to apply the retained vote results.");
        if (original is not null && JsonNode.DeepEquals(JsonNode.Parse(original), obj)) return false;
        if (original is not null)
            await Data.SaveAsync(Path.Combine(result.Root, "config-backups", Data.Hash(original) + ".json"), original);
        await Data.SaveAsync(path, output);
        return true;
    }
}

public static class DiscoveryCommand
{
    public static async Task<int> RunAsync(string[] args, CancellationToken ct)
    {
        string? title = null, bookPath = null, profile = null, prompt = null;
        int? count = null;
        bool inspect = false, preview = false, fresh = false;
        for (int index = 0; index < args.Length; index++)
        {
            string Value() => ++index < args.Length ? args[index] : throw new ArgumentException("Missing value for " + args[index - 1]);
            switch (args[index])
            {
                case "--title": title = Value(); break;
                case "--book": bookPath = Value(); break;
                case "--profile": profile = Value(); break;
                case "--prompt": prompt = Value(); break;
                case "--count": count = int.Parse(Value(), System.Globalization.CultureInfo.InvariantCulture); break;
                case "--inspect": inspect = true; break;
                case "--preview": preview = true; break;
                case "--fresh": fresh = true; break;
                case "--help": Console.WriteLine("discover --title <title> [--book <shared-book.json>] [--prompt <scope instructions>] [--profile auto|biography|scientific-biography|temple|place|event|nonfiction] [--count 10] [--preview] [--inspect] [--fresh]"); return 0;
                default: throw new ArgumentException("Unknown discovery argument: " + args[index]);
            }
        }
        if (title is not null && string.IsNullOrWhiteSpace(title)) throw new ArgumentException("Title cannot be empty.");
        if (bookPath is null)
        {
            if (title is null) throw new ArgumentException("Supply --title or --book. Use discover --help for syntax.");
            var directory = new DirectoryInfo(Environment.CurrentDirectory);
            while (directory.Parent is not null && !Directory.Exists(Path.Combine(directory.FullName, "books"))) directory = directory.Parent;
            var books = Path.Combine(directory.FullName, "books");
            if (!Directory.Exists(books)) books = Path.Combine(Environment.CurrentDirectory, "books");
            var matches = Directory.Exists(books) ? Directory.GetFiles(books, "*.json")
                .Where(p => Data.Read<BookDefinition>(File.ReadAllText(p)).Title.Equals(title, StringComparison.OrdinalIgnoreCase)).ToArray() : [];
            if (matches.Length > 1) throw new ArgumentException("Multiple book definitions have this title; supply --book.");
            bookPath = matches.SingleOrDefault() ?? Path.Combine(books, Data.Slug(title) + ".json");
        }
        bookPath = Path.GetFullPath(bookPath);
        string? original = File.Exists(bookPath) ? await File.ReadAllTextAsync(bookPath, ct) : null;
        var book = DiscoveryConfigStore.Read(original, title);
        var settings = book.Discovery with { ChapterCount = count ?? book.Discovery.ChapterCount,
            Prompt = prompt?.Trim() ?? book.Discovery.Prompt };
        settings.Validate();
        profile ??= book.DiscoveryApproval?.RequestedProfile ?? (original is null ? "auto" : book.Profile);
        if (profile != "auto" && !ContentProfiles.All.Contains(profile)) throw new ArgumentException("Unsupported --profile.");
        string nonce = fresh ? Guid.NewGuid().ToString("N") : book.DiscoveryApproval?.RunNonce ?? "";
        string fingerprint = TopicDiscoveryPipeline.Fingerprint(book, settings, profile, nonce);
        string baseRoot = Path.Combine(Path.GetFullPath(book.OutputRoot, Path.GetDirectoryName(bookPath)!), book.Id, "discovery");
        string root = Path.Combine(baseRoot, fingerprint);
        Console.WriteLine($"Discovery: {book.Title}; chapters={settings.ChapterCount}; profile={profile}; majority=2/3");
        if (settings.Prompt.Length > 0) Console.WriteLine($"Scope prompt: {settings.Prompt}");
        Console.WriteLine($"Jurors: {string.Join(", ", settings.JurorModels)}\nBook JSON: {bookPath}\nReport directory: {root}");
        if (inspect) return 0;
        string key = Environment.GetEnvironmentVariable("OPENROUTER_API_KEY") ?? "";
        if (string.IsNullOrWhiteSpace(key)) throw new InvalidOperationException("Set OPENROUTER_API_KEY before discovery.");
        Directory.CreateDirectory(baseRoot);
        using var runLock = new FileStream(Path.Combine(baseRoot, ".discovery.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        using var logging = LoggerFactory.Create(b => b.AddSimpleConsole(o => o.SingleLine = true)
            .AddProvider(new FileLogProvider(Path.Combine(baseRoot, "discovery.log"))));
        var log = logging.CreateLogger("TopicDiscovery");
        var costMark = CostMeter.Mark();
        TopicDiscoveryResult result;
        try
        {
            result = await new TopicDiscoveryPipeline(new OpenRouterDiscoveryClient(key, log), log)
                .RunAsync(book, settings, profile, root, nonce, ct);
        }
        catch
        {
            Console.WriteLine($"Discovery cost before stopping: {CostMeter.Since(costMark).OneLine()}");
            throw;
        }
        foreach (var topic in result.Selected) Console.WriteLine($"{topic.YesVotes}/3 — {topic.Candidate.Name}");
        bool changed = !preview && await DiscoveryConfigStore.ApplyAsync(bookPath, original, book, settings, result, ct);
        string status = preview ? "PREVIEW_ONLY" : changed ? "CONFIG_UPDATED" : "CONFIG_UNCHANGED";
        var cost = CostMeter.Since(costMark);
        await Data.SaveAsync(Path.Combine(root, "status.json"), Data.Write(new { status, bookPath, result.Fingerprint, costUsd = cost.TotalUsd, cost }));
        Console.WriteLine($"{status}; report: {Path.Combine(root, "selection-report.md")}");
        Console.WriteLine($"Discovery cost: {cost.OneLine()}");
        return 0;
    }
}
