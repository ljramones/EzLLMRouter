"use strict";

const VERSION = "0.2";
const successor = require("./successor.cjs");
const {IntegrationClient, IntegrationClientError} = require("./integration.cjs");
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/;
const FEATURES = new Set(["text", "tools", "document_text", "background", "nested", "streaming",
  "realtime_voice", "binary_multimodal", "responses_web_search", "provider_managed_state"]);
const ERROR_CODES = new Set(["UNSUPPORTED_VERSION", "AUTHENTICATION_FAILED", "MALFORMED_JSON", "SCHEMA_INVALID",
  "LIMIT_EXCEEDED", "SEMANTIC_INVALID", "SOURCE_INVALID", "POLICY_DENIED", "FINANCIAL_AUTH_REQUIRED",
  "CAPABILITY_UNSUPPORTED", "NOT_FOUND_OR_FORBIDDEN", "WORK_CONFLICT", "EVENT_CONFLICT", "STALE_REVISION",
  "PLAN_INVALID_OR_STALE", "FDC_REJECTED", "INTENT_PERSIST_FAILED", "INTERNAL_UNAVAILABLE",
  "REMOTE_EXECUTION_FAILED", "CANDIDATE_UNUSABLE"]);
const object = x => x !== null && typeof x === "object" && !Array.isArray(x);
const keys = (x, required, optional = []) => object(x) && required.every(k => Object.hasOwn(x, k)) &&
  Object.keys(x).every(k => required.includes(k) || optional.includes(k));
const id = x => typeof x === "string" && ID.test(x);
const count = x => Number.isSafeInteger(x) && x > 0;
const safeCount = x => Number.isSafeInteger(x) && x >= 0;
function utc(x) {
  if (typeof x !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(x)) return false;
  const year = Number(x.slice(0, 4)), month = Number(x.slice(5, 7)), day = Number(x.slice(8, 10));
  const hour = Number(x.slice(11, 13)), minute = Number(x.slice(14, 16)), second = Number(x.slice(17, 19));
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1] &&
    hour <= 23 && minute <= 59 && second <= 59;
}
const uniqueFeatures = x => Array.isArray(x) && x.every(v => FEATURES.has(v)) && new Set(x).size === x.length;
function validSelector(x) {
  return keys(x, ["task_id", "step_id", "step_revision", "execution_generation"]) &&
    id(x.task_id) && id(x.step_id) && count(x.step_revision) && id(x.execution_generation);
}
function validHandle(x) {
  return keys(x, ["submission_id", "work_key"]) && id(x.submission_id) &&
    keys(x.work_key, ["principal_id", "task_id", "step_id", "step_revision", "execution_generation"]) &&
    id(x.work_key.principal_id) && validSelector({ task_id: x.work_key.task_id, step_id: x.work_key.step_id,
      step_revision: x.work_key.step_revision, execution_generation: x.work_key.execution_generation });
}
function validError(x) {
  return keys(x, ["code", "correlation_id", "retry_guidance"], ["safe_message"]) &&
    ERROR_CODES.has(x.code) && id(x.correlation_id) && ["never", "query_first", "orchestrator_decision"].includes(x.retry_guidance) &&
    (!Object.hasOwn(x, "safe_message") || typeof x.safe_message === "string");
}
function validKnowledge(x) {
  return x?.state === "known" ? keys(x, ["state", "count"]) && safeCount(x.count) :
    (x?.state === "unknown" || x?.state === "not_applicable") && keys(x, ["state"]);
}
function validLabels(x) {
  return keys(x, ["lineage_ids", "sensitivity", "restrictions"]) &&
    Array.isArray(x.lineage_ids) && x.lineage_ids.length > 0 && x.lineage_ids.every(id) &&
    new Set(x.lineage_ids).size === x.lineage_ids.length &&
    ["public", "internal", "confidential", "restricted"].includes(x.sensitivity) &&
    Array.isArray(x.restrictions) && x.restrictions.every(id) && new Set(x.restrictions).size === x.restrictions.length;
}
function validDestination(x) {
  return keys(x, ["configuration_ref", "service", "endpoint", "model", "model_version", "processing_region"],
    ["pool", "quantization"]) && Object.values(x).every(id);
}
function validCost(x) {
  if (!object(x) || !/^[A-Z]{3}$/.test(x.currency)) return false;
  const money = v => typeof v === "string" && /^(0|[1-9][0-9]*)(\.[0-9]{1,9})?$/.test(v);
  if (x.status === "unknown") return keys(x, ["status", "currency"]);
  if (["reported", "calculated", "reconciled"].includes(x.status))
    return keys(x, ["status", "currency", "amount_decimal", "source_ref"], ["zero_basis"]) &&
      money(x.amount_decimal) && id(x.source_ref) && (x.amount_decimal !== "0" ||
        ["provider_reported_free", "contract_free", "cache_hit", "invoice_reconciled"].includes(x.zero_basis));
  if (x.status === "estimated")
    return keys(x, ["status", "currency", "amount_decimal", "method_ref", "lower_bound_decimal", "upper_bound_decimal"]) &&
      money(x.amount_decimal) && money(x.lower_bound_decimal) && money(x.upper_bound_decimal) && id(x.method_ref);
  return false;
}
function validUsage(x) {
  if (!object(x)) return false;
  if (x.state === "not_recorded") return keys(x, ["state"]);
  if (x.state !== "available" || !keys(x, ["state", "revision"])) return false;
  const r = x.revision;
  if (!keys(r, ["attempt_id", "revision", "usage_observation", "normalized_usage", "usage_semantics_version",
    "price_version", "cost", "recorded_at"], ["previous_revision", "usage_estimate_method_ref", "processing_region"]) ||
    !id(r.attempt_id) || !count(r.revision) || !["unknown", "partial", "reported", "estimated", "reconciled"].includes(r.usage_observation) ||
    !id(r.usage_semantics_version) || !id(r.price_version) || !utc(r.recorded_at) ||
    (Object.hasOwn(r, "previous_revision") && (!count(r.previous_revision) || r.previous_revision >= r.revision)) ||
    (Object.hasOwn(r, "usage_estimate_method_ref") && !id(r.usage_estimate_method_ref)) ||
    (Object.hasOwn(r, "processing_region") && !id(r.processing_region))) return false;
  const n = r.normalized_usage;
  if (!keys(n, ["input_uncached", "input_cache_read", "input_cache_write", "output_text", "output_reasoning", "other_billable"]) ||
    !["input_uncached", "input_cache_read", "input_cache_write", "output_text", "output_reasoning"].every(k => validKnowledge(n[k])) ||
    !Array.isArray(n.other_billable) || !n.other_billable.every(o => keys(o, ["component", "unit", "knowledge"]) &&
      id(o.component) && id(o.unit) && validKnowledge(o.knowledge))) return false;
  return validCost(r.cost);
}
function validOutputBlock(b) {
  if (!object(b) || !id(b.block_id) || !validLabels(b.source_labels)) return false;
  if (b.kind === "assistant_text") return keys(b, ["block_id", "kind", "text", "source_labels"]) && typeof b.text === "string";
  if (b.kind === "tool_call") return keys(b, ["block_id", "kind", "call_id", "tool_name", "arguments", "source_labels"]) &&
    id(b.call_id) && b.tool_name === "lookup" && keys(b.arguments, ["key"]) && typeof b.arguments.key === "string";
  return false;
}
function validCandidate(x) {
  if (!keys(x, ["candidate_id", "attempt_id", "execution_generation", "served_destination",
    "output_blocks", "finish_reason", "structural_status", "observed_at", "usage"],
    ["provider_request_id", "structural_code"])) return false;
  return id(x.candidate_id) && id(x.attempt_id) && id(x.execution_generation) &&
    validDestination(x.served_destination) && Array.isArray(x.output_blocks) && x.output_blocks.length > 0 &&
    x.output_blocks.every(validOutputBlock) &&
    new Set(x.output_blocks.map(b => b.block_id)).size === x.output_blocks.length &&
    new Set(x.output_blocks.filter(b => b.kind === "tool_call").map(b => b.call_id)).size ===
      x.output_blocks.filter(b => b.kind === "tool_call").length &&
    (x.finish_reason !== "tool_calls" || x.output_blocks.some(b => b.kind === "tool_call")) &&
    ["stop", "tool_calls", "length", "provider_other"].includes(x.finish_reason) &&
    ["pass", "fail", "not_checked"].includes(x.structural_status) && utc(x.observed_at) && validUsage(x.usage);
}
function validAttempt(a) {
  return keys(a, ["attempt_id", "execution_generation", "attempt_revision", "dispatch_state", "delivery_state",
    "cancel_state", "settlement_state", "generation_state", "usage"], ["provider_request_id", "cancel_evidence_ref"]) &&
    id(a.attempt_id) && id(a.execution_generation) && count(a.attempt_revision) &&
    ["prepared", "intent_persisted", "transmitted", "response_observed", "outcome_unknown", "rejected", "failed_before_dispatch"].includes(a.dispatch_state) &&
    ["none", "candidate_delivered"].includes(a.delivery_state) && ["none", "requested", "confirmed", "unresolved"].includes(a.cancel_state) &&
    ["unsettled", "provisional", "final"].includes(a.settlement_state) && ["current", "superseded"].includes(a.generation_state) &&
    validUsage(a.usage) && (a.cancel_state !== "confirmed" || id(a.cancel_evidence_ref));
}
function usageCorresponds(a, b) {
  return a.state === b.state && (a.state !== "available" ||
    (a.revision.attempt_id === b.revision.attempt_id && a.revision.revision === b.revision.revision));
}
function handleMatchesSelector(handle, selector) {
  if (!validHandle(handle)) return false;
  if (!selector) return true;
  if (Object.hasOwn(selector, "submission_id")) return handle.submission_id === selector.submission_id;
  return ["task_id", "step_id", "step_revision", "execution_generation"].every(
    k => handle.work_key[k] === selector[k]);
}
function validReply(x, status) {
  if (!object(x) || x.contract_version !== VERSION) return false;
  if (x.state === "delivered") return status === 200 && keys(x, ["contract_version", "state", "handle", "candidate"]) &&
    validHandle(x.handle) && validCandidate(x.candidate) && x.candidate.execution_generation === x.handle.work_key.execution_generation &&
    (x.candidate.usage.state !== "available" || x.candidate.usage.revision.attempt_id === x.candidate.attempt_id);
  if (x.state === "pending") return status === 202 && keys(x, ["contract_version", "state", "handle", "pending_result_policy"]) &&
    validHandle(x.handle) && ["pollable_if_retained", "metadata_only_no_store"].includes(x.pending_result_policy);
  if (x.state === "failed") return status >= 400 && keys(x, ["contract_version", "state", "handle", "error", "attempt_id", "failure_stage"]) &&
    validHandle(x.handle) && validError(x.error) && id(x.attempt_id) &&
    ["before_transmit", "after_transmit"].includes(x.failure_stage);
  if (x.state === "rejected") return status >= 400 && keys(x, ["contract_version", "state", "selector", "error"]) &&
    validSelector(x.selector) && validError(x.error);
  return false;
}
function validStatus(x, status) {
  return status === 200 && keys(x, ["contract_version", "handle", "status_revision", "submission_state",
    "attempts", "candidate_access", "updated_at"], ["candidate", "terminal_failure", "terminal_attempt_id", "result_unavailable_reason"]) &&
    x.contract_version === VERSION && validHandle(x.handle) && count(x.status_revision) &&
    ["received", "admitted", "no_route", "completed", "outcome_unknown", "failed_before_transmit", "failed_after_transmit"].includes(x.submission_state) &&
    Array.isArray(x.attempts) && x.attempts.every(a => validAttempt(a) &&
      a.execution_generation === x.handle.work_key.execution_generation &&
      (a.usage.state !== "available" || a.usage.revision.attempt_id === a.attempt_id)) &&
    new Set(x.attempts.map(a => a.attempt_id)).size === x.attempts.length &&
    ["present", "not_retained", "expired", "not_yet_available", "unavailable_due_failure"].includes(x.candidate_access) &&
    utc(x.updated_at) && (x.candidate_access === "present" ?
      validCandidate(x.candidate) && x.candidate.execution_generation === x.handle.work_key.execution_generation &&
      x.attempts.some(a => a.attempt_id === x.candidate.attempt_id &&
        usageCorresponds(a.usage, x.candidate.usage)) &&
      (x.candidate.usage.state !== "available" || x.candidate.usage.revision.attempt_id === x.candidate.attempt_id) :
      !Object.hasOwn(x, "candidate")) &&
    (!Object.hasOwn(x, "result_unavailable_reason") ||
      (x.result_unavailable_reason === "wait_expired_no_store" && x.submission_state === "completed" && x.candidate_access === "not_retained")) &&
    (["failed_before_transmit", "failed_after_transmit"].includes(x.submission_state) ?
      validError(x.terminal_failure) && id(x.terminal_attempt_id) &&
      x.attempts.some(a => a.attempt_id === x.terminal_attempt_id) :
      !Object.hasOwn(x, "terminal_failure") && !Object.hasOwn(x, "terminal_attempt_id"));
}
function validCapabilities(x, status) {
  return status === 200 && keys(x, ["contract_version", "profile", "supported_features", "disabled_features"]) &&
    x.contract_version === VERSION && x.profile === "initial_1a@1" && uniqueFeatures(x.supported_features) &&
    uniqueFeatures(x.disabled_features) && x.supported_features.every(f => !x.disabled_features.includes(f));
}

class EzLLMRouterError extends Error {
  constructor(code, httpStatus, retryGuidance, correlationId, details = {}) {
    super(code);
    this.name = "EzLLMRouterError";
    this.code = code;
    this.http_status = httpStatus;
    this.retry_guidance = retryGuidance;
    this.correlation_id = correlationId;
    Object.assign(this, details);
  }
}

function selectorFrom(request) {
  return {
    task_id: request.task_id,
    step_id: request.step_id,
    step_revision: request.step_revision,
    execution_generation: request.execution_generation,
  };
}

class EzLLMRouterClient {
  constructor({ baseUrl, token, fetchImpl = globalThis.fetch }) {
    let endpoint;
    try { endpoint = new URL(baseUrl); } catch { throw new TypeError("invalid service origin"); }
    if (typeof baseUrl !== "string" || !["http:", "https:"].includes(endpoint.protocol) ||
        endpoint.username || endpoint.password || endpoint.pathname !== "/" || endpoint.search || endpoint.hash ||
        typeof token !== "string" || !token || typeof fetchImpl !== "function") {
      throw new TypeError("baseUrl, token and fetch are required");
    }
    this.baseUrl = endpoint.origin;
    this.token = token;
    this.fetchImpl = fetchImpl;
  }

  async _request(method, path, body, extraHeaders = {}, workSelector, responseKind = "submit") {
    // Bind response matching and error recovery to the issued operation.
    workSelector = workSelector === undefined ? undefined : Object.freeze({ ...workSelector });
    const headers = { "EzLLMRouter-Contract-Version": VERSION, Authorization: `Bearer ${this.token}`,
      "Accept-Encoding": "identity", ...extraHeaders };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await this.fetchImpl(this.baseUrl + path, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body), redirect: "manual",
      });
    } catch (cause) {
      throw new EzLLMRouterError("TRANSPORT_OUTCOME_UNKNOWN", null, "query_first", null, { selector: workSelector, cause });
    }
    let value;
    try { value = await response.json(); } catch (cause) {
      throw new EzLLMRouterError("TRANSPORT_OUTCOME_UNKNOWN", response.status, "query_first", null, { selector: workSelector, cause });
    }
    if (value?.contract_version !== VERSION || response.headers.get("EzLLMRouter-Contract-Version") !== VERSION) {
      throw new EzLLMRouterError("UNSUPPORTED_VERSION", response.status, "never", value?.error?.correlation_id ?? null,
        { selector: workSelector, handle: validHandle(value?.handle) ? value.handle : undefined });
    }
    const valid = value?.error && !Object.hasOwn(value, "state") ?
      keys(value, ["contract_version", "error"]) && validError(value.error) && response.status >= 400 :
      responseKind === "submit" ? validReply(value, response.status) :
      responseKind === "status" ? validStatus(value, response.status) : validCapabilities(value, response.status);
    const corresponds = responseKind === "submit" ?
      (value?.state === "rejected" ? validSelector(value.selector) &&
        ["task_id", "step_id", "step_revision", "execution_generation"].every(k => value.selector[k] === workSelector[k]) :
        (!value?.handle || handleMatchesSelector(value.handle, workSelector))) :
      responseKind === "status" ? (!value?.handle || handleMatchesSelector(value.handle, workSelector)) : true;
    if (!valid || !corresponds) {
      throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null,
        { selector: workSelector, handle: validHandle(value?.handle) ? value.handle : undefined });
    }
    if (value.error || value.state === "failed" || value.state === "rejected") {
      const err = value.error ?? { code: "INTERNAL_UNAVAILABLE", retry_guidance: "query_first" };
      throw new EzLLMRouterError(err.code, response.status, err.retry_guidance, err.correlation_id,
        { handle: value.handle, attempt_id: value.attempt_id, failure_stage: value.failure_stage,
          work_key: value.handle?.work_key, selector: value.selector ?? workSelector, error: err });
    }
    if (!response.ok && response.status !== 202) {
      throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null,
        { selector: workSelector, handle: validHandle(value?.handle) ? value.handle : undefined });
    }
    return value;
  }

  async _submit(request, options, runId) {
    if (!request || typeof request !== "object" || Array.isArray(request)) throw new TypeError("request object required");
    const selected = selectorFrom(request);
    if (!validSelector(selected)) throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    let headers = {};
    if (options !== undefined) {
      if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(k => k !== "wait_ms")) {
        throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
      }
      if (Object.hasOwn(options, "wait_ms")) {
        const n = options.wait_ms;
        if (!Number.isInteger(n) || n < 0 || n > 30000) throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
        headers["EzLLMRouter-Wait-Ms"] = String(n);
      }
    }
    if (runId !== undefined) {
      if (!id(runId)) throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
      headers["EzLLMRouter-Attribution-Version"] = "1";
      headers["EzLLMRouter-Attribution-Run"] = runId;
    }
    return this._request("POST", "/v1/submissions", request, headers, selected);
  }

  submit(request, options) { return this._submit(request, options, undefined); }

  submitInRun(request, runId, options) { return this._submit(request, options, runId); }

  async _extension(method, path, body, kind) {
    const headers = { "EzLLMRouter-Contract-Version": VERSION, Authorization: `Bearer ${this.token}`,
      "Accept-Encoding": "identity" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response, value;
    try {
      response = await this.fetchImpl(this.baseUrl + path, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body), redirect: "manual",
      });
      value = await response.json();
    } catch (cause) {
      throw new EzLLMRouterError("TRANSPORT_OUTCOME_UNKNOWN", null, "query_first", null, { cause });
    }
    if (!object(value) || value.contract_version !== VERSION ||
        response.headers.get("EzLLMRouter-Contract-Version") !== VERSION)
      throw new EzLLMRouterError("UNSUPPORTED_VERSION", response.status, "never", null);
    if (keys(value, ["contract_version", "error"]) && validError(value.error) && response.status >= 400)
      throw new EzLLMRouterError(value.error.code, response.status, value.error.retry_guidance,
        value.error.correlation_id);
    const version = kind === "receipt" ? "outcome_version" : "attribution_version";
    const field = kind === "receipt" ? "receipt" : "run";
    if (!keys(value, ["contract_version", version, field]) || value[version] !== "1" ||
        !object(value[field]) || (kind === "receipt" ? ![200, 201].includes(response.status) : response.status !== 200))
      throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null);
    const item = value[field];
    if (kind === "receipt") {
      if (!keys(item, ["version", "event_id", "run_id", "kind", "subject_revision", "recorded_at", "event_digest"]) ||
          item.version !== "1" || !["event_id", "run_id", "event_digest"].every(k => id(item[k])) ||
          !count(item.subject_revision) || !utc(item.recorded_at) ||
          !["task_outcome", "step_evaluation"].includes(item.kind))
        throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null);
    } else if (!keys(item, ["run_id", "principal_id", "charging_owner_id", "initiating_user_id",
        "agent_id", "agent_version", "parent_run_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "mode",
        "created_at", "status", "request_digest"], ["terminal_at"]) ||
        !["run_id", "principal_id", "charging_owner_id", "root_run_id", "task_id", "task_class",
          "evaluation_ref", "request_digest"].every(k => id(item[k])) ||
        !["initiating_user_id", "agent_id", "agent_version", "parent_run_id"].every(
          k => item[k] === null || id(item[k])) ||
        !["direct_human", "autonomous_agent", "user_delegated_agent", "nested_agent"].includes(item.mode) ||
        !["running", "accepted", "rejected", "abandoned"].includes(item.status) ||
        !utc(item.created_at) || (Object.hasOwn(item, "terminal_at") && !utc(item.terminal_at)))
      throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null);
    return item;
  }

  startRun(run) {
    if (!object(run) || run.version !== "1" || !["run_id", "task_id", "task_class", "evaluation_ref"].every(k => id(run[k])) ||
        !keys(run, ["version", "run_id", "task_id", "task_class", "evaluation_ref", "mode"],
          ["agent_id", "agent_version", "initiating_user_id", "parent_run_id"]))
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    const expected = {direct_human: [], autonomous_agent: ["agent_id", "agent_version"],
      user_delegated_agent: ["agent_id", "agent_version", "initiating_user_id"],
      nested_agent: ["agent_id", "agent_version", "parent_run_id"]}[run.mode];
    if (!expected || expected.some(key => !id(run[key])) ||
        ["agent_id", "agent_version", "initiating_user_id", "parent_run_id"].some(
          key => Object.hasOwn(run, key) !== expected.includes(key)))
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    return this._extension("POST", "/v1/attribution-runs", run, "run");
  }

  getRun(runId) {
    if (!id(runId)) throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    return this._extension("GET", "/v1/attribution-runs/" + encodeURIComponent(runId), undefined, "run");
  }

  reportOutcome(event) {
    if (!object(event) || event.version !== "1" ||
        !["event_id", "run_id", "evaluator_version", "evidence_ref"].every(k => id(event[k])) ||
        !keys(event, ["version", "event_id", "run_id", "kind", "subject_revision", "verdict",
            "evaluator_version", "evidence_ref"], ["step_id", "step_revision", "execution_generation"]))
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    const step = event.kind === "step_evaluation";
    if (!count(event.subject_revision) ||
        (step ? (!id(event.step_id) || !count(event.step_revision) || !id(event.execution_generation) ||
          !["correct", "incorrect", "undetermined"].includes(event.verdict)) :
          (event.kind !== "task_outcome" || !["accepted", "rejected", "abandoned"].includes(event.verdict))) ||
        ["step_id", "step_revision", "execution_generation"].some(
          key => Object.hasOwn(event, key) !== step))
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    return this._extension("POST", "/v1/outcomes", event, "receipt");
  }

  getOutcomeReceipt(eventId) {
    if (!id(eventId)) throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    return this._extension("GET", "/v1/outcomes/" + encodeURIComponent(eventId), undefined, "receipt");
  }

  async getStatus(selector, { contractVersion = VERSION } = {}) {
    if (contractVersion === "0.3") return this.getSuccessorStatus(selector);
    if (contractVersion !== VERSION) throw new EzLLMRouterError("UNSUPPORTED_VERSION", null, "never", null);
    let path;
    if (keys(selector, ["submission_id"]) && id(selector.submission_id)) {
      path = "/v1/submissions/" + encodeURIComponent(selector.submission_id);
    } else if (validSelector(selector)) {
      path = "/v1/submissions/by-work/" + [selector.task_id, selector.step_id, selector.step_revision, selector.execution_generation].map(encodeURIComponent).join("/");
    } else {
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    }
    return this._request("GET", path, undefined, {}, selector, "status");
  }

  async _requestSuccessor(method, path, selector, body, waitMs, kind) {
    const headers = { "EzLLMRouter-Contract-Version": "0.3", Authorization: `Bearer ${this.token}`,
      "Accept-Encoding": "identity" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (waitMs !== undefined) headers["EzLLMRouter-Wait-Ms"] = String(waitMs);
    let response;
    try {
      response = await this.fetchImpl(this.baseUrl + path, { method, headers,
        body: body === undefined ? undefined : JSON.stringify(body), redirect: "manual" });
    } catch (cause) {
      throw new EzLLMRouterError("TRANSPORT_OUTCOME_UNKNOWN", null, "query_first", null, { selector, cause });
    }
    let value;
    try {
      const raw = Buffer.from(await response.arrayBuffer());
      value = successor.strictDecode(raw);
    } catch (cause) {
      throw new EzLLMRouterError("TRANSPORT_OUTCOME_UNKNOWN", response.status, "query_first", null, { selector, cause });
    }
    if (value?.contract_version !== "0.3" || response.headers.get("EzLLMRouter-Contract-Version") !== "0.3") {
      throw new EzLLMRouterError("UNSUPPORTED_VERSION", response.status, "never", null, { selector });
    }
    if (Object.hasOwn(value, "code")) {
      if (!successor.errorValid(value, response.status, kind)) {
        throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null, { selector });
      }
      throw new EzLLMRouterError(value.code, response.status, value.retry_guidance, value.correlation_id, { selector });
    }
    if (!successor.responseValid(value,kind === "submit" ? "SubmitReply" : "StatusSnapshot",
        response.status,selector,kind === "submit" ? body : undefined)) {
      throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null,
        { selector, handle: value?.handle, work_key: value?.handle?.work_key });
    }
    if (kind === "submit" && value.state === "failed") {
      throw new EzLLMRouterError(value.error.code, response.status, value.error.retry_guidance,
        value.error.correlation_id, { selector, handle: value.handle, work_key: value.handle.work_key,
          attempt_id: value.attempt_id,
          failure_stage: value.failure_stage, error: value.error });
    }
    if (response.status !== 200 && response.status !== 202) {
      throw new EzLLMRouterError("INTERNAL_UNAVAILABLE", response.status, "query_first", null, { selector });
    }
    return value;
  }

  _submitSuccessor(request, operationType, options = {}) {
    if (!successor.named(request, "SubmitRequest") || request.contract_version !== "0.3" ||
        request.operation.type !== operationType || request.operation.version !== 1 ||
        options === null || typeof options !== "object" || Array.isArray(options) ||
        Object.keys(options).some(key => key !== "wait_ms")) {
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    }
    const wait = options.wait_ms;
    if (wait !== undefined && (!Number.isInteger(wait) || wait < 0 || wait > 30000)) {
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    }
    const snapshot = structuredClone(request);
    const raw = JSON.stringify(snapshot);
    if (Buffer.byteLength(raw, "utf8") > 262144) throw new EzLLMRouterError("LIMIT_EXCEEDED", null, "never", null);
    const selector = structuredClone(request.work_selector);
    return this._requestSuccessor("POST", "/v1/submissions", selector, snapshot, wait, "submit");
  }

  submit_embedding(request, options) { return this._submitSuccessor(request, "embedding.create", options); }
  submit_rerank(request, options) { return this._submitSuccessor(request, "rerank", options); }
  submitEmbedding(request, options) { return this.submit_embedding(request, options); }
  submitRerank(request, options) { return this.submit_rerank(request, options); }

  getSuccessorStatus(selector) {
    if (!successor.named(selector, "StatusQuery")) {
      throw new EzLLMRouterError("SCHEMA_INVALID", null, "never", null);
    }
    const snapshot = structuredClone(selector);
    const selected = snapshot.work_selector ?? snapshot;
    const path = Object.hasOwn(snapshot, "submission_id") ?
      "/v1/submissions/" + encodeURIComponent(snapshot.submission_id) :
      "/v1/submissions/by-work/" + ["task_id", "step_id", "step_revision", "execution_generation"]
        .map(key => encodeURIComponent(selected[key])).join("/");
    return this._requestSuccessor("GET", path, selected, undefined, undefined, "status");
  }

  getCapabilities() { return this._request("GET", "/v1/capabilities", undefined, {}, undefined, "capabilities"); }
}

module.exports = Object.freeze({ EzLLMRouterClient, EzLLMRouterError, IntegrationClient, IntegrationClientError,
  contractVersion: VERSION });
