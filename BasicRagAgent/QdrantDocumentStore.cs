using CommunityToolkit.VectorData.Qdrant;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.VectorData;
using Qdrant.Client;

public sealed class QdrantDocumentStore
{
    private readonly VectorStoreCollection<ulong, DocumentChunk> _collection;
    private readonly IEmbeddingGenerator<string, Embedding<float>> _embeddingGenerator;

    public QdrantDocumentStore(
        string qdrantEndpoint,
        string qdrantApiKey,
        IEmbeddingGenerator<string, Embedding<float>> embeddingGenerator)
    {
        _embeddingGenerator = embeddingGenerator;

        var qdrantClient = new QdrantClient(
            new Uri(qdrantEndpoint),
            apiKey: qdrantApiKey);

        var vectorStore =
            new QdrantVectorStore(
                qdrantClient,
                ownsClient: true);

        _collection =
            vectorStore.GetCollection<ulong, DocumentChunk>(
                "QuestionAnswer");
    }

    public async Task EnsureCollectionAsync()
    {
        await _collection.EnsureCollectionExistsAsync();
    }

    public async Task StoreDocumentsAsync(
        string documentFolder)
    {
        var files = Directory.GetFiles(
            documentFolder,
            "*.clean",
            SearchOption.AllDirectories);

        Console.WriteLine(
            $"Found {files.Length} documents.");

        ulong id = 1;

        foreach (var file in files)
        {
            var text =
                await File.ReadAllTextAsync(file);

            foreach (var chunk in ChunkText(text))
            {
                var vector =
                    await _embeddingGenerator
                        .GenerateVectorAsync(chunk);

                var record = new DocumentChunk
                {
                    Id = id++,
                    FileName = Path.GetFileName(file),
                    Text = chunk,
                    Vector = vector
                };

                await _collection.UpsertAsync(record);

                Console.WriteLine(
                    $"Stored chunk {record.Id} " +
                    $"from {record.FileName}");
            }
        }

        Console.WriteLine(
            $"Finished. Stored {id - 1} chunks.");
    }

    public async Task<
        IReadOnlyList<DocumentSearchResult>>
        SearchAsync(
            string query,
            int top = 3,
            CancellationToken cancellationToken = default)
    {
        var queryVector =
            await _embeddingGenerator.GenerateVectorAsync(
                query,
                cancellationToken: cancellationToken);

        var results =
            new List<DocumentSearchResult>();

        await foreach (
            var result in _collection.SearchAsync(
                queryVector,
                top: top,
                cancellationToken: cancellationToken))
        {
            results.Add(
                new DocumentSearchResult
                {
                    FileName =
                        result.Record.FileName,

                    Text =
                        result.Record.Text,

                    Score =
                        result.Score
                });
        }

        return results;
    }

    private static IEnumerable<string>
        ChunkText(
            string text,
            int chunkSize = 1000)
    {
        for (
            int position = 0;
            position < text.Length;
            position += chunkSize)
        {
            var length =
                Math.Min(
                    chunkSize,
                    text.Length - position);

            yield return text.Substring(
                position,
                length);
        }
    }
}



