using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace GreatIndians.Factory;

public sealed record CostEntry(string Scope, string Stage, string Model, decimal CostUsd);
public sealed record CostLine(string Category, int Calls, decimal CostUsd);

public sealed record CostSummary(decimal TotalUsd, int PaidCalls, int UnpricedCalls, List<CostLine> Breakdown)
{
    public string Money() => Format(TotalUsd);

    public static string Format(decimal value) => "$" + value.ToString("0.000", CultureInfo.InvariantCulture);

    // One line for console/log output: "$0.912 (14 paid calls) — image generation 5 × $0.685; ...".
    public string OneLine() => $"{Money()} ({PaidCalls} paid call{(PaidCalls == 1 ? "" : "s")}" +
        (UnpricedCalls > 0 ? $"; {UnpricedCalls} without reported cost" : "") + ")" +
        (Breakdown.Count == 0 ? " — all results reused from cache" :
            " — " + string.Join("; ", Breakdown.Select(line => $"{line.Category} {line.Calls} × {Format(line.CostUsd)}")));

    public string Markdown() => $"Total OpenRouter cost for this invocation: **{Money()}** across {PaidCalls} paid calls." +
        (UnpricedCalls > 0 ? $" {UnpricedCalls} calls did not report a cost." : "") +
        (Breakdown.Count == 0 ? " All model results were reused from cache.\n" :
            "\n\n| Stage | Calls | Cost |\n|---|---:|---:|\n" +
            string.Join("\n", Breakdown.Select(line => $"| {line.Category} | {line.Calls} | {Format(line.CostUsd)} |")) + "\n");
}

// Process-wide record of the costs OpenRouter reports. Results reused from cache are never billed and never recorded.
public static class CostMeter
{
    private static readonly object Gate = new();
    private static readonly List<CostEntry> Entries = [];
    private static readonly List<CostEntry> Unpriced = [];

    public sealed record Position(int Priced, int Unpriced);

    public static Position Mark()
    {
        lock (Gate) return new Position(Entries.Count, Unpriced.Count);
    }

    public static void Record(string scope, string stage, string model, JsonElement usage)
    {
        lock (Gate)
        {
            if (usage.ValueKind == JsonValueKind.Object && usage.TryGetProperty("cost", out var value)
                && value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var cost))
                Entries.Add(new CostEntry(scope, stage, model, cost));
            else
                Unpriced.Add(new CostEntry(scope, stage, model, 0));
        }
    }

    public static void Record(string scope, string stage, string model, decimal cost)
    {
        lock (Gate) Entries.Add(new CostEntry(scope, stage, model, cost));
    }

    public static CostSummary Since(Position mark)
    {
        List<CostEntry> priced;
        int unpriced;
        lock (Gate)
        {
            priced = Entries.Skip(mark.Priced).ToList();
            unpriced = Unpriced.Count - mark.Unpriced;
        }

        var breakdown = priced.GroupBy(entry => Category(entry.Stage))
            .Select(group => new CostLine(group.Key, group.Count(), group.Sum(entry => entry.CostUsd)))
            .OrderByDescending(line => line.CostUsd).ToList();
        return new CostSummary(priced.Sum(entry => entry.CostUsd), priced.Count, unpriced, breakdown);
    }

    public static string Category(string stage)
    {
        if (stage.StartsWith("discovery-", StringComparison.Ordinal))
        {
            return "discovery " + Regex.Replace(stage["discovery-".Length..], "-.*$", "");
        }
        if (Regex.IsMatch(stage, @"^plan-\d+$")) return "illustration plan";
        if (Regex.IsMatch(stage, @"^layout-\d+-page-\d+$")) return "page review";
        if (Regex.IsMatch(stage, @"-web-[0-9a-f]+-review$")) return "web photo review";
        if (Regex.IsMatch(stage, @"-attempt-\d+-review$")) return "image review";
        if (Regex.IsMatch(stage, @"-attempt-\d+$")) return "image generation";
        return stage; // Text pipeline stages are already agent names such as HistoricalReviewer.
    }
}
