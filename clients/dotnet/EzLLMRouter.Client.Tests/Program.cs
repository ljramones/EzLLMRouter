using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using CognitiveDynamics.EzLLMRouter;

static class Program
{
    static string Text(JsonNode? value) => value?.GetValue<string>() ?? "";
    static int Number(JsonNode? value) => value?.GetValue<int>() ?? 0;
    static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    sealed class TrackedStream(byte[] bytes) : MemoryStream(bytes)
    {
        public bool WasDisposed { get; private set; }
        public int Reads { get; private set; }
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken token = default) { Reads++; return base.ReadAsync(buffer, token); }
        protected override void Dispose(bool disposing) { WasDisposed = true; base.Dispose(disposing); }
    }
    sealed class FakeHandler(JsonObject fixture) : HttpMessageHandler
    {
        public int Calls { get; private set; }
        public TrackedStream? Body { get; private set; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var expected = fixture["expected"]!["calls"]!.AsArray(); Check(Calls < expected.Count, "Unexpected transport invocation");
            var call = expected[Calls++]!.AsObject();
            Check(request.Method.Method == Text(call["method"]), "HTTP method mismatch");
            Check(Uri.UnescapeDataString(request.RequestUri!.PathAndQuery) == Uri.UnescapeDataString(Text(call["path"])), "Request path mismatch");
            foreach (var (key, value) in call["headers"]!.AsObject())
            {
                IEnumerable<string>? headers = null;
                bool found = request.Headers.TryGetValues(key, out headers) || request.Content is not null && request.Content.Headers.TryGetValues(key, out headers);
                Check(found && headers is not null && string.Join(",", headers) == Text(value), "Request header mismatch: " + key);
            }
            JsonNode? body = request.Content is null ? null : JsonNode.Parse(await request.Content.ReadAsStringAsync(cancellationToken));
            Check(JsonNode.DeepEquals(body, call["body"]), "Request body mismatch");
            if (fixture["lost"]?.GetValue<bool>() == true) throw new IOException("Synthetic lost acknowledgment");
            byte[] raw = fixture.ContainsKey("raw") ? Convert.FromBase64String(Text(fixture["raw"])) : Encoding.UTF8.GetBytes(fixture["response"]!.ToJsonString());
            Body = new TrackedStream(raw);
            var response = new HttpResponseMessage((HttpStatusCode)(fixture.ContainsKey("status") ? Number(fixture["status"]) : 200)) { Content = new StreamContent(Body) };
            response.Headers.Add("EzLLMRouter-Contract-Version", fixture.ContainsKey("wire") ? Text(fixture["wire"]) : "0.2");
            response.Headers.Add("EzLLMRouter-Integration-Version", fixture.ContainsKey("version") ? Text(fixture["version"]) : "1");
            if (fixture["response_headers"] is JsonObject extra)
                foreach (var (key, value) in extra)
                {
                    // Remove only existing entries: Remove rejects known header names
                    // that belong to the other header collection.
                    if (response.Headers.Any(header => header.Key.Equals(key, StringComparison.OrdinalIgnoreCase))) response.Headers.Remove(key);
                    if (response.Content.Headers.Any(header => header.Key.Equals(key, StringComparison.OrdinalIgnoreCase))) response.Content.Headers.Remove(key);
                    Check(response.Headers.TryAddWithoutValidation(key, Text(value)) ||
                          response.Content.Headers.TryAddWithoutValidation(key, Text(value)), "Invalid response fixture header: " + key);
                }
            return response;
        }
    }
    static Task<JsonObject> Invoke(EzLLMRouterClient client, IntegrationClient integration, JsonObject fixture)
    {
        var args = fixture["args"]!.AsArray(); JsonObject Obj(int index) => args[index]!.AsObject(); string Str(int index) => Text(args[index]);
        int? wait = fixture.ContainsKey("wait_ms") ? Number(fixture["wait_ms"]) : null;
        return Text(fixture["action"]) switch
        {
            "submit" => client.SubmitAsync(Obj(0), wait), "submit_in_run" => client.SubmitInRunAsync(Obj(0), Str(1), wait),
            "get_status" => client.GetStatusAsync(Obj(0)), "get_capabilities" => client.GetCapabilitiesAsync(),
            "get_successor_status" => client.GetSuccessorStatusAsync(Obj(0)), "submit_embedding" => client.SubmitEmbeddingAsync(Obj(0), wait), "submit_rerank" => client.SubmitRerankAsync(Obj(0), wait),
            "start_run" => client.StartRunAsync(Obj(0)), "get_run" => client.GetRunAsync(Str(0)),
            "report_outcome" => client.ReportOutcomeAsync(Obj(0)), "get_outcome_receipt" => client.GetOutcomeReceiptAsync(Str(0)),
            "create_dataset" => integration.CreateDatasetAsync(Obj(0)), "register_account" => integration.RegisterAccountAsync(Obj(0)),
            "set_account_state" => integration.SetAccountStateAsync(Str(0), Obj(1)), "set_account_permissions" => integration.SetAccountPermissionsAsync(Str(0), Obj(1)),
            "submit_observation" => integration.SubmitObservationAsync(Obj(0)), "recover_receipt" => integration.RecoverReceiptAsync(Str(0), Str(1)),
            "eligibility" => integration.EligibilityAsync(Str(0), Str(1), Str(2)), "operation_eligibility" => integration.OperationEligibilityAsync(Str(0), Str(1), Obj(2)),
            "report" => integration.ReportAsync(Str(0)), "submit_snapshot" => integration.SubmitSnapshotAsync(Obj(0)),
            "snapshot" => integration.SnapshotAsync(Str(0), Str(1)), "export_dataset" => integration.ExportDatasetAsync(Str(0)),
            _ => throw new Exception("Unknown case action")
        };
    }
    static async Task Parity(JsonObject fixture)
    {
        var expected = fixture["expected"]!.AsObject(); using var handler = new FakeHandler(fixture);
        using var client = new EzLLMRouterClient("http://synthetic.invalid", "synthetic-token", handler);
        using var integration = new IntegrationClient("http://synthetic.invalid", "synthetic-token", fixture.ContainsKey("version") ? Text(fixture["version"]) : "1", handler);
        try
        {
            var value = await Invoke(client, integration, fixture); Check(expected["ok"]?.GetValue<bool>() == true, "Expected failure " + expected["code"]);
            JsonNode? wanted = fixture["response"]; string action = Text(fixture["action"]);
            if (action is "start_run" or "get_run") wanted = wanted!["run"];
            if (action is "report_outcome" or "get_outcome_receipt") wanted = wanted!["receipt"];
            Check(JsonNode.DeepEquals(value, wanted), "Result mismatch");
        }
        catch (EzLLMRouterException error)
        {
            Check(error.Code == Text(expected["code"]), $"Code {error.Code} != {expected["code"]}");
            Check(error.RetryGuidance == Text(expected["retry_guidance"]), "Retry guidance mismatch");
            Check((error.HttpStatus ?? 0) == Number(expected["http_status"]), "HTTP status mismatch");
            Check(JsonNode.DeepEquals(error.Selector, expected["selector"]) && JsonNode.DeepEquals(error.Handle, expected["handle"]), "Recovery evidence mismatch");
        }
        Check(handler.Calls == expected["calls"]!.AsArray().Count, "Transport call count mismatch");
        if (handler.Body is not null)
        {
            Check(handler.Body.WasDisposed, "Response body leaked");
            if (Text(fixture["name"]) is "oversize" or "compressed") Check(handler.Body.Reads == 0, "Rejected headers read body");
        }
    }
    static async Task NativeHttp(string origin) => await TransportMatrix.Run(origin);
    static async Task LargeEmbedding(JsonArray fixtures)
    {
        var fixture = fixtures.First(row => Text(row?["name"]) == "embedding")!.DeepClone().AsObject();
        var request = fixture["args"]![0]!.AsObject(); var input = request["input"]!.AsObject(); var profile = input["profile"]!.AsObject();
        profile["dimensions"] = 2048; profile["profile_id"] = "profile.new"; profile["model_ref"] = "model.new"; request["requested_configuration_ref"] = "cfg.new";
        var result = fixture["response"]!["result"]!.AsObject(); result["dimensions"] = 2048; result["profile_id"] = "profile.new"; result["model_ref"] = "model.new";
        var items = new JsonArray(); var vectors = new JsonArray();
        for (int i = 0; i < 25; i++)
        {
            string id = "item." + i; items.Add(new JsonObject { ["item_id"] = id, ["text"] = "synthetic" });
            var coordinates = new JsonArray(); for (int n = 0; n < 2048; n++) coordinates.Add("0.1234567890123456");
            vectors.Add(new JsonObject { ["item_id"] = id, ["input_index"] = i, ["values"] = coordinates });
        }
        input["items"] = items; result["vectors"] = vectors;
        fixture["expected"]!["calls"]![0]!["body"] = request.DeepClone();
        Check(Encoding.UTF8.GetByteCount(fixture["response"]!.ToJsonString()) > 1024 * 1024, "Large fixture must exceed the legacy response limit");
        await Parity(fixture);
    }
    static async Task<int> Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--http") { await NativeHttp(args[1]); return 0; }
        DecoderCorpus.Run(Path.Combine(Path.GetDirectoryName(args[0])!, "../fixtures/contracts/transport-security/decoder_cases.json"));
        var fixtures = JsonNode.Parse(await File.ReadAllBytesAsync(args[0]))!.AsArray(); int failures = 0;
        foreach (var row in fixtures)
            try { await Parity(row!.AsObject()); } catch (Exception error) { failures++; Console.Error.WriteLine(row!["name"] + ": " + error.Message); }
        foreach (string invalid in new[] { "{\"a\":1,\"a\":2}", "{\"n\":1.5}", "{\"n\":9007199254740992}", "{\"x\":\"\\ud800\"}" })
        {
            bool rejected = false; try { ProtocolJson.ParseObject(invalid); } catch (Exception error) when (error is System.Text.Json.JsonException or InvalidOperationException) { rejected = true; }
            Check(rejected, "Invalid JSON accepted");
        }
        await LargeEmbedding(fixtures);
        Check(failures == 0, $"{failures} .NET contract failures"); Console.WriteLine($".NET: {fixtures.Count} shared contract cases and strict/large-response checks passed."); return 0;
    }
}
