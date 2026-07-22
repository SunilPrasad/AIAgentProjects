using System.ComponentModel;
using CalculateTotalRevenue.Models;
using CalculateTotalRevenue.Services;
using Microsoft.Extensions.Logging;

namespace CalculateTotalRevenue.Tools;

/// <summary>
/// Converts a monetary amount between currencies using a real, current exchange rate.
/// This is the only place currency conversion may happen — the agent must never do this math itself.
/// </summary>
public sealed class CurrencyConversionTool(
    IExchangeRateProvider exchangeRateProvider,
    ILogger<CurrencyConversionTool> logger)
{
    [Description(
        "Converts a monetary amount from one ISO 4217 currency code to another using a real, live exchange rate. " +
        "Call this once per distinct source currency that differs from the target currency before summing profit " +
        "values — independent conversions can be called in the same turn to run in parallel. Never estimate a rate " +
        "yourself; always use this tool.")]
    public async Task<CurrencyConversionResult> ConvertCurrencyAsync(
        [Description("The monetary amount to convert, expressed in sourceCurrency.")]
        decimal amount,
        [Description("The ISO 4217 code the amount is currently expressed in, e.g. USD, EUR, GBP.")]
        string sourceCurrency,
        [Description("The ISO 4217 code to convert the amount into, e.g. USD, EUR, GBP.")]
        string targetCurrency,
        CancellationToken cancellationToken = default)
    {
        var from = sourceCurrency.Trim().ToUpperInvariant();
        var to = targetCurrency.Trim().ToUpperInvariant();

        if (from == to)
        {
            logger.LogDebug("Source and target currency are both {Currency}; skipping conversion call.", from);
            return new CurrencyConversionResult(
                Success: true,
                OriginalAmount: amount,
                SourceCurrency: from,
                TargetCurrency: to,
                ConvertedAmount: amount,
                ExchangeRate: 1m,
                RateDate: DateOnly.FromDateTime(DateTime.UtcNow),
                ErrorMessage: null);
        }

        try
        {
            var quote = await exchangeRateProvider.GetRateAsync(from, to, cancellationToken);
            var converted = Math.Round(amount * quote.Rate, 2, MidpointRounding.ToEven);

            return new CurrencyConversionResult(
                Success: true,
                OriginalAmount: amount,
                SourceCurrency: from,
                TargetCurrency: to,
                ConvertedAmount: converted,
                ExchangeRate: quote.Rate,
                RateDate: quote.AsOf,
                ErrorMessage: null);
        }
        catch (ExchangeRateUnavailableException ex)
        {
            logger.LogWarning(ex, "Currency conversion failed for {From}->{To}", from, to);

            return new CurrencyConversionResult(
                Success: false,
                OriginalAmount: amount,
                SourceCurrency: from,
                TargetCurrency: to,
                ConvertedAmount: null,
                ExchangeRate: null,
                RateDate: null,
                ErrorMessage: ex.Message);
        }
    }
}
