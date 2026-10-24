using System.Text.Json;

namespace GreatIndians.Factory;

public sealed record OutputContract(string Name, JsonElement Schema)
{
    public static OutputContract? ForStage(string stage)
    {
        if (stage == "ledger")
        {
            return new OutputContract("evidence_ledger", Parse("""
                {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "claims": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "additionalProperties": false,
                        "properties": {
                          "id": { "type": "string" },
                          "text": { "type": "string" },
                          "sourceId": { "type": "string" },
                          "quote": { "type": "string" }
                        },
                        "required": ["id", "text", "sourceId", "quote"]
                      }
                    }
                  },
                  "required": ["claims"]
                }
                """));
        }

        if (stage.Contains("review", StringComparison.Ordinal))
        {
            return new OutputContract("editorial_review", Parse("""
                {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "approved": { "type": "boolean" },
                    "findings": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "additionalProperties": false,
                        "properties": {
                          "claimId": { "type": "string" },
                          "severity": { "type": "string", "enum": ["critical", "major", "minor"] },
                          "issue": { "type": "string" },
                          "recommendedFix": { "type": "string" }
                        },
                        "required": ["claimId", "severity", "issue", "recommendedFix"]
                      }
                    },
                    "summary": { "type": "string" }
                  },
                  "required": ["approved", "findings", "summary"]
                }
                """));
        }

        return null;
    }

    private static JsonElement Parse(string json)
    {
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }
}
