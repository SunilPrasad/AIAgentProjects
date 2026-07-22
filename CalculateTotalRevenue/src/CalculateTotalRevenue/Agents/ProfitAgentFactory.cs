using CalculateTotalRevenue.Models;
using CalculateTotalRevenue.Tools;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.Logging;

namespace CalculateTotalRevenue.Agents;

/// <summary>Composition point: wires the chat pipeline (function invocation + logging) and builds the agent.</summary>
public static class ProfitAgentFactory
{
    public static AIAgent Create(
        IChatClient baseChatClient,
        CurrencyConversionTool conversionTool,
        ProfitCalculationTool calculationTool,
        ILoggerFactory loggerFactory)
    {
        IChatClient pipeline = baseChatClient
            .AsBuilder()
            .UseFunctionInvocation(loggerFactory, configure: c => c.AllowConcurrentInvocation = true)
            .UseLogging(loggerFactory)
            .Build();

        var options = new ChatClientAgentOptions
        {
            Name = "ProfitCalculationAgent",
            ChatOptions = new ChatOptions
            {
                Instructions = AgentInstructions.SystemPrompt,
                Tools =
                [
                    AIFunctionFactory.Create(conversionTool.ConvertCurrencyAsync),
                    AIFunctionFactory.Create(calculationTool.CalculateTotalProfit)
                ],
                ResponseFormat = ChatResponseFormat.ForJsonSchema(
                    typeof(TotalProfitReport),
                    ReportSerialization.Options,
                    schemaName: nameof(TotalProfitReport),
                    schemaDescription: "The final multi-currency total profit report.")
            }
        };

        return new ChatClientAgent(pipeline, options, loggerFactory);
    }
}
