using System.Text.Json;
using GreatIndians.Factory;

internal static class CostMeterTests
{
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception("CostMeter: " + message);
    }

    public static async Task RunAsync()
    {
        var before = CostMeter.Mark();
        CostMeter.Record("earlier", "HistoricalReviewer", "m", 5m);
        var mark = CostMeter.Mark();
        using var priced = JsonDocument.Parse("""{"prompt_tokens":10,"cost":0.0125}""");
        using var unpriced = JsonDocument.Parse("""{"prompt_tokens":10}""");
        var stages = new[] { "I02-attempt-1", "I02-attempt-1-review", "layout-1-page-003", "plan-2", "discovery-ballot-juror2-1" };
        await Task.WhenAll(Enumerable.Range(0, 40).Select(i => Task.Run(() =>
            CostMeter.Record("PDF", stages[i % stages.Length], "m", priced.RootElement.Clone()))));
        CostMeter.Record("PDF", "plan-1", "m", unpriced.RootElement.Clone());

        var summary = CostMeter.Since(mark);
        Check(summary.TotalUsd == 0.5m, $"parallel total was {summary.TotalUsd}, expected 0.5.");
        Check(summary.PaidCalls == 40 && summary.UnpricedCalls == 1, "paid/unpriced call counts are wrong.");
        Check(summary.Breakdown.Select(line => line.Category).Order().SequenceEqual(
            new[] { "discovery ballot", "illustration plan", "image generation", "image review", "page review" }),
            "categories are wrong: " + string.Join(", ", summary.Breakdown.Select(line => line.Category)));
        Check(summary.Breakdown.All(line => line.Calls == 8 && line.CostUsd == 0.1m), "per-category totals are wrong.");
        Check(CostMeter.Since(before).TotalUsd == 5.5m, "an earlier mark did not include later costs.");
        Check(CostMeter.Category("I01-web-0123456789ab-review") == "web photo review", "web review category is wrong.");
        Check(CostMeter.Category("RevisionAgent") == "RevisionAgent", "text agent category is wrong.");
        Check(CostMeter.Since(CostMeter.Mark()).OneLine().Contains("reused from cache"), "a free re-run is not explained.");
        Console.WriteLine("PASS cost meter: parallel totals, categories and cached re-runs");
        CheckCostSavingPolicy();
    }

    private static void CheckCostSavingPolicy()
    {
        var config = new GreatIndians.Factory.Production.ProductionConfig();
        config.Validate();
        string Model(GreatIndians.Factory.Production.ProductionConfig c, int attempt, bool opening)
            => GreatIndians.Factory.Production.IllustratedPipeline.ImageModelFor(c, attempt, opening);
        Check(Model(config, 1, false) == config.DraftImageModel, "later scenes do not start on the draft model.");
        Check(Model(config, 2, false) == config.ImageModel && Model(config, 3, false) == config.ImageModel, "retries do not escalate.");
        Check(Model(config, 1, true) == config.ImageModel, "the opening character reference used the draft model.");
        Check(Model(config with { DraftModelForOpening = true }, 1, true) == config.DraftImageModel, "draftModelForOpening was ignored.");
        Check(Model(config with { MaxImageAttempts = 1 }, 1, false) == config.ImageModel, "the only attempt did not use imageModel.");
        Check(Model(config with { DraftImageAttempts = 5 }, 3, false) == config.ImageModel, "the final attempt did not use imageModel.");
        Check(Model(config with { DraftImageModel = "" }, 1, false) == config.ImageModel, "an empty draft model was not disabled.");

        var layout = new GreatIndians.Factory.Production.LayoutManifest(432, 648, 54.96, 6,
            [new("I01", 1, 0, 0, 10, 10, 300), new("I02", 3, 0, 0, 10, 10, 300), new("I03", 3, 0, 0, 10, 10, 300)], [], "");
        Check(GreatIndians.Factory.Production.IllustratedPipeline.PagesForVisualReview(layout, "illustrated").SequenceEqual([1, 3, 6]),
            "illustrated scope must review the opening, every illustrated page and the final page.");
        Check(GreatIndians.Factory.Production.IllustratedPipeline.PagesForVisualReview(layout, "all").Count == 6, "scope all skipped pages.");
        foreach (var bad in new[] { config with { PageReviewScope = "some" }, config with { ReviewImageMaxEdge = 100 },
            config with { DraftImageModel = "no-provider" }, config with { MaxBookCostUsd = -1 } })
        {
            try { bad.Validate(); throw new Exception("CostMeter: invalid cost-saving configuration was accepted."); }
            catch (InvalidDataException) { }
        }
        Console.WriteLine("PASS cost policy: draft-then-escalate image models, page review scope and configuration limits");
    }
}
