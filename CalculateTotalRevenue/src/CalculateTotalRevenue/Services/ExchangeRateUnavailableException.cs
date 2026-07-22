namespace CalculateTotalRevenue.Services;

/// <summary>
/// Thrown when a real exchange rate cannot be obtained. Callers must surface this as a failure —
/// never substitute an estimated or fallback rate.
/// </summary>
public sealed class ExchangeRateUnavailableException(string sourceCurrency, string targetCurrency, string reason)
    : Exception($"Unable to obtain an exchange rate from {sourceCurrency} to {targetCurrency}: {reason}")
{
    public string SourceCurrency { get; } = sourceCurrency;

    public string TargetCurrency { get; } = targetCurrency;
}
