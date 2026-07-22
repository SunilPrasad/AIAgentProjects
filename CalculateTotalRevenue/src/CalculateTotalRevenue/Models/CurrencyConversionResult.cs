using System.ComponentModel;

namespace CalculateTotalRevenue.Models;

/// <summary>Result of a single currency conversion tool call, including provenance (rate + timestamp) or a failure reason.</summary>
public sealed record CurrencyConversionResult(
    [property: Description("Whether the conversion succeeded. If false, ConvertedAmount is null and ErrorMessage explains why — do not proceed to calculate a total using this entry.")]
    bool Success,
    [property: Description("The original amount, in SourceCurrency, before conversion.")]
    decimal OriginalAmount,
    string SourceCurrency,
    string TargetCurrency,
    [property: Description("The amount converted into TargetCurrency, or null if the conversion failed.")]
    decimal? ConvertedAmount,
    [property: Description("The real exchange rate used, or null if the conversion failed. Never a guessed value.")]
    decimal? ExchangeRate,
    [property: Description("The date the exchange rate was published, or null if the conversion failed.")]
    DateOnly? RateDate,
    [property: Description("Explains why the conversion failed. Null when Success is true.")]
    string? ErrorMessage);
