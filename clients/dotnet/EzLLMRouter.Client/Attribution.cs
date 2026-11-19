using System.Text.Json.Nodes;
using static CognitiveDynamics.EzLLMRouter.Values;

namespace CognitiveDynamics.EzLLMRouter;

internal static class Attribution
{
    internal static Task<JsonObject> StartAsync(EzLLMRouterClient client, JsonObject value, CancellationToken cancellationToken)
    {
        var body = Protocol.Snapshot(value);
        string[]? extra = Text(At(body, "mode")) switch { "direct_human" => [], "autonomous_agent" => ["agent_id", "agent_version"], "user_delegated_agent" => ["agent_id", "agent_version", "initiating_user_id"], "nested_agent" => ["agent_id", "agent_version", "parent_run_id"], _ => null };
        string[] required = ["version", "run_id", "task_id", "task_class", "evaluation_ref", "mode"];
        if (extra is null || !Is(At(body, "version"), "1") || !Keys(body, [.. required, .. extra]) || !Ids(body, "run_id", "task_id", "task_class", "evaluation_ref") || extra.Any(key => !Id(At(body, key)))) throw Protocol.Invalid();
        return RequestAsync(client, "POST", "/v1/attribution-runs", body, false, Text(At(body, "run_id")), cancellationToken);
    }
    internal static Task<JsonObject> GetAsync(EzLLMRouterClient client, string id, bool receipt, CancellationToken cancellationToken)
    {
        if (!Id(JsonValue.Create(id))) throw Protocol.Invalid();
        return RequestAsync(client, "GET", (receipt ? "/v1/outcomes/" : "/v1/attribution-runs/") + EzLLMRouterClient.Escape(id), null, receipt, id, cancellationToken);
    }
    internal static Task<JsonObject> ReportAsync(EzLLMRouterClient client, JsonObject value, CancellationToken cancellationToken)
    {
        var body = Protocol.Snapshot(value); string[] required = ["version", "event_id", "run_id", "kind", "subject_revision", "verdict", "evaluator_version", "evidence_ref"];
        bool valid = Is(At(body, "version"), "1") && Ids(body, "event_id", "run_id", "evaluator_version", "evidence_ref") && Positive(At(body, "subject_revision"));
        if (Is(At(body, "kind"), "task_outcome")) valid &= Keys(body, required) && One(At(body, "verdict"), "accepted", "rejected", "abandoned");
        else if (Is(At(body, "kind"), "step_evaluation")) valid &= Keys(body, [.. required, "step_id", "step_revision", "execution_generation"]) && Ids(body, "step_id", "execution_generation") && Positive(At(body, "step_revision")) && One(At(body, "verdict"), "correct", "incorrect", "undetermined");
        else valid = false;
        if (!valid) throw Protocol.Invalid();
        return RequestAsync(client, "POST", "/v1/outcomes", body, true, Text(At(body, "event_id")), cancellationToken);
    }
    private static async Task<JsonObject> RequestAsync(EzLLMRouterClient client, string method, string path, JsonObject? body, bool receipt, string expectedId, CancellationToken cancellationToken)
    {
        var (value, status) = await client.Connection.RequestAsync(method, path, "EzLLMRouter-Contract-Version", "0.2", body, null, 1024 * 1024, null, cancellationToken).ConfigureAwait(false);
        if (Schema.Named(value, "0.2", "ErrorResponse") && status >= 400) throw Protocol.Evidence(At(value, "error"), status, null, null, value);
        string version = receipt ? "outcome_version" : "attribution_version", key = receipt ? "receipt" : "run";
        var item = At(value, key);
        bool valid = Keys(value, ["contract_version", version, key]) && Is(At(value, version), "1") && (status == 200 || receipt && status == 201) && Is(At(item, receipt ? "event_id" : "run_id"), expectedId);
        if (receipt) valid &= Keys(item, ["version", "event_id", "run_id", "kind", "subject_revision", "recorded_at", "event_digest"]) && Is(At(item, "version"), "1") && Ids(item, "event_id", "run_id", "event_digest") && Positive(At(item, "subject_revision")) && Utc(At(item, "recorded_at")) && One(At(item, "kind"), "task_outcome", "step_evaluation");
        else
        {
            valid &= Keys(item, ["run_id", "principal_id", "charging_owner_id", "initiating_user_id", "agent_id", "agent_version", "parent_run_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "mode", "created_at", "status", "request_digest"], "terminal_at")
                && Ids(item, "run_id", "principal_id", "charging_owner_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "request_digest") && Utc(At(item, "created_at")) && (!Has(item, "terminal_at") || Utc(At(item, "terminal_at"))) && One(At(item, "mode"), "direct_human", "autonomous_agent", "user_delegated_agent", "nested_agent") && One(At(item, "status"), "running", "accepted", "rejected", "abandoned");
            foreach (string field in new[] { "initiating_user_id", "agent_id", "agent_version", "parent_run_id" }) valid &= At(item, field) is null || Id(At(item, field));
        }
        if (!valid) throw Protocol.Bad(status, null, null);
        return item!.DeepClone().AsObject();
    }
}
