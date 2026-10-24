using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Agents.AI;
using OpenAI;

// Microsoft Agent Framework-based chapter drafting and revision; external independent reviewer.
// Fail-closed: no approved evidence, no manuscript; no reviewer approval, no illustration briefs.
var opts = new JsonSerializerOptions { PropertyNameCaseInsensitive = true, WriteIndented = true };
if (args.Length < 2 || args[0] != "chapter")
{
    Console.WriteLine("Usage: dotnet run -- chapter <approved-evidence.json> [output-folder]");
    return;
}
var input = JsonSerializer.Deserialize<ChapterInput>(await File.ReadAllTextAsync(args[1]), opts)
    ?? throw new InvalidOperationException("Invalid input");
if (input.Claims.Count == 0 || input.Claims.Any(c => c.Status != "supported" || string.IsNullOrWhiteSpace(c.Source) || string.IsNullOrWhiteSpace(c.Quote)))
    throw new InvalidOperationException("All supplied claims must be supported with source and evidence excerpt. Research approval is required before drafting.");
if (!input.ResearchApprovedByHuman)
    throw new InvalidOperationException("Research package requires human approval before drafting.");
var apiKey = Environment.GetEnvironmentVariable("OPENAI_API_KEY") ?? throw new InvalidOperationException("OPENAI_API_KEY missing");
var reviewerKey = Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY") ?? throw new InvalidOperationException("ANTHROPIC_API_KEY missing: independent review is mandatory");
var model = Environment.GetEnvironmentVariable("WRITER_MODEL") ?? "gpt-4.1";
var reviewerModel = Environment.GetEnvironmentVariable("REVIEWER_MODEL") ?? "claude-sonnet-4-5";
var output = args.Length > 2 ? args[2] : Path.Combine("runs", DateTime.UtcNow.ToString("yyyyMMdd-HHmmss"));
Directory.CreateDirectory(output);
var client = new OpenAIClient(apiKey);
AIAgent writer = client.GetChatClient(model).AsAIAgent(name: "ChildrenBiographyWriter", instructions: Prompts.Writer);
AIAgent reviser = client.GetChatClient(model).AsAIAgent(name: "EvidenceBasedReviser", instructions: Prompts.Reviser);
AIAgent artDirector = client.GetChatClient(model).AsAIAgent(name: "IllustrationArtDirector", instructions: Prompts.ArtDirector);
var facts = JsonSerializer.Serialize(input, opts);
var draft = (await writer.RunAsync($"Produce a chapter based ONLY on this human-approved evidence:\n{facts}")).Text;
await File.WriteAllTextAsync(Path.Combine(output, "draft-0.md"), draft);
using var http = new HttpClient { Timeout = TimeSpan.FromMinutes(3) };
ReviewResult? last = null;
for (int pass = 1; pass <= 3; pass++)
{
    string reviewerInstructions = Prompts.Reviewer + "\nEVIDENCE LEDGER:\n" + facts + "\nCHAPTER:\n" + draft;
    string json = await ReviewWithClaudeAsync(http, reviewerKey, reviewerModel, reviewerInstructions);
    await File.WriteAllTextAsync(Path.Combine(output, $"review-{pass}.raw.json"), json);
    last = JsonSerializer.Deserialize<ReviewResult>(ExtractJson(json), opts)
        ?? throw new InvalidOperationException("Reviewer output was not valid JSON; publication blocked.");
    if (last.Approved && last.Findings.Count == 0) break;
    if (pass == 3) break;
    draft = (await reviser.RunAsync($"EVIDENCE:\n{facts}\nCURRENT CHAPTER:\n{draft}\nINDEPENDENT REVIEW:\n{JsonSerializer.Serialize(last,opts)}\nRevise only where justified by evidence.")).Text;
    await File.WriteAllTextAsync(Path.Combine(output, $"draft-{pass}.md"), draft);
}
if (last is null || !last.Approved || last.Findings.Count != 0)
{
    await File.WriteAllTextAsync(Path.Combine(output, "STATUS.txt"), "BLOCKED: unresolved review findings. No illustration stage executed.\n");
    Console.WriteLine($"Review blocked publication. Inspect: {output}");
    return;
}
await File.WriteAllTextAsync(Path.Combine(output, "chapter-approved-by-ai-PENDING-HUMAN.md"), draft);
var brief = (await artDirector.RunAsync($"Write 3-5 illustration briefs for this approved chapter. Use one style bible; no text inside images. Include historical accuracy warnings.\nSTYLE: {input.IllustrationStyle}\nEVIDENCE:\n{facts}\nCHAPTER:\n{draft}")).Text;
await File.WriteAllTextAsync(Path.Combine(output, "illustration-briefs-PENDING-HUMAN.md"), brief);
await File.WriteAllTextAsync(Path.Combine(output, "STATUS.txt"), "AI REVIEW PASSED. Await human chapter approval, illustration verification and print proof. NO IMAGES GENERATED.\n");
Console.WriteLine($"AI-reviewed draft and illustration briefs saved to {output}");

static string ExtractJson(string s)
{
    var first = s.IndexOf('{'); var last = s.LastIndexOf('}');
    if (first < 0 || last <= first) throw new FormatException("Expected reviewer JSON object");
    return s.Substring(first, last - first + 1);
}
static async Task<string> ReviewWithClaudeAsync(HttpClient client, string apiKey, string model, string prompt)
{
    using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.anthropic.com/v1/messages");
    req.Headers.Add("x-api-key", apiKey);
    req.Headers.Add("anthropic-version", "2023-06-01");
    req.Content = new StringContent(JsonSerializer.Serialize(new {
        model, max_tokens = 2200,
        messages = new[] { new { role = "user", content = prompt } }
    }), Encoding.UTF8, "application/json");
    using var res = await client.SendAsync(req);
    var data = await res.Content.ReadAsStringAsync();
    res.EnsureSuccessStatusCode();
    using var parsed = JsonDocument.Parse(data);
    return string.Join("\n", parsed.RootElement.GetProperty("content").EnumerateArray()
      .Where(x => x.GetProperty("type").GetString() == "text")
      .Select(x => x.GetProperty("text").GetString()));
}
public sealed record Claim(string Id, string Text, string Status, string Source, string Quote);
public sealed record ChapterInput(string Subject, string AgeGroup, string IllustrationStyle, bool ResearchApprovedByHuman, List<Claim> Claims);
public sealed record Finding(string ClaimId, string Severity, string Issue, string RecommendedFix);
public sealed record ReviewResult(bool Approved, List<Finding> Findings, string? Summary);
public static class Prompts
{
    public const string Writer = "You write inspiring narrative nonfiction for ages 8-12. Aim for 600-900 words of flowing story, not a short picture book, fact sheet, or bullet list. Build narrative momentum, curiosity, challenge and meaningful achievement. Facts must derive ONLY from the supplied evidence ledger. You may include explicitly signalled imagined scenes (e.g. 'Imagine...'), never invented quotations or unsupported personal incidents presented as fact. Don't falsely attribute zero to Aryabhata. Write beautiful, clear British English. End with a brief 'History Detective' note distinguishing fact from imagination. No citations invented.";
    public const string Reviser = "You revise vivid children's historical nonfiction with strict evidentiary discipline. Respond with only the complete revised chapter. Resolve each supported critical error; retain narrative energy and age suitability. Never add unsupported facts, imaginary verbatim quotes, or unchecked firsts.";
    public const string Reviewer = "You are an independent historical and child-suitability critic. Audit every checkable claim against ONLY the supplied evidence. Mark unsupported assertions, misattributed achievements, problematic stereotypes, misleading certainty, and age-inappropriate writing. Imagination signalled as imagination is allowed if plausible. Do not rubber-stamp. Return ONLY JSON matching {\"approved\":boolean,\"findings\":[{\"claimId\":string,\"severity\":string,\"issue\":string,\"recommendedFix\":string}],\"summary\":string}. Approve only if no findings remain; missing evidence => reject.";
    public const string ArtDirector = "You create illustration BRIEFS ONLY, not images. Follow the same children's illustrated narrative-book style across scenes: painterly digital gouache/watercolour, warm luminous palette, expressive but age-appropriate, consistent proportions, no embedded writing. Describe each visual, character references and period-specific authenticity warnings. Do not invent evidence.";
}
