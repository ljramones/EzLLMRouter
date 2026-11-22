using System.Text.Json;
using System.Text.Json.Nodes;
using CognitiveDynamics.EzLLMRouter;

internal static class DecoderCorpus
{
    internal static void Run(string path)
    {
        var cases = JsonNode.Parse(File.ReadAllBytes(path))!["cases"]!.AsArray();
        if (cases.Count != 536) throw new InvalidOperationException("Decoder corpus inventory changed");
        foreach (var row in cases)
        {
            string? actual = null;
            try { actual = ProtocolJson.Stringify(ProtocolJson.ParseObject(Convert.FromHexString(row!["raw_hex"]!.GetValue<string>()))); }
            catch (Exception error) when (error is JsonException or InvalidOperationException) { }
            if (actual != row!["canonical"]?.GetValue<string>())
                throw new InvalidOperationException("Decoder corpus mismatch: " + row["id"]);
        }
        Console.WriteLine($".NET: {cases.Count} independent decoder cases passed.");
    }
}
