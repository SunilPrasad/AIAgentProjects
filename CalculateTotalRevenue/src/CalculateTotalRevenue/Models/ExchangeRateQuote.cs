namespace CalculateTotalRevenue.Models;

/// <summary>A real exchange rate resolved from the rate provider — never a guessed or fallback value.</summary>
public sealed record ExchangeRateQuote(
    string SourceCurrency,
    string TargetCurrency,
    decimal Rate,
    DateOnly AsOf);
