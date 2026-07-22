using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using CalculateTotalRevenue.Models;
using Microsoft.Extensions.Logging;

namespace CalculateTotalRevenue.Services;

/// <summary>
/// Resolves exchange rates from the Frankfurter API (https://frankfurter.dev), a free, keyless service
/// backed by European Central Bank reference rates. No API key or manual rate table required.
/// </summary>
public sealed class FrankfurterExchangeRateProvider(
    HttpClient httpClient,
    ILogger<FrankfurterExchangeRateProvider> logger) : IExchangeRateProvider
{
    public async Task<ExchangeRateQuote> GetRateAsync(
        string sourceCurrency,
        string targetCurrency,
        CancellationToken cancellationToken)
    {
        var from = sourceCurrency.Trim().ToUpperInvariant();
        var to = targetCurrency.Trim().ToUpperInvariant();

        var requestUri = $"v1/latest?base={Uri.EscapeDataString(from)}&symbols={Uri.EscapeDataString(to)}";
        logger.LogDebug("Requesting exchange rate {From}->{To} via {RequestUri}", from, to, requestUri);

        HttpResponseMessage response;
        try
        {
            response = await httpClient.GetAsync(requestUri, cancellationToken);
        }
        catch (HttpRequestException ex)
        {
            throw new ExchangeRateUnavailableException(from, to, $"network error contacting rate provider: {ex.Message}");
        }

        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new ExchangeRateUnavailableException(
                from, to, $"rate provider returned HTTP {(int)response.StatusCode}: {Truncate(body)}");
        }

        FrankfurterResponse? payload;
        try
        {
            payload = await response.Content.ReadFromJsonAsync<FrankfurterResponse>(cancellationToken: cancellationToken);
        }
        catch (JsonException ex)
        {
            throw new ExchangeRateUnavailableException(from, to, $"malformed response from rate provider: {ex.Message}");
        }

        if (payload?.Rates is null || !payload.Rates.TryGetValue(to, out var rate) || rate <= 0)
        {
            throw new ExchangeRateUnavailableException(
                from, to, $"rate provider returned no rate for '{from}'/'{to}' (unsupported or invalid ISO 4217 currency code)");
        }

        if (!DateOnly.TryParse(payload.Date, out var asOf))
        {
            asOf = DateOnly.FromDateTime(DateTime.UtcNow);
        }

        logger.LogInformation("Resolved exchange rate {From}->{To} = {Rate} (as of {AsOf})", from, to, rate, asOf);
        return new ExchangeRateQuote(from, to, rate, asOf);
    }

    private static string Truncate(string value) => value.Length <= 200 ? value : value[..200] + "...";

    private sealed class FrankfurterResponse
    {
        [JsonPropertyName("amount")]
        public decimal Amount { get; set; }

        [JsonPropertyName("base")]
        public string? Base { get; set; }

        [JsonPropertyName("date")]
        public string? Date { get; set; }

        [JsonPropertyName("rates")]
        public Dictionary<string, decimal>? Rates { get; set; }
    }
}
