package com.cognitivedynamics.ezllmrouter;

import static com.cognitivedynamics.ezllmrouter.Values.*;

import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class Attribution {
    private Attribution() {}
    static Map<String, Object> start(EzLLMRouterClient client, Map<String, Object> run) {
        Map<String, Object> body = EzLLMRouterClient.snapshot(run);
        List<String> extras = switch (text(body.get("mode"))) {
            case "direct_human" -> List.of(); case "autonomous_agent" -> List.of("agent_id", "agent_version");
            case "user_delegated_agent" -> List.of("agent_id", "agent_version", "initiating_user_id");
            case "nested_agent" -> List.of("agent_id", "agent_version", "parent_run_id"); default -> null;
        };
        if (extras == null) throw Protocol.invalid();
        Set<String> required = new HashSet<>(List.of("version", "run_id", "task_id", "task_class", "evaluation_ref", "mode")); required.addAll(extras);
        if (!keys(body, required, Set.of()) || !eq(body.get("version"), "1") || !ids(body, "run_id", "task_id", "task_class", "evaluation_ref") || extras.stream().anyMatch(key -> !id(body.get(key)))) throw Protocol.invalid();
        return request(client, "POST", "/v1/attribution-runs", body, false, text(body.get("run_id")));
    }
    static Map<String, Object> report(EzLLMRouterClient client, Map<String, Object> event) {
        Map<String, Object> body = EzLLMRouterClient.snapshot(event);
        Set<String> required = new HashSet<>(List.of("version", "event_id", "run_id", "kind", "subject_revision", "verdict", "evaluator_version", "evidence_ref"));
        boolean valid = eq(body.get("version"), "1") && ids(body, "event_id", "run_id", "evaluator_version", "evidence_ref") && positive(body.get("subject_revision"));
        switch (text(body.get("kind"))) {
            case "task_outcome" -> valid &= List.of("accepted", "rejected", "abandoned").contains(text(body.get("verdict")));
            case "step_evaluation" -> { required.addAll(List.of("step_id", "step_revision", "execution_generation")); valid &= ids(body, "step_id", "execution_generation") && positive(body.get("step_revision")) && List.of("correct", "incorrect", "undetermined").contains(text(body.get("verdict"))); }
            default -> valid = false;
        }
        if (!valid || !keys(body, required, Set.of())) throw Protocol.invalid();
        return request(client, "POST", "/v1/outcomes", body, true, text(body.get("event_id")));
    }
    static Map<String, Object> request(EzLLMRouterClient client, String method, String path, Map<String, Object> body, boolean receipt, String expectedId) {
        Connection.Reply response = client.connection.request(method, path, "EzLLMRouter-Contract-Version", "0.2", body, Map.of(), 1024 * 1024, null);
        Map<String, Object> value = response.value(); int status = response.status();
        if (Schema.named(value, "0.2", "ErrorResponse") && status >= 400) throw Protocol.evidence(field(value, "error"), status, null, null, value);
        String version = receipt ? "outcome_version" : "attribution_version", key = receipt ? "receipt" : "run";
        Map<String, Object> item = field(value, key);
        boolean valid = keys(value, Set.of("contract_version", version, key), Set.of()) && eq(value.get(version), "1") && (status == 200 || receipt && status == 201) && eq(item.get(receipt ? "event_id" : "run_id"), expectedId);
        if (receipt) valid &= keys(item, Set.of("version", "event_id", "run_id", "kind", "subject_revision", "recorded_at", "event_digest"), Set.of()) && eq(item.get("version"), "1") && ids(item, "event_id", "run_id", "event_digest") && positive(item.get("subject_revision")) && utc(item.get("recorded_at")) && List.of("task_outcome", "step_evaluation").contains(text(item.get("kind")));
        else {
            valid &= keys(item, Set.of("run_id", "principal_id", "charging_owner_id", "initiating_user_id", "agent_id", "agent_version", "parent_run_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "mode", "created_at", "status", "request_digest"), Set.of("terminal_at")) && ids(item, "run_id", "principal_id", "charging_owner_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "request_digest") && utc(item.get("created_at")) && (!item.containsKey("terminal_at") || utc(item.get("terminal_at"))) && List.of("direct_human", "autonomous_agent", "user_delegated_agent", "nested_agent").contains(text(item.get("mode"))) && List.of("running", "accepted", "rejected", "abandoned").contains(text(item.get("status")));
            for (String optional : List.of("initiating_user_id", "agent_id", "agent_version", "parent_run_id")) valid &= item.get(optional) == null || id(item.get(optional));
        }
        if (!valid) throw Protocol.bad(status, null, null); return item;
    }
}
