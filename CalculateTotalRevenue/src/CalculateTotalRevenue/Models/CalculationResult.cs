using System.ComponentModel;

namespace CalculateTotalRevenue.Models;

/// <summary>Result of summing a set of same-currency profit amounts.</summary>
public sealed record CalculationResult(
    [property: Description("The sum of all input amounts, rounded to 2 decimal places using banker's rounding.")]
    decimal TotalProfit,
    string Currency,
    int RecordCount);
