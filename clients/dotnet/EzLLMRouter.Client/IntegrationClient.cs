using System.Text.Json.Nodes;
using static CognitiveDynamics.EzLLMRouter.Values;

namespace CognitiveDynamics.EzLLMRouter;

/// <summary>Async external accounting v1/v2/v3. Delivery never executes model work.</summary>
public sealed class IntegrationClient : IDisposable
{
    private readonly Connection connection;
    public string Version { get; }
    private readonly string path;
    public IntegrationClient(string origin, string token, string version = "1", HttpMessageHandler? handler = null, TimeSpan? timeout = null)
    {
        if (version is not ("1" or "2" or "3")) throw new EzLLMRouterException("UNSUPPORTED_VERSION");
        Version = version; path = "/integration/v" + version; connection = new(origin, token, handler, timeout);
    }
    public void Dispose() => connection.Dispose();
    private static EzLLMRouterException Bad() => new("PROTOCOL_INVALID", null, "query_first");
    private async Task<JsonObject> RequestAsync(string method, string endpoint, JsonObject? body, int[] expected, CancellationToken cancellationToken)
    {
        var (value, status) = await connection.RequestAsync(method, path + endpoint, "EzLLMRouter-Integration-Version", Version, body, null, 16 * 1024 * 1024, null, cancellationToken).ConfigureAwait(false);
        if (status >= 400)
        {
            var error = At(value, "error"); string code = Text(At(error, "code")), guidance = Text(At(error, "retry_guidance"));
            if (code.Length == 0) throw new EzLLMRouterException("TRANSPORT_OUTCOME_UNKNOWN", status, "query_first");
            throw new EzLLMRouterException(code, status, guidance is "never" or "query_first" or "orchestrator_decision" ? guidance : status >= 500 ? "query_first" : "never");
        }
        if (!expected.Contains(status)) throw new EzLLMRouterException("PROTOCOL_INVALID", status, "query_first");
        return value;
    }
    private Task<JsonObject> WriteAsync(string endpoint, string shape, JsonObject body, int[] expected, CancellationToken cancellationToken)
    {
        var copy = Protocol.Snapshot(body); if (!Schema.Named(copy, Version, shape)) throw Protocol.Invalid();
        return RequestAsync("POST", endpoint, copy, expected, cancellationToken);
    }
    public Task<JsonObject> CreateDatasetAsync(JsonObject body, CancellationToken cancellationToken = default) => WriteAsync("/datasets", "dataset", body, [200, 201], cancellationToken);
    public Task<JsonObject> RegisterAccountAsync(JsonObject body, CancellationToken cancellationToken = default) => WriteAsync("/accounts", "account", body, [200, 201], cancellationToken);
    public Task<JsonObject> SetAccountStateAsync(string accountId, JsonObject body, CancellationToken cancellationToken = default)
    {
        if (!Id(JsonValue.Create(accountId))) throw Protocol.Invalid();
        return WriteAsync("/accounts/" + EzLLMRouterClient.Escape(accountId) + "/state", "account_state", body, [200], cancellationToken);
    }
    public Task<JsonObject> SetAccountPermissionsAsync(string accountId, JsonObject body, CancellationToken cancellationToken = default)
    {
        if (Version != "3" || !Id(JsonValue.Create(accountId))) throw Protocol.Invalid();
        return WriteAsync("/accounts/" + EzLLMRouterClient.Escape(accountId) + "/permissions", "account_permissions", body, [200], cancellationToken);
    }
    private static bool Zero(JsonNode? value) => Text(value).Trim('0', '.').Length == 0;
    private static bool UniqueUnits(JsonNode? units) { var seen = new HashSet<string>(); return Items(units).All(unit => seen.Add(Text(At(unit, "unit")))); }
    private static bool Evidence(JsonNode? value) => One(At(value, "status"), "verified", "stale", "denied") == Has(value, "eligibility_id");
    private static string Capability(JsonNode? family) => Text(family) switch { "speech_input" => "transcription", "speech_output" => "synthesis", var name => name };
    private static bool Selection(JsonNode? value, string modelKey) => Is(At(value, "selection_kind"), "known_model") == Has(value, modelKey) && Text(At(value, "capability")) == Capability(At(value, "operation_family"));
    private bool EventValid(JsonObject value)
    {
        if (!Schema.Named(value, Version, "event") || !Is(At(value, "integration_version"), Version)) return false;
        string kind = Text(At(value, "kind"));
        if ((kind is "activity" or "attempt_started") && (Eq(At(value, "root_run_id"), At(value, "run_id")) == Has(value, "parent_run_id") || Eq(At(value, "parent_run_id"), At(value, "run_id")))) return false;
        if (Version != "1")
        {
            if (kind == "activity" && Is(At(value, "activity_kind"), "outcome") && !Has(value, "outcome")) return false;
            if (kind == "attempt_started" && (Is(At(value, "model_identity_state"), "known") != Has(value, "model_id") || One(At(value, "attempt_role"), "retry", "fallback") != Has(value, "predecessor_attempt_id"))) return false;
            if (kind == "decision" && (!Evidence(At(value, "eligibility_evidence")) || Version == "3" && !Selection(value, "selected_model_id"))) return false;
            if (kind == "usage")
            {
                bool units = Is(At(value, "usage_state"), "known"), cost = Is(At(value, "cost_state"), "known");
                if (!UniqueUnits(At(value, "native_units")) || units != (Has(value, "native_units") && Has(value, "usage_provenance")) || !units && (Has(value, "native_units") || Has(value, "usage_provenance"))) return false;
                string[] fields = ["currency", "amount_decimal", "cost_basis", "price_ref", "price_version"];
                if (cost != fields.All(key => Has(value, key)) || !cost && (fields.Any(key => Has(value, key)) || Has(value, "zero_basis")) || cost && Zero(At(value, "amount_decimal")) != Has(value, "zero_basis")) return false;
            }
        }
        else if (kind == "usage" && Is(At(value, "usage_state"), "known") && (!UniqueUnits(At(value, "native_units")) || Zero(At(value, "amount_decimal")) != Has(value, "zero_basis"))) return false;
        return true;
    }
    private bool SnapshotValid(JsonObject value)
    {
        if (Version == "1" || !Is(At(value, "integration_version"), Version) || !Schema.Named(value, Version, "snapshot")) return false;
        string key = Is(At(value, "snapshot_kind"), "feature") ? "features" : "selected_action", other = key == "features" ? "selected_action" : "features";
        if (Is(At(value, "status"), "captured") != Has(value, key) || Has(value, other) || string.CompareOrdinal(Text(At(value, "source_at")), Text(At(value, "available_at"))) > 0 || string.CompareOrdinal(Text(At(value, "available_at")), Text(At(value, "retention_until"))) > 0 || Has(value, "source_expires_at") && string.CompareOrdinal(Text(At(value, "source_expires_at")), Text(At(value, "retention_until"))) < 0) return false;
        var action = At(value, "selected_action");
        return !Has(value, "selected_action") || Evidence(At(action, "eligibility_evidence")) && (Version != "3" || Selection(action, "selected_model_id"));
    }
    private static bool Receipt(JsonObject value, string datasetId, string eventId) => Is(At(value, "dataset_id"), datasetId) && Is(At(value, "event_id"), eventId)
        && One(At(value, "kind"), "activity", "attempt_started", "decision", "result", "usage", "lineage", "account_resolution")
        && System.Text.RegularExpressions.Regex.IsMatch(Text(At(value, "event_digest")), "^sha256:[0-9a-f]{64}$") && One(At(value, "membership_at_receipt"), "included", "excluded_before_activation", "pending_start");
    public async Task<JsonObject> SubmitObservationAsync(JsonObject value, CancellationToken cancellationToken = default)
    {
        var copy = Protocol.Snapshot(value); if (!EventValid(copy)) throw Protocol.Invalid();
        var reply = await RequestAsync("POST", "/events", copy, [200, 201], cancellationToken).ConfigureAwait(false);
        if (!Receipt(reply, Text(At(copy, "dataset_id")), Text(At(copy, "event_id"))) || !Eq(At(reply, "kind"), At(copy, "kind")) || !Is(At(reply, "event_digest"), ProtocolJson.Digest(copy))) throw Bad();
        return reply;
    }
    public async Task<JsonObject> RecoverReceiptAsync(string datasetId, string eventId, CancellationToken cancellationToken = default)
    {
        if (!Id(JsonValue.Create(datasetId)) || !Id(JsonValue.Create(eventId))) throw Protocol.Invalid();
        var reply = await RequestAsync("GET", "/events/" + EzLLMRouterClient.Escape(eventId) + "/receipt?dataset_id=" + EzLLMRouterClient.Escape(datasetId), null, [200], cancellationToken).ConfigureAwait(false);
        if (!Receipt(reply, datasetId, eventId)) throw Bad(); return reply;
    }
    private static bool EligibilityValid(JsonObject value, string datasetId, string accountId, bool operation) => Is(At(value, "dataset_id"), datasetId) && Is(At(value, "account_id"), accountId) && Positive(At(value, "account_revision"))
        && (At(value, "usable")?.GetValueKind() is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False)
        && (operation ? One(At(value, "reason"), "usable", "account_disabled", "model_not_permitted", "operation_not_permitted") : One(At(value, "reason"), "usable", "account_disabled", "model_not_permitted"))
        && Schema.IsTrue(At(value, "usable")) == Is(At(value, "reason"), "usable");
    private static bool DigestValid(JsonObject value)
    {
        var signed = value.DeepClone().AsObject(); signed.Remove("eligibility_digest");
        return Id(At(value, "eligibility_id")) && Utc(At(value, "evaluated_at")) && Is(At(value, "eligibility_digest"), ProtocolJson.Digest(signed));
    }
    public async Task<JsonObject> EligibilityAsync(string datasetId, string accountId, string modelId, CancellationToken cancellationToken = default)
    {
        if (!new[] { datasetId, accountId, modelId }.All(value => Id(JsonValue.Create(value)))) throw Protocol.Invalid();
        if (Version == "3") return await OperationEligibilityAsync(datasetId, accountId, new JsonObject { ["operation_family"] = "generation", ["capability"] = "generation", ["selection_kind"] = "known_model", ["model_id"] = modelId }, cancellationToken).ConfigureAwait(false);
        var reply = await RequestAsync("GET", "/accounts/" + EzLLMRouterClient.Escape(accountId) + "/eligibility?dataset_id=" + EzLLMRouterClient.Escape(datasetId) + "&model_id=" + EzLLMRouterClient.Escape(modelId), null, [200], cancellationToken).ConfigureAwait(false);
        if (!EligibilityValid(reply, datasetId, accountId, false) || !Is(At(reply, "model_id"), modelId) || Version == "2" && !DigestValid(reply)) throw Bad(); return reply;
    }
    public async Task<JsonObject> OperationEligibilityAsync(string datasetId, string accountId, JsonObject selector, CancellationToken cancellationToken = default)
    {
        var copy = Protocol.Snapshot(selector);
        if (Version != "3" || !Id(JsonValue.Create(datasetId)) || !Id(JsonValue.Create(accountId)) || !Schema.Named(At(copy, "operation_family"), "3", "operation_family") || !One(At(copy, "selection_kind"), "known_model", "provider_selected", "not_applicable") || !Selection(copy, "model_id") || Has(copy, "model_id") && !Id(At(copy, "model_id")) || !Is(At(copy, "selection_kind"), "known_model") && !One(At(copy, "operation_family"), "speech_input", "speech_output")) throw Protocol.Invalid();
        string query = "?dataset_id=" + EzLLMRouterClient.Escape(datasetId);
        foreach (string key in new[] { "operation_family", "capability", "selection_kind", "model_id" }) if (Has(copy, key)) query += "&" + key + "=" + EzLLMRouterClient.Escape(Text(At(copy, key)));
        var reply = await RequestAsync("GET", "/accounts/" + EzLLMRouterClient.Escape(accountId) + "/eligibility" + query, null, [200], cancellationToken).ConfigureAwait(false);
        if (!EligibilityValid(reply, datasetId, accountId, true) || !Ids(reply, "provider_id", "credential_ref") || !DigestValid(reply) || new[] { "operation_family", "capability", "selection_kind", "model_id" }.Any(key => !Eq(At(reply, key), At(copy, key)))) throw Bad(); return reply;
    }
    public Task<JsonObject> ReportAsync(string datasetId, CancellationToken cancellationToken = default)
    { if (!Id(JsonValue.Create(datasetId))) throw Protocol.Invalid(); return RequestAsync("GET", "/reports/usage?dataset_id=" + EzLLMRouterClient.Escape(datasetId), null, [200], cancellationToken); }
    public async Task<JsonObject> SubmitSnapshotAsync(JsonObject value, CancellationToken cancellationToken = default)
    {
        var copy = Protocol.Snapshot(value); if (!SnapshotValid(copy)) throw Protocol.Invalid();
        var reply = await RequestAsync("POST", "/snapshots", copy, [200, 201], cancellationToken).ConfigureAwait(false);
        if (!Eq(At(reply, "snapshot_id"), At(copy, "snapshot_id")) || !Is(At(reply, "snapshot_digest"), ProtocolJson.Digest(copy))) throw Bad(); return reply;
    }
    public Task<JsonObject> SnapshotAsync(string datasetId, string snapshotId, CancellationToken cancellationToken = default)
    { if (Version == "1" || !Id(JsonValue.Create(datasetId)) || !Id(JsonValue.Create(snapshotId))) throw Protocol.Invalid(); return RequestAsync("GET", "/snapshots/" + EzLLMRouterClient.Escape(snapshotId) + "?dataset_id=" + EzLLMRouterClient.Escape(datasetId), null, [200], cancellationToken); }
    public Task<JsonObject> ExportDatasetAsync(string datasetId, CancellationToken cancellationToken = default)
    { if (Version == "1" || !Id(JsonValue.Create(datasetId))) throw Protocol.Invalid(); return RequestAsync("GET", "/reports/dataset?dataset_id=" + EzLLMRouterClient.Escape(datasetId), null, [200], cancellationToken); }
}
