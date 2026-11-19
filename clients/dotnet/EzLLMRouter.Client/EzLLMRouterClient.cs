using System.Text;
using System.Text.Json.Nodes;
using static CognitiveDynamics.EzLLMRouter.Values;

namespace CognitiveDynamics.EzLLMRouter;

/// <summary>Async execution, retrieval, attribution and outcome API client.</summary>
public sealed class EzLLMRouterClient : IDisposable
{
    public const string Version = "0.3.0";
    internal Connection Connection { get; }
    public EzLLMRouterClient(string origin, string token, HttpMessageHandler? handler = null, TimeSpan? timeout = null) => Connection = new(origin, token, handler, timeout);
    public void Dispose() => Connection.Dispose();
    internal static string Escape(string value) => Uri.EscapeDataString(value);
    private static Dictionary<string, string> Wait(int? waitMs)
    {
        if (waitMs is < 0 or > 30000) throw Protocol.Invalid();
        return waitMs.HasValue ? new() { ["EzLLMRouter-Wait-Ms"] = waitMs.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) } : [];
    }
    public Task<JsonObject> SubmitAsync(JsonObject request, int? waitMs = null, CancellationToken cancellationToken = default) => SubmitInRunAsync(request, null, waitMs, cancellationToken);
    public Task<JsonObject> SubmitInRunAsync(JsonObject request, string? runId, int? waitMs = null, CancellationToken cancellationToken = default)
    {
        var body = Protocol.Snapshot(request); var selector = new JsonObject();
        foreach (string key in Protocol.SelectorKeys) selector[key] = At(body, key)?.DeepClone();
        if (!Schema.Named(selector, "0.2", "WorkSelector") || runId is not null && !Id(JsonValue.Create(runId))) throw Protocol.Invalid();
        var headers = Wait(waitMs);
        if (runId is not null) { headers["EzLLMRouter-Attribution-Version"] = "1"; headers["EzLLMRouter-Attribution-Run"] = runId; }
        return WireAsync("POST", "/v1/submissions", "0.2", "submit", body, selector, headers, cancellationToken);
    }
    public Task<JsonObject> GetStatusAsync(JsonObject selector, CancellationToken cancellationToken = default) => StatusAsync(selector, "0.2", cancellationToken);
    public Task<JsonObject> GetSuccessorStatusAsync(JsonObject selector, CancellationToken cancellationToken = default) => StatusAsync(selector, "0.3", cancellationToken);
    private Task<JsonObject> StatusAsync(JsonObject selector, string version, CancellationToken cancellationToken)
    {
        var selected = Protocol.Snapshot(selector); JsonObject work = selected; string path;
        if (version == "0.3") { if (!Schema.Named(selected, version, "StatusQuery")) throw Protocol.Invalid(); if (Has(selected, "work_selector")) work = selected["work_selector"]!.AsObject(); }
        if (selected.Count == 1 && Id(At(selected, "submission_id"))) path = "/v1/submissions/" + Escape(Text(At(selected, "submission_id")));
        else if (Schema.Named(work, version, "WorkSelector")) path = "/v1/submissions/by-work/" + string.Join('/', Protocol.SelectorKeys.Select(key => Escape(key == "step_revision" ? Number(At(work, key)).ToString(System.Globalization.CultureInfo.InvariantCulture) : Text(At(work, key)))));
        else throw Protocol.Invalid();
        return WireAsync("GET", path, version, "status", null, work, null, cancellationToken);
    }
    public Task<JsonObject> GetCapabilitiesAsync(CancellationToken cancellationToken = default) => WireAsync("GET", "/v1/capabilities", "0.2", "capabilities", null, null, null, cancellationToken);
    public Task<JsonObject> SubmitEmbeddingAsync(JsonObject request, int? waitMs = null, CancellationToken cancellationToken = default) => SuccessorAsync(request, "embedding.create", waitMs, cancellationToken);
    public Task<JsonObject> SubmitRerankAsync(JsonObject request, int? waitMs = null, CancellationToken cancellationToken = default) => SuccessorAsync(request, "rerank", waitMs, cancellationToken);
    private Task<JsonObject> SuccessorAsync(JsonObject request, string operation, int? waitMs, CancellationToken cancellationToken)
    {
        var body = Protocol.Snapshot(request);
        if (!Schema.Named(body, "0.3", "SubmitRequest") || !Is(At(At(body, "operation"), "type"), operation)) throw Protocol.Invalid();
        if (Encoding.UTF8.GetByteCount(ProtocolJson.Stringify(body)) > 262144) throw new EzLLMRouterException("LIMIT_EXCEEDED");
        return WireAsync("POST", "/v1/submissions", "0.3", "submit", body, body["work_selector"]!.AsObject(), Wait(waitMs), cancellationToken);
    }
    private async Task<JsonObject> WireAsync(string method, string path, string version, string kind, JsonObject? body, JsonObject? selector, Dictionary<string, string>? headers, CancellationToken cancellationToken)
    {
        var (value, status) = await Connection.RequestAsync(method, path, "EzLLMRouter-Contract-Version", version, body, headers, version == "0.3" ? 16 * 1024 * 1024 : 1024 * 1024, selector, cancellationToken).ConfigureAwait(false);
        var handle = Protocol.MatchingHandle(value, selector, version);
        bool envelopeError = version == "0.3" ? Has(value, "code") : Has(value, "error") && !Has(value, "state");
        if (envelopeError)
        {
            bool validError = version == "0.3" ? Protocol.SuccessorError(value, status, kind) : Schema.Named(value, version, "ErrorResponse") && status >= 400;
            if (!validError) throw Protocol.Bad(status, selector, null);
            throw Protocol.Evidence(version == "0.3" ? value : At(value, "error"), status, selector, null, value);
        }
        bool valid = version == "0.3" ? Protocol.Successor(value, status, kind, body) : Protocol.Wire02(value, status, kind);
        if (selector is not null && handle is null && !(version == "0.2" && kind == "submit" && Is(At(value, "state"), "rejected") && Eq(At(value, "selector"), selector))) valid = false;
        if (!valid) throw Protocol.Bad(status, selector, handle);
        if (One(At(value, "state"), "failed", "rejected")) throw Protocol.Evidence(At(value, "error"), status, selector, handle, value);
        return value;
    }
    public Task<JsonObject> StartRunAsync(JsonObject run, CancellationToken cancellationToken = default) => Attribution.StartAsync(this, run, cancellationToken);
    public Task<JsonObject> GetRunAsync(string runId, CancellationToken cancellationToken = default) => Attribution.GetAsync(this, runId, false, cancellationToken);
    public Task<JsonObject> ReportOutcomeAsync(JsonObject value, CancellationToken cancellationToken = default) => Attribution.ReportAsync(this, value, cancellationToken);
    public Task<JsonObject> GetOutcomeReceiptAsync(string eventId, CancellationToken cancellationToken = default) => Attribution.GetAsync(this, eventId, true, cancellationToken);
}
