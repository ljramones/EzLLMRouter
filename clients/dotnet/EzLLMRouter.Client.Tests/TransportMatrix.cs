using System.Text.Json.Nodes;
using CognitiveDynamics.EzLLMRouter;

internal static class TransportMatrix
{
    internal static async Task Run(string origin)
    {
        var cases = JsonNode.Parse(await File.ReadAllBytesAsync(Environment.GetEnvironmentVariable("EZLLMROUTER_TEST_MATRIX")!))!["cases"]!.AsArray();
        if (cases.Count != 28) throw new InvalidOperationException("Transport matrix inventory changed");
        foreach (var row in cases)
        {
            string name = row!["id"]!.GetValue<string>();
            string endpoint = name == "untrusted_tls" ? Environment.GetEnvironmentVariable("EZLLMROUTER_TEST_TLS_ORIGIN")! : origin;
            using var client = new EzLLMRouterClient(endpoint, "synthetic-native-" + name, timeout: TimeSpan.FromMilliseconds(row["timeout_ms"]!.GetValue<int>()));
            try
            {
                var result = await client.GetCapabilitiesAsync();
                if (row["code"] is not null || result["profile"]?.GetValue<string>() != "initial_1a@1") throw new InvalidOperationException("Unexpected HTTP success: " + name);
            }
            catch (EzLLMRouterException error)
            {
                bool status = row["http_status"]!.AsArray().Any(value => value!.GetValue<int>() == (error.HttpStatus ?? 0));
                if (row["code"]?.GetValue<string>() != error.Code || row["retry_guidance"]!.GetValue<string>() != error.RetryGuidance || !status)
                    throw new InvalidOperationException($"{name}: {error.Code}/{error.RetryGuidance}/{error.HttpStatus}");
            }
        }
        Console.WriteLine($".NET: {cases.Count} shared native HTTP cases passed.");
    }
}
