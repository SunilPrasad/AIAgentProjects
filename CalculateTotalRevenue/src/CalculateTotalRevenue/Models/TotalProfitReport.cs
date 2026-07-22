using System.ComponentModel;

namespace CalculateTotalRevenue.Models;

/// <summary>
/// The required schema for the agent's final answer. The model must populate this only after every
/// required currency conversion has succeeded and the calculation tool has produced a total.
/// </summary>
public sealed record TotalProfitReport(
    [property: Description("The single currency all profit values were converted into and summed in.")]
    string TargetCurrency,

    [property: Description("Every profit value exactly as reported in the request, before any conversion.")]
    IReadOnlyList<TotalProfitReport.OriginalEntry> OriginalEntries,

    [property: Description("Each entry that required currency conversion, with the rate and rate date used. Empty if no conversion was needed.")]
    IReadOnlyList<TotalProfitReport.ConvertedEntry> ConvertedEntries,

    [property: Description("The final summed total profit in TargetCurrency. Null if the report could not be completed (see Success/Notes).")]
    decimal? FinalTotalProfit,

    [property: Description("False if any required conversion failed or the request was ambiguous/incomplete — in that case FinalTotalProfit must be null.")]
    bool Success,

    [property: Description("Human-readable explanation: assumptions made (e.g. an inferred target currency), or the reason the report could not be completed.")]
    string Notes)
{
    public sealed record OriginalEntry(decimal Amount, string Currency);

    public sealed record ConvertedEntry(
        decimal OriginalAmount,
        string OriginalCurrency,
        decimal ConvertedAmount,
        decimal ExchangeRate,
        string RateDate);
}
