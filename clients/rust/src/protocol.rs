use crate::schema::*;
use crate::{Error, Value};
use num_bigint::BigInt;
use std::collections::HashSet;

pub(crate) const SELECTOR: [&str; 4] = ["task_id", "step_id", "step_revision", "execution_generation"];
pub(crate) fn matching_handle<'a>(value: &'a Value, selector: Option<&Value>, version: &str) -> Option<&'a Value> {
    let selector = selector?; let handle = at(value, "handle");
    if !named(handle, version, if version == "0.3" { "Handle" } else { "SubmissionHandle" }) { return None; }
    let matches = if has(selector, "submission_id") { at(handle, "submission_id") == at(selector, "submission_id") } else { SELECTOR.iter().all(|key| at(at(handle, "work_key"), key) == at(selector, key)) };
    if matches { Some(handle) } else { None }
}
pub(crate) fn bad(status: u16, selector: Option<&Value>, handle: Option<&Value>) -> Error {
    let mut error = Error::new("INTERNAL_UNAVAILABLE", Some(status), "query_first", selector);
    error.handle = handle.cloned(); error.work_key = handle.map(|h| at(h, "work_key").clone()); error
}
pub(crate) fn evidence(value: &Value, status: u16, selector: Option<&Value>, handle: Option<&Value>, envelope: &Value) -> Error {
    let mut error = Error::new(text(at(value, "code")), Some(status), text(at(value, "retry_guidance")), selector);
    error.correlation_id = at(value, "correlation_id").as_str().map(str::to_owned); error.handle = handle.cloned();
    error.work_key = handle.map(|h| at(h, "work_key").clone()); error.attempt_id = at(envelope, "attempt_id").as_str().map(str::to_owned);
    error.failure_stage = at(envelope, "failure_stage").as_str().map(str::to_owned); error
}
fn usage(value: &Value, attempt: &Value) -> bool {
    if !is(at(value, "state"), "available") { return true; } let r = at(value, "revision");
    at(r, "attempt_id") == attempt && (!has(r, "previous_revision") || number(at(r, "previous_revision")) < number(at(r, "revision")))
}
fn candidate(value: &Value) -> bool {
    if !usage(at(value, "usage"), at(value, "attempt_id")) { return false; }
    let mut blocks = HashSet::new(); let mut calls = HashSet::new(); let mut tool = false;
    for block in items(at(value, "output_blocks")) {
        if !blocks.insert(text(at(block, "block_id"))) { return false; }
        if is(at(block, "kind"), "tool_call") { tool = true; if !calls.insert(text(at(block, "call_id"))) { return false; } }
    }
    !is(at(value, "finish_reason"), "tool_calls") || tool
}
pub(crate) fn wire02(value: &Value, status: u16, kind: &str) -> bool {
    let name = match kind { "submit" => "SubmitReply", "status" => "StatusSnapshot", _ => "CapabilityResponse" };
    if !named(value, "0.2", name) { return false; }
    if kind == "capabilities" { return status == 200 && !items(at(value, "supported_features")).iter().any(|feature| items(at(value, "disabled_features")).contains(feature)); }
    let generation = at(at(at(value, "handle"), "work_key"), "execution_generation");
    if kind == "submit" { return match text(at(value, "state")) {
        "delivered" => status == 200 && candidate(at(value, "candidate")) && at(at(value, "candidate"), "execution_generation") == generation,
        "pending" => status == 202, "failed" | "rejected" => status >= 400, _ => false,
    }; }
    if status != 200 { return false; }
    let attempts = items(at(value, "attempts")); let mut seen = HashSet::new();
    for attempt in attempts {
        if !seen.insert(text(at(attempt, "attempt_id"))) || at(attempt, "execution_generation") != generation || !usage(at(attempt, "usage"), at(attempt, "attempt_id")) { return false; }
    }
    if has(value, "terminal_attempt_id") && !seen.contains(text(at(value, "terminal_attempt_id"))) { return false; }
    if is(at(value, "candidate_access"), "present") {
        let result = at(value, "candidate"); if !candidate(result) || at(result, "execution_generation") != generation { return false; }
        return attempts.iter().any(|attempt| {
            let a = at(attempt, "usage"); let b = at(result, "usage");
            at(attempt, "attempt_id") == at(result, "attempt_id") && at(a, "state") == at(b, "state") && (!is(at(a, "state"), "available") || at(at(a, "revision"), "revision") == at(at(b, "revision"), "revision"))
        });
    }
    true
}
#[derive(Clone)]
struct ExactDecimal { coefficient: BigInt, exponent: i32 }
impl ExactDecimal {
    fn compare(&self, other: &Self) -> std::cmp::Ordering {
        let exponent = self.exponent.min(other.exponent);
        (&self.coefficient * BigInt::from(10).pow((self.exponent - exponent) as u32)).cmp(&(&other.coefficient * BigInt::from(10).pow((other.exponent - exponent) as u32)))
    }
    fn integer(value: i64) -> Self { Self { coefficient: value.into(), exponent: 0 } }
}
fn decimal(value: &Value, score: bool) -> Option<ExactDecimal> {
    let s = value.as_str()?;
    if !pattern(s, r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$") { return None; }
    let lower = s.to_ascii_lowercase(); let mut parts = lower.split('e'); let mantissa = parts.next()?;
    let mut exponent: i32 = parts.next().map(str::parse).transpose().ok()?.unwrap_or(0);
    let raw_digits = mantissa.replace('-', "").replace('.', ""); let digits = raw_digits.trim_start_matches('0');
    if digits.len() > 17 || exponent.abs() > 100 || digits.is_empty() && s.starts_with('-') { return None; }
    let mut coefficient = BigInt::parse_bytes(if digits.is_empty() { b"0" } else { digits.as_bytes() }, 10)?;
    if s.starts_with('-') { coefficient = -coefficient; }
    if let Some(dot) = mantissa.find('.') { exponent -= (mantissa.len() - dot - 1) as i32; }
    let result = ExactDecimal { coefficient, exponent };
    if result.compare(&ExactDecimal::integer(-1000000)).is_lt() || result.compare(&ExactDecimal::integer(1000000)).is_gt() || score && (result.compare(&ExactDecimal::integer(0)).is_lt() || result.compare(&ExactDecimal::integer(1)).is_gt()) { return None; }
    Some(result)
}
fn result_valid(value: &Value, attempt: &Value, request: Option<&Value>) -> bool {
    if !named(value, "0.3", "Result") || at(value, "attempt_id") != attempt || request.is_some_and(|r| at(value, "operation") != at(r, "operation")) { return false; }
    if is(at(at(value, "operation"), "type"), "embedding.create") {
        let vectors = items(at(value, "vectors"));
        for (i, vector) in vectors.iter().enumerate() {
            if number(at(vector, "input_index")) != i as i64 || items(at(vector, "values")).len() as i64 != number(at(value, "dimensions")) || items(at(vector, "values")).iter().any(|v| decimal(v, false).is_none()) { return false; }
        }
        let Some(request) = request else { return true; }; let input = at(request, "input"); let profile = at(input, "profile"); let list = items(at(input, "items"));
        return ["profile_id", "model_ref", "dimensions"].iter().all(|key| at(value, key) == at(profile, key)) && vectors.len() == list.len() && vectors.iter().zip(list).all(|(vector, item)| at(vector, "item_id") == at(item, "item_id"));
    }
    let ranking = items(at(value, "results")); let mut seen = HashSet::new(); let mut previous: Option<ExactDecimal> = None; let mut previous_index = -1;
    for (i, item) in ranking.iter().enumerate() {
        let Some(score) = decimal(at(item, "score"), true) else { return false; }; let index = number(at(item, "input_index"));
        if number(at(item, "rank")) != i as i64 + 1 || !seen.insert(text(at(item, "candidate_id"))) || previous.as_ref().is_some_and(|p| p.compare(&score).is_lt() || p.compare(&score).is_eq() && previous_index > index) { return false; }
        previous = Some(score); previous_index = index;
        if let Some(request) = request { let candidates = items(at(at(request, "input"), "candidates")); if index < 0 || index as usize >= candidates.len() || at(item, "candidate_id") != at(&candidates[index as usize], "candidate_id") { return false; } }
    }
    request.is_none_or(|r| at(value, "ranking_profile_id") == at(at(r, "input"), "ranking_profile_id") && ranking.len() as i64 == number(at(at(r, "input"), "top_k")))
}
pub(crate) fn successor_error(value: &Value, status: u16, kind: &str) -> bool {
    if !named(value, "0.3", "ErrorResponse") { return false; }
    let code = text(at(value, "code")); let guidance = text(at(value, "retry_guidance"));
    if status == 401 { return code == "POLICY_DENIED" && guidance == "never"; }
    let expected = match code {
        "UNSUPPORTED_VERSION" => 426, "MALFORMED_JSON" | "SCHEMA_INVALID" => 400, "LIMIT_EXCEEDED" => 413,
        "SEMANTIC_INVALID" | "CAPABILITY_UNSUPPORTED" => 422, "WORK_CONFLICT" | "WORK_VERSION_CONFLICT" | "PLAN_INVALID_OR_STALE" | "FDC_REJECTED" => 409,
        "NOT_FOUND_OR_FORBIDDEN" => 404, "POLICY_DENIED" | "FINANCIAL_AUTH_REQUIRED" => 403, "INTENT_PERSIST_FAILED" => 503, "RESULT_INVALID" | "USAGE_UNKNOWN" => 502, _ => 0,
    };
    if status != expected { return false; }
    match code { "INTENT_PERSIST_FAILED" => guidance == "query_first", "WORK_CONFLICT" | "WORK_VERSION_CONFLICT" => guidance == "never", "POLICY_DENIED" if guidance == "query_first" => kind == "submit", _ => true }
}
pub(crate) fn successor(value: &Value, status: u16, kind: &str, request: Option<&Value>) -> bool {
    if !named(value, "0.3", if kind == "submit" { "SubmitReply" } else { "StatusSnapshot" }) { return false; }
    if kind == "submit" {
        if is(at(value, "state"), "completed") { return status == 200 && result_valid(at(value, "result"), at(value, "attempt_id"), request); }
        if one(at(value, "state"), &["pending", "outcome_unknown"]) { return status == 202; }
        let code = text(at(at(value, "error"), "code"));
        let expected = if is(at(value, "failure_stage"), "before_send") { match code { "INTENT_PERSIST_FAILED" => 503, "FDC_REJECTED" | "PLAN_INVALID_OR_STALE" => 409, _ => 0 } } else if matches!(code, "RESULT_INVALID" | "USAGE_UNKNOWN") { 502 } else { 0 };
        return status == expected && successor_error(at(value, "error"), status, "submit");
    }
    let attempts = items(at(value, "attempts")); if status != 200 || attempts.len() != 1 { return false; }
    let attempt = &attempts[0]; let usage = at(attempt, "usage_revision");
    if has(attempt, "usage_revision") {
        if at(usage, "attempt_id") != at(attempt, "attempt_id") || at(attempt, "settlement_state") != at(usage, "cost_status") { return false; }
        if is(at(usage, "cost_status"), "unknown") { if has(usage, "amount_decimal") { return false; } }
        else {
            let Some(component) = items(at(usage, "components")).first() else { return false; };
            if !is(at(component, "presence"), "known") || !is(at(component, "evidence"), "reported") || !positive(at(component, "quantity")) || !has(usage, "amount_decimal") { return false; }
        }
    } else if !is(at(attempt, "settlement_state"), "pending") { return false; }
    if has(attempt, "result") && !result_valid(at(attempt, "result"), at(attempt, "attempt_id"), None) { return false; }
    match text(at(value, "submission_state")) {
        "completed" => is(at(attempt, "delivery_state"), "valid") && (is(at(value, "candidate_access"), "present") && has(attempt, "result") || is(at(value, "candidate_access"), "expired") && !has(attempt, "result")),
        "failed" => is(at(value, "candidate_access"), "unavailable_due_failure") && has(attempt, "failure") && !has(attempt, "result") && one(at(attempt, "delivery_state"), &["invalid", "pending"]),
        "unknown" => is(at(value, "candidate_access"), "unknown_outcome") && is(at(attempt, "dispatch_state"), "possible_send") && is(at(attempt, "delivery_state"), "unknown") && !has(attempt, "result"),
        _ => is(at(value, "candidate_access"), "not_yet_available") && is(at(attempt, "delivery_state"), "pending") && !has(attempt, "result"),
    }
}
