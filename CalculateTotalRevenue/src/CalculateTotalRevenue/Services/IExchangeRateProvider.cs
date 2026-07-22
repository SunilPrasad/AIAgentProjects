using CalculateTotalRevenue.Models;

namespace CalculateTotalRevenue.Services;

/// <summary>Resolves real, current exchange rates. Implementations must never invent or estimate a rate.</summary>
public interface IExchangeRateProvider
{
    /// <exception cref="ExchangeRateUnavailableException">
    /// Thrown when no real rate can be obtained for the requested currency pair.
    /// </exception>
    Task<ExchangeRateQuote> GetRateAsync(string sourceCurrency, string targetCurrency, CancellationToken cancellationToken);
}
