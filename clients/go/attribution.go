package ezllmrouter

import (
	"context"
	"net/url"
)

func keys(v Object, required, optional []string) bool {
	if v == nil {
		return false
	}
	for _, k := range required {
		if !has(v, k) {
			return false
		}
	}
	for k := range v {
		found := false
		for _, s := range required {
			found = found || k == s
		}
		for _, s := range optional {
			found = found || k == s
		}
		if !found {
			return false
		}
	}
	return true
}
func ids(v Object, names ...string) bool {
	for _, k := range names {
		if !identifier(v[k]) {
			return false
		}
	}
	return true
}
func (c *Client) StartRun(ctx context.Context, value Object) (Object, error) {
	v, err := snapshot(value)
	required := []string{"version", "run_id", "task_id", "task_class", "evaluation_ref", "mode"}
	extras, ok := map[string][]string{"direct_human": {}, "autonomous_agent": {"agent_id", "agent_version"}, "user_delegated_agent": {"agent_id", "agent_version", "initiating_user_id"}, "nested_agent": {"agent_id", "agent_version", "parent_run_id"}}[str(v["mode"])]
	if err != nil || !ok || v["version"] != "1" || !keys(v, append(required, extras...), nil) || !ids(v, append([]string{"run_id", "task_id", "task_class", "evaluation_ref"}, extras...)...) {
		return invalid()
	}
	return c.attribution(ctx, "POST", "/v1/attribution-runs", v, false, str(v["run_id"]))
}
func (c *Client) GetRun(ctx context.Context, runID string) (Object, error) {
	if !identifier(runID) {
		return invalid()
	}
	return c.attribution(ctx, "GET", "/v1/attribution-runs/"+url.PathEscape(runID), nil, false, runID)
}
func (c *Client) ReportOutcome(ctx context.Context, value Object) (Object, error) {
	v, err := snapshot(value)
	required := []string{"version", "event_id", "run_id", "kind", "subject_revision", "verdict", "evaluator_version", "evidence_ref"}
	valid := err == nil && v["version"] == "1" && ids(v, "event_id", "run_id", "evaluator_version", "evidence_ref") && positive(v["subject_revision"])
	switch v["kind"] {
	case "task_outcome":
		valid = valid && keys(v, required, nil) && contains([]any{"accepted", "rejected", "abandoned"}, v["verdict"])
	case "step_evaluation":
		valid = valid && keys(v, append(required, "step_id", "step_revision", "execution_generation"), nil) && ids(v, "step_id", "execution_generation") && positive(v["step_revision"]) && contains([]any{"correct", "incorrect", "undetermined"}, v["verdict"])
	default:
		valid = false
	}
	if !valid {
		return invalid()
	}
	return c.attribution(ctx, "POST", "/v1/outcomes", v, true, str(v["event_id"]))
}
func (c *Client) GetOutcomeReceipt(ctx context.Context, eventID string) (Object, error) {
	if !identifier(eventID) {
		return invalid()
	}
	return c.attribution(ctx, "GET", "/v1/outcomes/"+url.PathEscape(eventID), nil, true, eventID)
}
func (c *Client) attribution(ctx context.Context, method, path string, body Object, receipt bool, expectedID string) (Object, error) {
	v, status, err := c.conn.request(ctx, method, path, "Duranki-Contract-Version", "0.2", body, nil, 1024*1024, nil)
	if err != nil {
		return nil, err
	}
	if named(v, "0.2", "ErrorResponse") && status >= 400 {
		return nil, errorEvidence(field(v, "error"), status, nil, nil)
	}
	version, key, idKey := "attribution_version", "run", "run_id"
	if receipt {
		version, key, idKey = "outcome_version", "receipt", "event_id"
	}
	item := field(v, key)
	valid := keys(v, []string{"contract_version", version, key}, nil) && v[version] == "1" && (status == 200 || receipt && status == 201) && item[idKey] == expectedID
	if receipt {
		valid = valid && keys(item, []string{"version", "event_id", "run_id", "kind", "subject_revision", "recorded_at", "event_digest"}, nil) && item["version"] == "1" && ids(item, "event_id", "run_id", "event_digest") && positive(item["subject_revision"]) && utc(item["recorded_at"]) && contains([]any{"task_outcome", "step_evaluation"}, item["kind"])
	} else {
		required := []string{"run_id", "principal_id", "charging_owner_id", "initiating_user_id", "agent_id", "agent_version", "parent_run_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "mode", "created_at", "status", "request_digest"}
		valid = valid && keys(item, required, []string{"terminal_at"}) && ids(item, "run_id", "principal_id", "charging_owner_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "request_digest") && utc(item["created_at"]) && (!has(item, "terminal_at") || utc(item["terminal_at"])) && contains([]any{"direct_human", "autonomous_agent", "user_delegated_agent", "nested_agent"}, item["mode"]) && contains([]any{"running", "accepted", "rejected", "abandoned"}, item["status"])
		for _, k := range []string{"initiating_user_id", "agent_id", "agent_version", "parent_run_id"} {
			valid = valid && (item[k] == nil || identifier(item[k]))
		}
	}
	if !valid {
		return nil, protocolError(status, nil, nil)
	}
	return item, nil
}
