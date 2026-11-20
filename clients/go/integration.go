package ezllmrouter

import (
	"context"
	"net/url"
	"strings"
)

// IntegrationClient delivers external accounting records. It never executes model work.
type IntegrationClient struct {
	conn    *connection
	version string
	path    string
}

// NewIntegrationClient selects accounting version "1", "2" or "3" explicitly.
func NewIntegrationClient(origin, token, version string, options ...Option) (*IntegrationClient, error) {
	if version != "1" && version != "2" && version != "3" {
		return nil, problem("UNSUPPORTED_VERSION", 0, "never", nil)
	}
	conn, err := connect(origin, token, options)
	if err != nil {
		return nil, err
	}
	return &IntegrationClient{conn, version, "/integration/v" + version}, nil
}
func (c *IntegrationClient) Close() error { c.conn.close(); return nil }
func (c *IntegrationClient) request(ctx context.Context, method, path string, body Object, expected ...int) (Object, error) {
	v, status, err := c.conn.request(ctx, method, c.path+path, "EzLLMRouter-Integration-Version", c.version, body, nil, 16*1024*1024, nil)
	if err != nil {
		return nil, err
	}
	if status >= 400 {
		e := field(v, "error")
		if str(e["code"]) == "" {
			return nil, problem("TRANSPORT_OUTCOME_UNKNOWN", status, "query_first", nil)
		}
		guidance := str(e["retry_guidance"])
		if guidance != "never" && guidance != "query_first" && guidance != "orchestrator_decision" {
			guidance = "never"
			if status >= 500 {
				guidance = "query_first"
			}
		}
		return nil, problem(str(e["code"]), status, guidance, nil)
	}
	for _, s := range expected {
		if status == s {
			return v, nil
		}
	}
	return nil, problem("PROTOCOL_INVALID", status, "query_first", nil)
}
func invalid() (Object, error) { return nil, problem("SCHEMA_INVALID", 0, "never", nil) }
func integrationProtocol() (Object, error) {
	return nil, problem("PROTOCOL_INVALID", 0, "query_first", nil)
}
func (c *IntegrationClient) write(ctx context.Context, path, name string, body Object, expected ...int) (Object, error) {
	b, err := snapshot(body)
	if err != nil || !named(b, c.version, name) {
		return invalid()
	}
	return c.request(ctx, "POST", path, b, expected...)
}
func (c *IntegrationClient) CreateDataset(ctx context.Context, body Object) (Object, error) {
	return c.write(ctx, "/datasets", "dataset", body, 200, 201)
}
func (c *IntegrationClient) RegisterAccount(ctx context.Context, body Object) (Object, error) {
	return c.write(ctx, "/accounts", "account", body, 200, 201)
}
func (c *IntegrationClient) SetAccountState(ctx context.Context, accountID string, body Object) (Object, error) {
	if !identifier(accountID) {
		return invalid()
	}
	return c.write(ctx, "/accounts/"+url.PathEscape(accountID)+"/state", "account_state", body, 200)
}
func (c *IntegrationClient) SetAccountPermissions(ctx context.Context, accountID string, body Object) (Object, error) {
	if c.version != "3" || !identifier(accountID) {
		return invalid()
	}
	return c.write(ctx, "/accounts/"+url.PathEscape(accountID)+"/permissions", "account_permissions", body, 200)
}
func eventValid(e Object, version string) bool {
	if !named(e, version, "event") || e["integration_version"] != version {
		return false
	}
	kind := str(e["kind"])
	if (kind == "activity" || kind == "attempt_started") && ((e["root_run_id"] == e["run_id"]) == has(e, "parent_run_id") || e["parent_run_id"] == e["run_id"]) {
		return false
	}
	if version != "1" {
		if kind == "activity" && e["activity_kind"] == "outcome" && !has(e, "outcome") {
			return false
		}
		if kind == "attempt_started" && ((e["model_identity_state"] == "known") != has(e, "model_id") || ((e["attempt_role"] == "retry" || e["attempt_role"] == "fallback") != has(e, "predecessor_attempt_id"))) {
			return false
		}
		if kind == "decision" && !evidenceValid(field(e, "eligibility_evidence")) {
			return false
		}
		if kind == "decision" && version == "3" && !selectionValid(e, "selected_model_id") {
			return false
		}
		if kind == "usage" {
			knownUnits, knownCost := e["usage_state"] == "known", e["cost_state"] == "known"
			if !uniqueUnits(array(e["native_units"])) || knownUnits != (has(e, "native_units") && has(e, "usage_provenance")) || !knownUnits && (has(e, "native_units") || has(e, "usage_provenance")) {
				return false
			}
			all, any := true, false
			for _, k := range []string{"currency", "amount_decimal", "cost_basis", "price_ref", "price_version"} {
				all = all && has(e, k)
				any = any || has(e, k)
			}
			if knownCost != all || !knownCost && (any || has(e, "zero_basis")) || knownCost && (zero(e["amount_decimal"]) != has(e, "zero_basis")) {
				return false
			}
		}
	} else if kind == "usage" && e["usage_state"] == "known" && (!uniqueUnits(array(e["native_units"])) || zero(e["amount_decimal"]) != has(e, "zero_basis")) {
		return false
	}
	return true
}
func zero(v any) bool { return strings.Trim(str(v), "0.") == "" }
func uniqueUnits(units []any) bool {
	seen := map[string]bool{}
	for _, raw := range units {
		unit := str(object(raw)["unit"])
		if seen[unit] {
			return false
		}
		seen[unit] = true
	}
	return true
}
func evidenceValid(e Object) bool {
	status := str(e["status"])
	return (status == "verified" || status == "stale" || status == "denied") == has(e, "eligibility_id")
}
func operationCapability(family any) any {
	if family == "speech_input" {
		return "transcription"
	}
	if family == "speech_output" {
		return "synthesis"
	}
	return family
}
func selectionValid(v Object, key string) bool {
	return (v["selection_kind"] == "known_model") == has(v, key) && v["capability"] == operationCapability(v["operation_family"])
}
func snapshotValid(s Object, version string) bool {
	if version == "1" || s["integration_version"] != version || !named(s, version, "snapshot") {
		return false
	}
	key, other := "features", "selected_action"
	if s["snapshot_kind"] != "feature" {
		key, other = other, key
	}
	if (s["status"] == "captured") != has(s, key) || has(s, other) || str(s["source_at"]) > str(s["available_at"]) || str(s["available_at"]) > str(s["retention_until"]) || has(s, "source_expires_at") && str(s["source_expires_at"]) < str(s["retention_until"]) {
		return false
	}
	if has(s, "selected_action") {
		a := field(s, "selected_action")
		if !evidenceValid(field(a, "eligibility_evidence")) || version == "3" && !selectionValid(a, "selected_model_id") {
			return false
		}
	}
	return true
}
func receiptValid(v Object, datasetID, eventID string) bool {
	return v["dataset_id"] == datasetID && v["event_id"] == eventID && contains([]any{"activity", "attempt_started", "decision", "result", "usage", "lineage", "account_resolution"}, v["kind"]) && hashPattern.MatchString(str(v["event_digest"])) && contains([]any{"included", "excluded_before_activation", "pending_start"}, v["membership_at_receipt"])
}
func (c *IntegrationClient) SubmitObservation(ctx context.Context, event Object) (Object, error) {
	e, err := snapshot(event)
	if err != nil || !eventValid(e, c.version) {
		return invalid()
	}
	v, err := c.request(ctx, "POST", "/events", e, 200, 201)
	if err != nil {
		return nil, err
	}
	if !receiptValid(v, str(e["dataset_id"]), str(e["event_id"])) || v["kind"] != e["kind"] || v["event_digest"] != digest(e) {
		return integrationProtocol()
	}
	return v, nil
}
func (c *IntegrationClient) RecoverReceipt(ctx context.Context, datasetID, eventID string) (Object, error) {
	if !identifier(datasetID) || !identifier(eventID) {
		return invalid()
	}
	v, err := c.request(ctx, "GET", "/events/"+url.PathEscape(eventID)+"/receipt?dataset_id="+url.QueryEscape(datasetID), nil, 200)
	if err != nil {
		return nil, err
	}
	if !receiptValid(v, datasetID, eventID) {
		return integrationProtocol()
	}
	return v, nil
}
func (c *IntegrationClient) Eligibility(ctx context.Context, datasetID, accountID, modelID string) (Object, error) {
	if c.version == "3" {
		return c.OperationEligibility(ctx, datasetID, accountID, Object{"operation_family": "generation", "capability": "generation", "selection_kind": "known_model", "model_id": modelID})
	}
	if !identifier(datasetID) || !identifier(accountID) || !identifier(modelID) {
		return invalid()
	}
	v, err := c.request(ctx, "GET", "/accounts/"+url.PathEscape(accountID)+"/eligibility?dataset_id="+url.QueryEscape(datasetID)+"&model_id="+url.QueryEscape(modelID), nil, 200)
	if err != nil {
		return nil, err
	}
	if !eligibilityValid(v, datasetID, accountID, false) || v["model_id"] != modelID || c.version == "2" && !digestValid(v) {
		return integrationProtocol()
	}
	return v, nil
}
func digestValid(v Object) bool {
	if !identifier(v["eligibility_id"]) || !utc(v["evaluated_at"]) {
		return false
	}
	signed := Object{}
	for k, x := range v {
		if k != "eligibility_digest" {
			signed[k] = x
		}
	}
	return v["eligibility_digest"] == digest(signed)
}
func eligibilityValid(v Object, datasetID, accountID string, operation bool) bool {
	usable, ok := v["usable"].(bool)
	reasons := []any{"usable", "account_disabled", "model_not_permitted"}
	if operation {
		reasons = append(reasons, "operation_not_permitted")
	}
	return v["dataset_id"] == datasetID && v["account_id"] == accountID && positive(v["account_revision"]) && ok && contains(reasons, v["reason"]) && usable == (v["reason"] == "usable")
}
func (c *IntegrationClient) OperationEligibility(ctx context.Context, datasetID, accountID string, selector Object) (Object, error) {
	s, err := snapshot(selector)
	if err != nil || c.version != "3" || !identifier(datasetID) || !identifier(accountID) || !named(s["operation_family"], "3", "operation_family") || !contains([]any{"known_model", "provider_selected", "not_applicable"}, s["selection_kind"]) || !selectionValid(s, "model_id") || has(s, "model_id") && !identifier(s["model_id"]) || s["selection_kind"] != "known_model" && s["operation_family"] != "speech_input" && s["operation_family"] != "speech_output" {
		return invalid()
	}
	query := "?dataset_id=" + url.QueryEscape(datasetID)
	for _, k := range []string{"operation_family", "capability", "selection_kind", "model_id"} {
		if has(s, k) {
			query += "&" + k + "=" + url.QueryEscape(str(s[k]))
		}
	}
	v, err := c.request(ctx, "GET", "/accounts/"+url.PathEscape(accountID)+"/eligibility"+query, nil, 200)
	if err != nil {
		return nil, err
	}
	if !eligibilityValid(v, datasetID, accountID, true) || !identifier(v["provider_id"]) || !identifier(v["credential_ref"]) || !digestValid(v) {
		return integrationProtocol()
	}
	for _, k := range []string{"operation_family", "capability", "selection_kind", "model_id"} {
		if !equal(v[k], s[k]) {
			return integrationProtocol()
		}
	}
	return v, nil
}
func (c *IntegrationClient) Report(ctx context.Context, datasetID string) (Object, error) {
	if !identifier(datasetID) {
		return invalid()
	}
	return c.request(ctx, "GET", "/reports/usage?dataset_id="+url.QueryEscape(datasetID), nil, 200)
}
func (c *IntegrationClient) SubmitSnapshot(ctx context.Context, value Object) (Object, error) {
	s, err := snapshot(value)
	if err != nil || !snapshotValid(s, c.version) {
		return invalid()
	}
	v, err := c.request(ctx, "POST", "/snapshots", s, 200, 201)
	if err != nil {
		return nil, err
	}
	if v["snapshot_id"] != s["snapshot_id"] || v["snapshot_digest"] != digest(s) {
		return integrationProtocol()
	}
	return v, nil
}
func (c *IntegrationClient) Snapshot(ctx context.Context, datasetID, snapshotID string) (Object, error) {
	if c.version == "1" || !identifier(datasetID) || !identifier(snapshotID) {
		return invalid()
	}
	return c.request(ctx, "GET", "/snapshots/"+url.PathEscape(snapshotID)+"?dataset_id="+url.QueryEscape(datasetID), nil, 200)
}
func (c *IntegrationClient) ExportDataset(ctx context.Context, datasetID string) (Object, error) {
	if c.version == "1" || !identifier(datasetID) {
		return invalid()
	}
	return c.request(ctx, "GET", "/reports/dataset?dataset_id="+url.QueryEscape(datasetID), nil, 200)
}
