public sealed class DocumentSearchResult
{
    public string FileName { get; set; } = "";

    public string Text { get; set; } = "";

    public double? Score { get; set; }
}