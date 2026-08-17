using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using OpenAI;
using OpenAI.Chat;
using System.ClientModel;

// ------------------------------------------------------
// COMMAND LINE
// ------------------------------------------------------

bool shouldIndex =
    args.Any(arg =>
        string.Equals(
            arg,
            "index",
            StringComparison.OrdinalIgnoreCase));

// ------------------------------------------------------
// CONFIGURATION
// ------------------------------------------------------

var openRouterApiKey =
    Environment.GetEnvironmentVariable("OPENROUTER_API_KEY")
    ?? throw new Exception(
        "OPENROUTER_API_KEY is missing");

var qdrantEndpoint =
    "https://5c55bc1d-cac5-4de4-8b1e-65b9fae26662.eu-west-2-0.aws.cloud.qdrant.io:6334";
    

var qdrantApiKey = "";
    

var documentFolder =
    @"C:\Users\Sunil\Downloads\Question_Answer_Dataset_v1.2\Question_Answer_Dataset_v1.2\S10\data";

// ------------------------------------------------------
// OPENROUTER CLIENT
// ------------------------------------------------------

var openAIClient = new OpenAIClient(
    new ApiKeyCredential(openRouterApiKey),
    new OpenAIClientOptions
    {
        Endpoint =
            new Uri("https://openrouter.ai/api/v1")
    });

// ------------------------------------------------------
// CHAT MODEL
// ------------------------------------------------------

ChatClient chatClient =
    openAIClient.GetChatClient(
        "openai/gpt-4.1-mini");

// ------------------------------------------------------
// EMBEDDING MODEL
// ------------------------------------------------------

IEmbeddingGenerator<string, Embedding<float>>
    embeddingGenerator =
        openAIClient
            .GetEmbeddingClient(
                "openai/text-embedding-3-small")
            .AsIEmbeddingGenerator();

// ------------------------------------------------------
// QDRANT VECTOR STORE
// ------------------------------------------------------

var documentStore =
    new QdrantDocumentStore(
        qdrantEndpoint,
        qdrantApiKey,
        embeddingGenerator);

await documentStore.EnsureCollectionAsync();

// ------------------------------------------------------
// OPTIONAL INDEXING
// ------------------------------------------------------

if (shouldIndex)
{
    Console.WriteLine();
    Console.WriteLine("Indexing mode enabled.");
    Console.WriteLine();

    await documentStore.StoreDocumentsAsync(
        documentFolder);

    Console.WriteLine();
    Console.WriteLine("Indexing completed.");
}
else
{
    Console.WriteLine(
        "Skipping indexing. Using existing Qdrant data.");
}

// ------------------------------------------------------
// MICROSOFT AGENT FRAMEWORK RAG
// ------------------------------------------------------

TextSearchProviderOptions searchOptions =
    new()
    {
        SearchTime =
            TextSearchProviderOptions
                .TextSearchBehavior
                .BeforeAIInvoke
    };

AIAgent agent =
    chatClient.AsAIAgent(
        new ChatClientAgentOptions
        {
            ChatOptions = new()
            {
                Instructions = """
                    You are a RAG assistant.

                    Answer using only the retrieved context.

                    If the retrieved documents do not
                    contain the answer, say that you
                    don't know.

                    Mention the source document when possible.
                    """
            },

            AIContextProviders =
            [
                new TextSearchProvider(
                    SearchDocuments,
                    searchOptions)
            ]
        });

// ------------------------------------------------------
// ASK QUESTIONS
// ------------------------------------------------------

while (true)
{
    Console.WriteLine();

    Console.Write(
        "Question (type 'exit' to quit): ");

    var question =
        Console.ReadLine() ?? "";

    if (string.Equals(
        question,
        "exit",
        StringComparison.OrdinalIgnoreCase))
    {
        break;
    }

    if (string.IsNullOrWhiteSpace(question))
    {
        continue;
    }

    Console.WriteLine();

    var response =
        await agent.RunAsync(question);

    Console.WriteLine();
    Console.WriteLine("Answer:");
    Console.WriteLine(response);
}

// ------------------------------------------------------
// RAG RETRIEVAL
// ------------------------------------------------------

async Task<IEnumerable<
    TextSearchProvider.TextSearchResult>>
    SearchDocuments(
        string query,
        CancellationToken cancellationToken)
{
    Console.WriteLine();
    Console.WriteLine(
        $"Searching Qdrant for: {query}");

    var searchResults =
        await documentStore.SearchAsync(
            query,
            top: 3,
            cancellationToken);

    var ragResults =
        new List<
            TextSearchProvider.TextSearchResult>();

    foreach (var result in searchResults)
    {
        Console.WriteLine(
            $"Retrieved: " +
            $"{result.FileName} " +
            $"Score: {result.Score:F4}");

        ragResults.Add(
            new TextSearchProvider.TextSearchResult
            {
                SourceName =
                    result.FileName,

                Text =
                    result.Text
            });
    }

    return ragResults;
}