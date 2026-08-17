using Microsoft.Extensions.VectorData;

public sealed class DocumentChunk
{
    [VectorStoreKey]
    public ulong Id { get; set; }

    [VectorStoreData]
    public string FileName { get; set; } = "";

    [VectorStoreData]
    public string Text { get; set; } = "";

    [VectorStoreVector(
        1536,
        DistanceFunction =
            DistanceFunction.CosineSimilarity)]
    public ReadOnlyMemory<float> Vector { get; set; }
}