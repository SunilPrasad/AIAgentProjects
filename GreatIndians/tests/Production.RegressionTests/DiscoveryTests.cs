using System.Text.Json.Nodes;
using GreatIndians.Factory;
using GreatIndians.Factory.Discovery;
using Microsoft.Extensions.Logging.Abstractions;

internal static class DiscoveryTests
{
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception("Discovery: " + message);
    }
    private static void Reject(Action action, string message)
    {
        try { action(); } catch (InvalidDataException) { return; }
        throw new Exception("Discovery did not reject " + message);
    }

    public static async Task RunAsync()
    {
        await ResearchRecoveryTests.RunAsync();
        string root = Path.Combine(AppContext.BaseDirectory, "discovery-tests", Guid.NewGuid().ToString("N")[..12]);
        Directory.CreateDirectory(root);
        var settings = new DiscoverySettings { ChapterCount = 2 };
        var book = new BookDefinition { Id = "test-science", Title = "Test Science", Profile = "scientific-biography", Discovery = settings };
        var fake = new FakeClient();
        var pipeline = new TopicDiscoveryPipeline(fake, NullLogger.Instance);
        var result = await pipeline.RunAsync(book, settings, "auto", Path.Combine(root, "run"), "", default);
        Check(fake.Nominations == 3 && fake.Ballots == 3 && fake.ResearchCalls == 1, "Not all jurors participated.");
        Check(result.Selected.Count == 2 && result.Selected[0].Candidate.Name == "Alpha Scientist"
            && result.Selected[1].YesVotes == 2, "Majority ranking failed.");
        Check(result.AllDecisions.Single(d => d.Candidate.Name == "Gamma Scientist").YesVotes == 1
            && result.Selected.All(d => d.Candidate.Name != "Gamma Scientist"), "Minority candidate selected.");
        Check(fake.Blind, "Another juror's ballot/proposal identity leaked into voting context.");
        var replay = await pipeline.RunAsync(book, settings, "auto", result.Root, "", default);
        Check(fake.Nominations == 3 && fake.Ballots == 3 && fake.ResearchCalls == 1, "Paid work was repeated despite unchanged cache.");
        Check(replay.Fingerprint == result.Fingerprint, "Fingerprint changed unexpectedly.");

        var pool = result.AllDecisions.Select(d => d.Candidate).ToList();
        var ballots = Enumerable.Range(1, 3).Select(i => new JuryBallot("juror-" + i, "test/model-" + i,
            fake.MakeBallot(pool, i))).ToArray();
        Reject(() => DiscoveryPolicy.Tally(pool, ballots.Take(2).ToArray()), "a missing juror");
        Reject(() => DiscoveryPolicy.Tally(pool, [ballots[0], ballots[0], ballots[2]]), "a duplicate juror");
        Reject(() => DiscoveryPolicy.Tally(pool, ballots.Select(b => b with { Model = "test/same" }).ToArray()), "one model as three jurors");
        var valid = ballots[0].Ballot;
        Reject(() => DiscoveryPolicy.ValidateBallot(valid with { Votes = [valid.Votes[0], valid.Votes[0], valid.Votes[2]] }, pool), "duplicate candidate votes");
        Reject(() => DiscoveryPolicy.ValidateBallot(valid with { Votes = valid.Votes.Select(v => v with { EvidenceExcerptIds = ["invented"] }).ToList() }, pool), "invented evidence");
        Reject(() => DiscoveryPolicy.ValidateBallot(valid with { Votes = valid.Votes.Select(v => v with { Rank = 1 }).ToList() }, pool), "duplicate ranks");
        var nomination = new TopicNomination("scientific-biography", "Test scope", [new("Alpha Scientist", [], "Alpha", "Evidence", ["fake-id"])]);
        Reject(() => DiscoveryPolicy.ValidateNomination(nomination, [], 5), "unsupported nominations");

        string path = Path.Combine(root, "book.json");
        var originalNode = JsonNode.Parse(Data.Write(book))!.AsObject();
        originalNode["coverImage"] = "cover.png";
        originalNode["backCoverText"] = "Keep this exact blurb.";
        string original = originalNode.ToJsonString();
        await File.WriteAllTextAsync(path, original);
        Check(await DiscoveryConfigStore.ApplyAsync(path, original, book, settings, result, default), "JSON not updated.");
        var updatedText = await File.ReadAllTextAsync(path);
        var updated = BookDefinition.Load(path);
        var updatedNode = JsonNode.Parse(updatedText)!;
        Check(updatedNode["coverImage"]!.GetValue<string>() == "cover.png"
            && updatedNode["backCoverText"]!.GetValue<string>() == "Keep this exact blurb.", "Unknown settings lost.");
        Check(updated.RequireDiscoveryApproval && updated.SelectionId.StartsWith("jury-"), "Selection certificate/output isolation missing.");
        Check(updated.ForWriting(path).OutputDirectory.Contains(updated.SelectionId)
            && updated.ForProduction(path).OutputDirectory.Contains(updated.SelectionId), "Output stages use different selection roots.");
        Check(File.ReadAllText(Path.Combine(result.Root, "config-backups", Data.Hash(original) + ".json")) == original, "Original backup differs.");
        Reject(() => (updated with { Title = "Different title" }).Validate(), "certificate title edits");
        Reject(() => (updated with { Subjects = updated.Subjects.Reverse().ToArray() }).Validate(), "certificate order edits");
        Reject(() => (updated with { Profile = "temple" }).Validate(), "certificate profile edits");
        var repeated = await pipeline.RunAsync(updated, settings, updated.DiscoveryApproval!.RequestedProfile, result.Root, "", default);
        Check(!await DiscoveryConfigStore.ApplyAsync(path, updatedText, updated, settings, repeated, default), "Unchanged JSON was rewritten.");
        Check(fake.Nominations == 3 && fake.ResearchCalls == 1, "Applying JSON invalidated the cache.");
        await File.WriteAllTextAsync(path, updatedText + "\n");
        bool conflict = false;
        try { await DiscoveryConfigStore.ApplyAsync(path, updatedText, updated, settings, repeated, default); }
        catch (IOException) { conflict = true; }
        Check(conflict && await File.ReadAllTextAsync(path) == updatedText + "\n", "Concurrent changes overwritten.");

        string newPath = Path.Combine(root, "new.json");
        await DiscoveryConfigStore.ApplyAsync(newPath, null, book, settings, result, default);
        var newNode = JsonNode.Parse(await File.ReadAllTextAsync(newPath))!;
        Check(newNode["id"] is not null && newNode["subjects"]![0]!["id"] is not null, "New JSON incompatible with Python tools.");
        Check(BookDefinition.Load(newPath).Production.ImageMode == "webOnly", "New science collection permitted generated illustrations by default.");

        var oldSubject = new SubjectDefinition { Id = "alpha-stable", Name = "Alpha Scientist", Aliases = ["Alpha S"], ImageQuery = "curated query", CommonsFiles = ["File:Curated.jpg"] };
        var preserveBook = book with { Subjects = [oldSubject] };
        var preserved = await pipeline.RunAsync(preserveBook, settings, "auto", Path.Combine(root, "preserve"), "", default);
        string preservePath = Path.Combine(root, "preserve.json");
        string preserveText = Data.Write(preserveBook);
        await File.WriteAllTextAsync(preservePath, preserveText);
        await DiscoveryConfigStore.ApplyAsync(preservePath, preserveText, preserveBook, settings, preserved, default);
        var preservedSubject = BookDefinition.Load(preservePath).Subjects.Single(s => s.Name == "Alpha Scientist");
        Check(preservedSubject.Id == "alpha-stable" && preservedSubject.CommonsFiles.Single() == "File:Curated.jpg"
            && preservedSubject.ImageQuery == "curated query" && preservedSubject.Aliases.Contains("Alpha S"), "Curated subject settings lost.");

        var shortSettings = settings with { ChapterCount = 3 };
        bool insufficient = false;
        try { await pipeline.RunAsync(book, shortSettings, "auto", Path.Combine(root, "short"), "", default); }
        catch (DiscoveryConsensusException) { insufficient = true; }
        Check(insufficient && await File.ReadAllTextAsync(path) == updatedText + "\n"
            && File.Exists(Path.Combine(root, "short", "selection-report.md")), "Insufficient majority changed config or lost report.");
        var unavailable = new FakeClient { FailJuror = true };
        var outagePipeline = new TopicDiscoveryPipeline(unavailable, NullLogger.Instance);
        string outageRoot = Path.Combine(root, "outage");
        bool failed = false;
        try { await outagePipeline.RunAsync(book, settings, "auto", outageRoot, "", default); }
        catch (HttpRequestException) { failed = true; }
        Check(failed && unavailable.Ballots == 0 && await File.ReadAllTextAsync(path) == updatedText + "\n", "Juror failure bypassed quorum.");
        unavailable.FailJuror = false;
        await outagePipeline.RunAsync(book, settings, "auto", outageRoot, "", default);
        Check(unavailable.Nominations == 4 && unavailable.ResearchCalls == 1, "Completed jurors were purchased again on resume.");
        Check(TopicDiscoveryPipeline.Fingerprint(book, settings, "auto", "fresh") != result.Fingerprint, "Fresh flag cannot invalidate paid caches.");
        var duplicateNominations = new[]
        {
            new JuryNomination("juror-1", "a/model", new("biography", "scope", [new("Alpha Scientist", ["A. Scientist"], "query", "reason", ["S1-E001"])])),
            new JuryNomination("juror-2", "b/model", new("biography", "scope", [new("A. Scientist", [], "query", "reason", ["S2-E001"])]))
        };
        Check(DiscoveryPolicy.Merge(duplicateNominations, []).Count == 1, "Aliases generated duplicate chapters.");
        var corrupt = new FakeClient { CorruptSource = true };
        bool sourceRejected = false;
        try { await new TopicDiscoveryPipeline(corrupt, NullLogger.Instance).RunAsync(book, settings, "auto", Path.Combine(root, "corrupt"), "", default); }
        catch (InvalidDataException) { sourceRejected = true; }
        Check(sourceRejected && corrupt.Nominations == 0, "Source hash mismatch reached paid jurors.");
        var retry = new FakeClient { InvalidFirstNomination = true };
        await new TopicDiscoveryPipeline(retry, NullLogger.Instance).RunAsync(book, settings, "auto", Path.Combine(root, "retry"), "", default);
        Check(retry.Nominations == 4 && retry.Ballots == 3, "Invalid evidence nomination did not receive one bounded corrective retry.");
        var scopedSettings = settings with { Prompt = "Modern scientists only, active from 1800 onwards. Exclude ancient and medieval figures such as Aryabhata." };
        var scopedClient = new FakeClient { ExpectedPrompt = scopedSettings.Prompt };
        var scopedResult = await new TopicDiscoveryPipeline(scopedClient, NullLogger.Instance)
            .RunAsync(book, scopedSettings, "auto", Path.Combine(root, "scoped"), "", default);
        Check(scopedClient.ScopeReachedResearch && scopedClient.ScopeReachedAllJurors == 6,
            "Scope prompt did not reach research and all three nominations/ballots.");
        Check(scopedResult.Fingerprint != result.Fingerprint, "Changed scope reused unscoped vote caches.");
        string scopedPath = Path.Combine(root, "scoped.json");
        await DiscoveryConfigStore.ApplyAsync(scopedPath, null, book, scopedSettings, scopedResult, default);
        var scopedBook = BookDefinition.Load(scopedPath);
        Check(scopedBook.Discovery.Prompt == scopedSettings.Prompt && scopedBook.Title == book.Title,
            "Scope was not persisted separately from title.");
        Reject(() => (scopedBook with { Discovery = scopedSettings with { Prompt = "Ancient scientists only" } }).Validate(),
            "old majority approval reused after scope change");
        Console.WriteLine("PASS discovery: three blind jurors, majority-only ranking, evidence/ballot validation, outage resume, cache reuse, safe JSON backup/update, certificate and output isolation");
    }

    private sealed class FakeClient : ITopicDiscoveryClient
    {
        public int ResearchCalls, Nominations, Ballots;
        public bool FailJuror, CorruptSource, InvalidFirstNomination, Blind = true;
        public string ExpectedPrompt = "";
        public bool ScopeReachedResearch;
        public int ScopeReachedAllJurors;
        public Task<List<Source>> ResearchAsync(BookConfig config, string prompt, Artifacts files, CancellationToken ct)
        {
            Interlocked.Increment(ref ResearchCalls);
            ScopeReachedResearch = prompt == ExpectedPrompt;
            string text = string.Join(" ", Enumerable.Repeat("Alpha Scientist, Beta Scientist and Gamma Scientist contributed documented scientific work to this field.", 8));
            return Task.FromResult(new List<Source>
            {
                new("S1", "https://museum.example/research", "Museum overview", text, CorruptSource ? "changed-hash" : Data.Hash(text), DateTimeOffset.UtcNow),
                new("S2", "https://university.example/science", "University overview", text, Data.Hash(text), DateTimeOffset.UtcNow)
            });
        }
        public Task<TopicNomination> NominateAsync(string model, string instructions, string input, string stage, Artifacts files, CancellationToken ct)
        {
            Interlocked.Increment(ref Nominations);
            if (ExpectedPrompt.Length > 0 && instructions.Contains(ExpectedPrompt)) Interlocked.Increment(ref ScopeReachedAllJurors);
            if (FailJuror && stage.Contains("juror-3")) throw new HttpRequestException("Fake provider outage");
            if (InvalidFirstNomination && stage == "nominate-juror-1-1")
                return Task.FromResult(new TopicNomination("scientific-biography", "Test field", [new("Alpha Scientist", [], "query", "Reason", ["invented-id"])]));
            var candidates = new[] { "Alpha Scientist", "Beta Scientist", "Gamma Scientist" }.Select(name =>
                new NominatedTopic(name, [], name, "Documented relevant contribution", ["S1-E001", "S2-E001"])).ToList();
            return Task.FromResult(new TopicNomination("scientific-biography", "Test field", candidates));
        }
        public Task<TopicBallot> VoteAsync(string model, string instructions, string input, string stage, Artifacts files, CancellationToken ct)
        {
            Interlocked.Increment(ref Ballots);
            if (ExpectedPrompt.Length > 0 && instructions.Contains(ExpectedPrompt)) Interlocked.Increment(ref ScopeReachedAllJurors);
            var node = JsonNode.Parse(input)!["context"]!;
            var pool = node["candidates"]!.AsArray().Select(n => new DiscoveryCandidate(n!["Id"]!.GetValue<string>(),
                n["Name"]!.GetValue<string>(), [], "query", "reason", ["S1-E001", "S2-E001"], [])).ToList();
            if (node["ballots"] is not null || node["nominations"] is not null || input.Contains("ProposedBy")) Blind = false;
            int juror = stage.Contains("juror-1") ? 1 : stage.Contains("juror-2") ? 2 : 3;
            return Task.FromResult(MakeBallot(pool, juror));
        }
        public TopicBallot MakeBallot(IReadOnlyList<DiscoveryCandidate> pool, int juror)
        {
            int rank = 0;
            return new TopicBallot(pool.OrderBy(c => c.Name).Select(c =>
            {
                bool yes = c.Name.StartsWith("Alpha") || c.Name.StartsWith("Beta") && juror <= 2 || c.Name.StartsWith("Gamma") && juror == 3;
                return new TopicVote(c.Id, yes, yes ? ++rank : 0, "Independent evidence assessment", yes ? ["S1-E001"] : []);
            }).ToList(), "Independent test ballot");
        }
    }
}
