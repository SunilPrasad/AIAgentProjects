using System.Text.Json;

namespace CalculateTotalRevenue.Models;

/// <summary>
/// The single JsonSerializerOptions instance used both to generate the TotalProfitReport JSON
/// schema sent to the model and to deserialize its response. Sharing one instance (rather than
/// letting each call pick its own defaults) is what guarantees the property names the model is
/// told to use match the names we parse back — a mismatch here silently nulls out every property.
/// </summary>
public static class ReportSerialization
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);
}
