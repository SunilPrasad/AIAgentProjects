using System.ComponentModel;
using CalculateTotalRevenue.Models;
using Microsoft.Extensions.Logging;

namespace CalculateTotalRevenue.Tools;

/// <summary>
/// Performs the actual summation of profit values. This is the only place addition of profit
/// values may happen — the agent must never add numbers itself.
/// </summary>
public sealed class ProfitCalculationTool(ILogger<ProfitCalculationTool> logger)
{
    [Description(
        "Sums a list of profit amounts that are ALL already expressed in the same target currency, applying " +
        "financial (banker's) rounding to 2 decimal places. Do not call this until every amount has been " +
        "converted into targetCurrency — mixing currencies here would produce a meaningless total.")]
    public CalculationResult CalculateTotalProfit(
        [Description("The profit amounts to sum. Every value must already be expressed in targetCurrency.")]
        IReadOnlyList<decimal> convertedAmounts,
        [Description("The single currency that every amount in convertedAmounts is expressed in.")]
        string targetCurrency)
    {
        var total = convertedAmounts.Aggregate(0m, (sum, next) => sum + next);
        total = Math.Round(total, 2, MidpointRounding.ToEven);

        var currency = targetCurrency.Trim().ToUpperInvariant();
        logger.LogInformation(
            "Calculated total profit {Total} {Currency} from {Count} amount(s).",
            total, currency, convertedAmounts.Count);

        return new CalculationResult(total, currency, convertedAmounts.Count);
    }
}
