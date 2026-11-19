package com.cognitivedynamics.ezllmrouter;

import static com.cognitivedynamics.ezllmrouter.Values.*;
import static com.cognitivedynamics.ezllmrouter.EzLLMRouterClient.escape;

import java.time.Duration;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** External accounting v1/v2/v3. Telemetry delivery never executes model work. */
public final class IntegrationClient implements AutoCloseable {
    private final Connection connection;
    private final String version;
    private final String path;
    public IntegrationClient(String origin, String token) { this(origin, token, "1"); }
    public IntegrationClient(String origin, String token, String version) { this(origin, token, version, Duration.ofSeconds(35), null); }
    public IntegrationClient(String origin, String token, String version, Transport transport) { this(origin, token, version, Duration.ofSeconds(35), transport); }
    public IntegrationClient(String origin, String token, String version, Duration timeout, Transport transport) {
        if (version == null || !List.of("1", "2", "3").contains(version)) throw Connection.error("UNSUPPORTED_VERSION", 0, "never", null);
        this.version = version; path = "/integration/v" + version; connection = new Connection(origin, token, timeout, transport);
    }
    @Override public void close() { connection.close(); }
    private static EzLLMRouterException bad() { return Connection.error("PROTOCOL_INVALID", 0, "query_first", null); }
    private Map<String, Object> request(String method, String endpoint, Map<String, Object> body, int... expected) {
        Connection.Reply response = connection.request(method, path + endpoint, "Duranki-Integration-Version", version, body, Map.of(), 16 * 1024 * 1024, null);
        Map<String, Object> value = response.value(); int status = response.status();
        if (status >= 400) {
            Map<String, Object> error = field(value, "error"); if (text(error.get("code")).isEmpty()) throw Connection.error("TRANSPORT_OUTCOME_UNKNOWN", status, "query_first", null);
            String guidance = text(error.get("retry_guidance")); throw Connection.error(text(error.get("code")), status, guidance.isEmpty() ? "never" : guidance, null);
        }
        for (int allowed : expected) if (status == allowed) return value;
        throw Connection.error("PROTOCOL_INVALID", status, "query_first", null);
    }
    private Map<String, Object> write(String endpoint, String schema, Map<String, Object> body, int... expected) {
        Map<String, Object> copy = EzLLMRouterClient.snapshot(body); if (!Schema.named(copy, version, schema)) throw Protocol.invalid(); return request("POST", endpoint, copy, expected);
    }
    public Map<String, Object> createDataset(Map<String, Object> body) { return write("/datasets", "dataset", body, 200, 201); }
    public Map<String, Object> registerAccount(Map<String, Object> body) { return write("/accounts", "account", body, 200, 201); }
    public Map<String, Object> setAccountState(String accountId, Map<String, Object> body) { if (!id(accountId)) throw Protocol.invalid(); return write("/accounts/" + escape(accountId) + "/state", "account_state", body, 200); }
    public Map<String, Object> setAccountPermissions(String accountId, Map<String, Object> body) { if (!version.equals("3") || !id(accountId)) throw Protocol.invalid(); return write("/accounts/" + escape(accountId) + "/permissions", "account_permissions", body, 200); }
    private static boolean zero(Object amount) { return text(amount).replace("0", "").replace(".", "").isEmpty(); }
    private static boolean uniqueUnits(Object raw) { Set<Object> units = new HashSet<>(); for (Object unit : array(raw)) if (!units.add(object(unit).get("unit"))) return false; return true; }
    private static boolean evidence(Map<String, Object> value) { return List.of("verified", "stale", "denied").contains(text(value.get("status"))) == value.containsKey("eligibility_id"); }
    private static Object capability(Object family) { return eq(family, "speech_input") ? "transcription" : eq(family, "speech_output") ? "synthesis" : family; }
    private static boolean selection(Map<String, Object> value, String modelKey) { return eq(value.get("selection_kind"), "known_model") == value.containsKey(modelKey) && eq(value.get("capability"), capability(value.get("operation_family"))); }
    private boolean eventValid(Map<String, Object> event) {
        if (!Schema.named(event, version, "event") || !version.equals(event.get("integration_version"))) return false;
        String kind = text(event.get("kind"));
        if (List.of("activity", "attempt_started").contains(kind) && (eq(event.get("root_run_id"), event.get("run_id")) == event.containsKey("parent_run_id") || eq(event.get("parent_run_id"), event.get("run_id")))) return false;
        if (!version.equals("1")) {
            if (kind.equals("activity") && eq(event.get("activity_kind"), "outcome") && !event.containsKey("outcome")) return false;
            if (kind.equals("attempt_started") && (eq(event.get("model_identity_state"), "known") != event.containsKey("model_id") || List.of("retry", "fallback").contains(text(event.get("attempt_role"))) != event.containsKey("predecessor_attempt_id"))) return false;
            if (kind.equals("decision") && (!evidence(field(event, "eligibility_evidence")) || version.equals("3") && !selection(event, "selected_model_id"))) return false;
            if (kind.equals("usage")) {
                boolean units = eq(event.get("usage_state"), "known"), cost = eq(event.get("cost_state"), "known");
                if (!uniqueUnits(event.get("native_units")) || units != (event.containsKey("native_units") && event.containsKey("usage_provenance")) || !units && (event.containsKey("native_units") || event.containsKey("usage_provenance"))) return false;
                List<String> fields = List.of("currency", "amount_decimal", "cost_basis", "price_ref", "price_version");
                if (cost != fields.stream().allMatch(event::containsKey) || !cost && (fields.stream().anyMatch(event::containsKey) || event.containsKey("zero_basis")) || cost && zero(event.get("amount_decimal")) != event.containsKey("zero_basis")) return false;
            }
        } else if (kind.equals("usage") && eq(event.get("usage_state"), "known") && (!uniqueUnits(event.get("native_units")) || zero(event.get("amount_decimal")) != event.containsKey("zero_basis"))) return false;
        return true;
    }
    private boolean snapshotValid(Map<String, Object> value) {
        if (version.equals("1") || !version.equals(value.get("integration_version")) || !Schema.named(value, version, "snapshot")) return false;
        String key = eq(value.get("snapshot_kind"), "feature") ? "features" : "selected_action", other = key.equals("features") ? "selected_action" : "features";
        if (eq(value.get("status"), "captured") != value.containsKey(key) || value.containsKey(other) || text(value.get("source_at")).compareTo(text(value.get("available_at"))) > 0 || text(value.get("available_at")).compareTo(text(value.get("retention_until"))) > 0 || value.containsKey("source_expires_at") && text(value.get("source_expires_at")).compareTo(text(value.get("retention_until"))) < 0) return false;
        Map<String, Object> action = field(value, "selected_action");
        return !value.containsKey("selected_action") || evidence(field(action, "eligibility_evidence")) && (!version.equals("3") || selection(action, "selected_model_id"));
    }
    private static boolean receipt(Map<String, Object> value, String datasetId, String eventId) {
        return eq(value.get("dataset_id"), datasetId) && eq(value.get("event_id"), eventId) && List.of("activity", "attempt_started", "decision", "result", "usage", "lineage", "account_resolution").contains(text(value.get("kind"))) && text(value.get("event_digest")).matches("sha256:[0-9a-f]{64}") && List.of("included", "excluded_before_activation", "pending_start").contains(text(value.get("membership_at_receipt")));
    }
    public Map<String, Object> submitObservation(Map<String, Object> event) {
        Map<String, Object> copy = EzLLMRouterClient.snapshot(event); if (!eventValid(copy)) throw Protocol.invalid();
        Map<String, Object> reply = request("POST", "/events", copy, 200, 201);
        if (!receipt(reply, text(copy.get("dataset_id")), text(copy.get("event_id"))) || !eq(reply.get("kind"), copy.get("kind")) || !eq(reply.get("event_digest"), digest(copy))) throw bad(); return reply;
    }
    public Map<String, Object> recoverReceipt(String datasetId, String eventId) {
        if (!id(datasetId) || !id(eventId)) throw Protocol.invalid();
        Map<String, Object> reply = request("GET", "/events/" + escape(eventId) + "/receipt?dataset_id=" + escape(datasetId), null, 200);
        if (!receipt(reply, datasetId, eventId)) throw bad(); return reply;
    }
    private static boolean eligibilityValid(Map<String, Object> value, String datasetId, String accountId, boolean operation) {
        List<String> reasons = operation ? List.of("usable", "account_disabled", "model_not_permitted", "operation_not_permitted") : List.of("usable", "account_disabled", "model_not_permitted");
        return eq(value.get("dataset_id"), datasetId) && eq(value.get("account_id"), accountId) && positive(value.get("account_revision")) && value.get("usable") instanceof Boolean && reasons.contains(text(value.get("reason"))) && eq(value.get("usable"), eq(value.get("reason"), "usable"));
    }
    private static boolean digestValid(Map<String, Object> value) {
        Map<String, Object> signed = new LinkedHashMap<>(value); signed.remove("eligibility_digest");
        return id(value.get("eligibility_id")) && utc(value.get("evaluated_at")) && eq(value.get("eligibility_digest"), digest(signed));
    }
    public Map<String, Object> eligibility(String datasetId, String accountId, String modelId) {
        if (!id(datasetId) || !id(accountId) || !id(modelId)) throw Protocol.invalid();
        if (version.equals("3")) return operationEligibility(datasetId, accountId, Map.of("operation_family", "generation", "capability", "generation", "selection_kind", "known_model", "model_id", modelId));
        Map<String, Object> reply = request("GET", "/accounts/" + escape(accountId) + "/eligibility?dataset_id=" + escape(datasetId) + "&model_id=" + escape(modelId), null, 200);
        if (!eligibilityValid(reply, datasetId, accountId, false) || !eq(reply.get("model_id"), modelId) || version.equals("2") && !digestValid(reply)) throw bad(); return reply;
    }
    public Map<String, Object> operationEligibility(String datasetId, String accountId, Map<String, Object> selector) {
        Map<String, Object> copy = EzLLMRouterClient.snapshot(selector);
        if (!version.equals("3") || !id(datasetId) || !id(accountId) || !Schema.named(copy.get("operation_family"), "3", "operation_family") || !List.of("known_model", "provider_selected", "not_applicable").contains(text(copy.get("selection_kind"))) || !selection(copy, "model_id") || copy.containsKey("model_id") && !id(copy.get("model_id")) || !eq(copy.get("selection_kind"), "known_model") && !List.of("speech_input", "speech_output").contains(text(copy.get("operation_family")))) throw Protocol.invalid();
        StringBuilder query = new StringBuilder("?dataset_id=" + escape(datasetId));
        for (String key : List.of("operation_family", "capability", "selection_kind", "model_id")) if (copy.containsKey(key)) query.append('&').append(key).append('=').append(escape(text(copy.get(key))));
        Map<String, Object> reply = request("GET", "/accounts/" + escape(accountId) + "/eligibility" + query, null, 200);
        if (!eligibilityValid(reply, datasetId, accountId, true) || !ids(reply, "provider_id", "credential_ref") || !digestValid(reply) || List.of("operation_family", "capability", "selection_kind", "model_id").stream().anyMatch(key -> !eq(reply.get(key), copy.get(key)))) throw bad(); return reply;
    }
    public Map<String, Object> report(String datasetId) { if (!id(datasetId)) throw Protocol.invalid(); return request("GET", "/reports/usage?dataset_id=" + escape(datasetId), null, 200); }
    public Map<String, Object> submitSnapshot(Map<String, Object> value) {
        Map<String, Object> copy = EzLLMRouterClient.snapshot(value); if (!snapshotValid(copy)) throw Protocol.invalid();
        Map<String, Object> reply = request("POST", "/snapshots", copy, 200, 201);
        if (!eq(reply.get("snapshot_id"), copy.get("snapshot_id")) || !eq(reply.get("snapshot_digest"), digest(copy))) throw bad(); return reply;
    }
    public Map<String, Object> snapshot(String datasetId, String snapshotId) { if (version.equals("1") || !id(datasetId) || !id(snapshotId)) throw Protocol.invalid(); return request("GET", "/snapshots/" + escape(snapshotId) + "?dataset_id=" + escape(datasetId), null, 200); }
    public Map<String, Object> exportDataset(String datasetId) { if (version.equals("1") || !id(datasetId)) throw Protocol.invalid(); return request("GET", "/reports/dataset?dataset_id=" + escape(datasetId), null, 200); }
}
