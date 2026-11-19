// Package ezllmrouter provides synchronous execution and accounting clients.
// Clients contact only the configured EzLLMRouter service, never a model provider.
package ezllmrouter

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

// Version is the client package version, independent of wire contract versions.
const Version = "0.3.0"

// Client supports wire 0.2 text/tools, wire 0.3 embedding/rerank and attribution v1.
type Client struct{ conn *connection }

// NewClient creates a client for a trusted service origin.
func NewClient(origin, token string, options ...Option) (*Client, error) {
	c, err := connect(origin, token, options)
	if err != nil {
		return nil, err
	}
	return &Client{c}, nil
}

// Close releases owned transport resources. Further operations fail locally.
func (c *Client) Close() error { c.conn.close(); return nil }

// SubmitOptions controls the server wait. A nil WaitMS omits the header; zero is explicit.
type SubmitOptions struct{ WaitMS *int }

func headers(options *SubmitOptions) (http.Header, error) {
	h := http.Header{}
	if options != nil && options.WaitMS != nil {
		wait := *options.WaitMS
		if wait < 0 || wait > 30000 {
			return nil, problem("SCHEMA_INVALID", 0, "never", nil)
		}
		h.Set("EzLLMRouter-Wait-Ms", strconv.Itoa(wait))
	}
	return h, nil
}
func (c *Client) Submit(ctx context.Context, request Object, options *SubmitOptions) (Object, error) {
	return c.submit(ctx, request, options, "")
}
func (c *Client) SubmitInRun(ctx context.Context, request Object, runID string, options *SubmitOptions) (Object, error) {
	if !identifier(runID) {
		return nil, problem("SCHEMA_INVALID", 0, "never", nil)
	}
	return c.submit(ctx, request, options, runID)
}
func (c *Client) submit(ctx context.Context, request Object, options *SubmitOptions, runID string) (Object, error) {
	body, err := snapshot(request)
	if err != nil || body == nil || !named(selected(body), "0.2", "WorkSelector") {
		return nil, problem("SCHEMA_INVALID", 0, "never", nil)
	}
	h, err := headers(options)
	if err != nil {
		return nil, err
	}
	if runID != "" {
		h.Set("EzLLMRouter-Attribution-Version", "1")
		h.Set("EzLLMRouter-Attribution-Run", runID)
	}
	return c.wire(ctx, "POST", "/v1/submissions", "0.2", "submit", body, selected(body), h)
}

// GetStatus accepts either a submission_id or the four wire-0.2 work selector fields.
func (c *Client) GetStatus(ctx context.Context, selector Object) (Object, error) {
	return c.getStatus(ctx, selector, "0.2")
}

// GetSuccessorStatus accepts submission_id or {work_selector: {...}} for wire 0.3.
func (c *Client) GetSuccessorStatus(ctx context.Context, selector Object) (Object, error) {
	return c.getStatus(ctx, selector, "0.3")
}
func (c *Client) getStatus(ctx context.Context, selector Object, version string) (Object, error) {
	s, err := snapshot(selector)
	if err != nil || s == nil {
		return nil, problem("SCHEMA_INVALID", 0, "never", nil)
	}
	path := ""
	query := s
	if version == "0.3" {
		if !named(s, version, "StatusQuery") {
			return nil, problem("SCHEMA_INVALID", 0, "never", nil)
		}
		if has(s, "work_selector") {
			query = field(s, "work_selector")
		}
	}
	if len(s) == 1 && identifier(s["submission_id"]) {
		path = "/v1/submissions/" + url.PathEscape(str(s["submission_id"]))
	} else if named(query, version, "WorkSelector") {
		pieces := []string{}
		for _, k := range selectorKeys {
			pieces = append(pieces, url.PathEscape(fmt.Sprint(query[k])))
		}
		path = "/v1/submissions/by-work/" + strings.Join(pieces, "/")
	} else {
		return nil, problem("SCHEMA_INVALID", 0, "never", nil)
	}
	return c.wire(ctx, "GET", path, version, "status", nil, query, nil)
}
func (c *Client) GetCapabilities(ctx context.Context) (Object, error) {
	return c.wire(ctx, "GET", "/v1/capabilities", "0.2", "capabilities", nil, nil, nil)
}
func (c *Client) SubmitEmbedding(ctx context.Context, request Object, options *SubmitOptions) (Object, error) {
	return c.submitSuccessor(ctx, request, options, "embedding.create")
}
func (c *Client) SubmitRerank(ctx context.Context, request Object, options *SubmitOptions) (Object, error) {
	return c.submitSuccessor(ctx, request, options, "rerank")
}
func (c *Client) submitSuccessor(ctx context.Context, request Object, options *SubmitOptions, operation string) (Object, error) {
	body, err := snapshot(request)
	if err != nil || !named(body, "0.3", "SubmitRequest") || field(body, "operation")["type"] != operation {
		return nil, problem("SCHEMA_INVALID", 0, "never", nil)
	}
	raw, _ := canonical(body)
	if len(raw) > 262144 {
		return nil, problem("LIMIT_EXCEEDED", 0, "never", nil)
	}
	h, err := headers(options)
	if err != nil {
		return nil, err
	}
	return c.wire(ctx, "POST", "/v1/submissions", "0.3", "submit", body, field(body, "work_selector"), h)
}
func (c *Client) wire(ctx context.Context, method, path, version, kind string, body, selector Object, h http.Header) (Object, error) {
	limit := 1024 * 1024
	if version == "0.3" {
		limit = 16 * 1024 * 1024
	}
	value, status, err := c.conn.request(ctx, method, path, "EzLLMRouter-Contract-Version", version, body, h, limit, selector)
	if err != nil {
		return nil, err
	}
	handle := matchingHandle(value, selector, version)
	envelopeError := has(value, "error") && !has(value, "state")
	if version == "0.3" {
		envelopeError = has(value, "code")
	}
	if envelopeError {
		evidence := value
		valid := successorError(value, status, kind)
		if version == "0.2" {
			evidence = field(value, "error")
			valid = named(value, version, "ErrorResponse") && status >= 400
		}
		if !valid {
			return nil, protocolError(status, selector, nil)
		}
		return nil, errorEvidence(evidence, status, selector, nil)
	}
	valid := wire02Valid(value, status, kind)
	if version == "0.3" {
		valid = successorValid(value, status, kind, body)
	}
	if selector != nil && handle == nil {
		valid = false
		if version == "0.2" && kind == "submit" && value["state"] == "rejected" && equal(field(value, "selector"), selector) {
			valid = wire02Valid(value, status, kind)
		}
	}
	if !valid {
		return nil, protocolError(status, selector, handle)
	}
	if value["state"] == "failed" || value["state"] == "rejected" {
		e := errorEvidence(field(value, "error"), status, selector, handle)
		e.AttemptID = str(value["attempt_id"])
		e.FailureStage = str(value["failure_stage"])
		return nil, e
	}
	return value, nil
}

func wire02Usage(v Object) bool {
	if v["state"] != "available" {
		return true
	}
	r := field(v, "revision")
	return !has(r, "previous_revision") || integer(r["previous_revision"]) < integer(r["revision"])
}
func usageIdentity(v Object, attempt any) bool {
	return wire02Usage(v) && (v["state"] != "available" || field(v, "revision")["attempt_id"] == attempt)
}
func wire02Candidate(v Object) bool {
	if !usageIdentity(field(v, "usage"), v["attempt_id"]) {
		return false
	}
	seen := map[string]bool{}
	calls := map[string]bool{}
	tool := false
	for _, raw := range array(v["output_blocks"]) {
		b := object(raw)
		id := str(b["block_id"])
		if seen[id] {
			return false
		}
		seen[id] = true
		if b["kind"] == "tool_call" {
			id = str(b["call_id"])
			if calls[id] {
				return false
			}
			calls[id] = true
			tool = true
		}
	}
	return v["finish_reason"] != "tool_calls" || tool
}
func wire02Valid(v Object, status int, kind string) bool {
	name := map[string]string{"submit": "SubmitReply", "status": "StatusSnapshot", "capabilities": "CapabilityResponse"}[kind]
	if !named(v, "0.2", name) {
		return false
	}
	if kind == "capabilities" {
		if status != 200 {
			return false
		}
		for _, f := range array(v["supported_features"]) {
			if contains(array(v["disabled_features"]), f) {
				return false
			}
		}
		return true
	}
	generation := field(field(v, "handle"), "work_key")["execution_generation"]
	if kind == "submit" {
		switch v["state"] {
		case "delivered":
			candidate := field(v, "candidate")
			return status == 200 && wire02Candidate(candidate) && candidate["execution_generation"] == generation
		case "pending":
			return status == 202
		case "failed", "rejected":
			return status >= 400
		}
		return false
	}
	if status != 200 {
		return false
	}
	seen := map[string]bool{}
	attempts := array(v["attempts"])
	for _, raw := range attempts {
		a := object(raw)
		id := str(a["attempt_id"])
		if seen[id] || a["execution_generation"] != generation || !usageIdentity(field(a, "usage"), a["attempt_id"]) {
			return false
		}
		seen[id] = true
	}
	if has(v, "terminal_attempt_id") && !seen[str(v["terminal_attempt_id"])] {
		return false
	}
	if v["candidate_access"] == "present" {
		candidate := field(v, "candidate")
		if candidate["execution_generation"] != generation || !wire02Candidate(candidate) {
			return false
		}
		found := false
		for _, raw := range attempts {
			a := object(raw)
			left, right := field(a, "usage"), field(candidate, "usage")
			found = found || (a["attempt_id"] == candidate["attempt_id"] && left["state"] == right["state"] && (left["state"] != "available" || field(left, "revision")["revision"] == field(right, "revision")["revision"]))
		}
		if !found {
			return false
		}
	}
	return true
}
