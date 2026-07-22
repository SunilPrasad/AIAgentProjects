namespace CalculateTotalRevenue.Configuration;

public sealed class ExchangeRateOptions
{
    public required string BaseUrl { get; set; }

    public int TimeoutSeconds { get; set; } = 10;
}
