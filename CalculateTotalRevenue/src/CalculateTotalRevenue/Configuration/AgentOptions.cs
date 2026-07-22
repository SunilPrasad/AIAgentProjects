namespace CalculateTotalRevenue.Configuration;

public sealed class AgentOptions
{
    public required string Endpoint { get; set; }

    public required string ModelId { get; set; }

    /// <summary>Populated at startup from the OPENROUTER_API_KEY environment variable, never from appsettings.json.</summary>
    public string? ApiKey { get; set; }
}
