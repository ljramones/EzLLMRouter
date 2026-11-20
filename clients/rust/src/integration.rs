use crate::json::{digest, snapshot};
use crate::schema::*;
use crate::transport::{escape, Connection, Options};
use crate::{json, Error, Result, Value};
use std::collections::{BTreeMap, HashSet};

/// External accounting v1/v2/v3. This client never executes model work.
pub struct IntegrationClient { connection: Connection, version: String, path: String }
impl IntegrationClient {
    pub fn new(origin: &str, token: &str, version: &str) -> Result<Self> { Self::with_options(origin, token, version, Options::default()) }
    pub fn with_options(origin: &str, token: &str, version: &str, options: Options) -> Result<Self> {
        if !matches!(version, "1" | "2" | "3") { return Err(Error::new("UNSUPPORTED_VERSION", None, "never", None)); }
        Ok(Self { connection: Connection::new(origin, token, options)?, version: version.into(), path: format!("/integration/v{version}") })
    }
    pub fn close(&self) { self.connection.close(); }
    pub fn version(&self) -> &str { &self.version }
    fn request(&self, method: &str, endpoint: &str, body: Option<&Value>, expected: &[u16]) -> Result<Value> {
        let (value, status) = self.connection.request(method, &(self.path.clone() + endpoint), "EzLLMRouter-Integration-Version", &self.version, body, BTreeMap::new(), 16 * 1024 * 1024, None)?;
        if status >= 400 {
            let evidence = at(&value, "error"); let code = text(at(evidence, "code")); let guidance = text(at(evidence, "retry_guidance"));
            if code.is_empty() { return Err(Error::new("TRANSPORT_OUTCOME_UNKNOWN", Some(status), "query_first", None)); }
            return Err(Error::new(code, Some(status), if matches!(guidance, "never" | "query_first" | "orchestrator_decision") { guidance } else if status >= 500 { "query_first" } else { "never" }, None));
        }
        if !expected.contains(&status) { return Err(Error::new("PROTOCOL_INVALID", Some(status), "query_first", None)); }
        Ok(value)
    }
    fn write(&self, endpoint: &str, shape: &str, body: &Value, expected: &[u16]) -> Result<Value> {
        let copy = snapshot(body)?; if !named(&copy, &self.version, shape) { return Err(Error::invalid()); }
        self.request("POST", endpoint, Some(&copy), expected)
    }
    pub fn create_dataset(&self, body: &Value) -> Result<Value> { self.write("/datasets", "dataset", body, &[200, 201]) }
    pub fn register_account(&self, body: &Value) -> Result<Value> { self.write("/accounts", "account", body, &[200, 201]) }
    pub fn set_account_state(&self, account_id: &str, body: &Value) -> Result<Value> {
        if !id(&Value::from(account_id)) { return Err(Error::invalid()); }
        self.write(&format!("/accounts/{}/state", escape(account_id)), "account_state", body, &[200])
    }
    pub fn set_account_permissions(&self, account_id: &str, body: &Value) -> Result<Value> {
        if self.version != "3" || !id(&Value::from(account_id)) { return Err(Error::invalid()); }
        self.write(&format!("/accounts/{}/permissions", escape(account_id)), "account_permissions", body, &[200])
    }
    pub fn submit_observation(&self, event: &Value) -> Result<Value> {
        let copy = snapshot(event)?; if !event_valid(&copy, &self.version) { return Err(Error::invalid()); }
        let reply = self.request("POST", "/events", Some(&copy), &[200, 201])?;
        if !receipt(&reply, text(at(&copy, "dataset_id")), text(at(&copy, "event_id"))) || at(&reply, "kind") != at(&copy, "kind") || !is(at(&reply, "event_digest"), &digest(&copy)?) { return Err(bad()); }
        Ok(reply)
    }
    pub fn recover_receipt(&self, dataset_id: &str, event_id: &str) -> Result<Value> {
        if ![dataset_id, event_id].iter().all(|s| id(&Value::from(*s))) { return Err(Error::invalid()); }
        let reply = self.request("GET", &format!("/events/{}/receipt?dataset_id={}", escape(event_id), escape(dataset_id)), None, &[200])?;
        if !receipt(&reply, dataset_id, event_id) { return Err(bad()); } Ok(reply)
    }
    pub fn eligibility(&self, dataset_id: &str, account_id: &str, model_id: &str) -> Result<Value> {
        if ![dataset_id, account_id, model_id].iter().all(|s| id(&Value::from(*s))) { return Err(Error::invalid()); }
        if self.version == "3" { return self.operation_eligibility(dataset_id, account_id, &json!({"operation_family":"generation","capability":"generation","selection_kind":"known_model","model_id":model_id})); }
        let reply = self.request("GET", &format!("/accounts/{}/eligibility?dataset_id={}&model_id={}", escape(account_id), escape(dataset_id), escape(model_id)), None, &[200])?;
        if !eligibility_valid(&reply, dataset_id, account_id, false) || !is(at(&reply, "model_id"), model_id) || self.version == "2" && !digest_valid(&reply)? { return Err(bad()); } Ok(reply)
    }
    pub fn operation_eligibility(&self, dataset_id: &str, account_id: &str, selector: &Value) -> Result<Value> {
        let copy = snapshot(selector)?;
        if self.version != "3" || ![dataset_id, account_id].iter().all(|s| id(&Value::from(*s))) || !named(at(&copy, "operation_family"), "3", "operation_family") || !one(at(&copy, "selection_kind"), &["known_model", "provider_selected", "not_applicable"]) || !selection(&copy, "model_id") || has(&copy, "model_id") && !id(at(&copy, "model_id")) || !is(at(&copy, "selection_kind"), "known_model") && !one(at(&copy, "operation_family"), &["speech_input", "speech_output"]) { return Err(Error::invalid()); }
        let mut query = format!("?dataset_id={}", escape(dataset_id));
        for key in ["operation_family", "capability", "selection_kind", "model_id"] { if has(&copy, key) { query += &format!("&{key}={}", escape(text(at(&copy, key)))); } }
        let reply = self.request("GET", &format!("/accounts/{}/eligibility{query}", escape(account_id)), None, &[200])?;
        if !eligibility_valid(&reply, dataset_id, account_id, true) || !ids(&reply, &["provider_id", "credential_ref"]) || !digest_valid(&reply)? || ["operation_family", "capability", "selection_kind", "model_id"].iter().any(|key| at(&reply, key) != at(&copy, key)) { return Err(bad()); } Ok(reply)
    }
    pub fn report(&self, dataset_id: &str) -> Result<Value> {
        if !id(&Value::from(dataset_id)) { return Err(Error::invalid()); }
        self.request("GET", &format!("/reports/usage?dataset_id={}", escape(dataset_id)), None, &[200])
    }
    pub fn submit_snapshot(&self, value: &Value) -> Result<Value> {
        let copy = snapshot(value)?; if !snapshot_valid(&copy, &self.version) { return Err(Error::invalid()); }
        let reply = self.request("POST", "/snapshots", Some(&copy), &[200, 201])?;
        if at(&reply, "snapshot_id") != at(&copy, "snapshot_id") || !is(at(&reply, "snapshot_digest"), &digest(&copy)?) { return Err(bad()); } Ok(reply)
    }
    pub fn snapshot(&self, dataset_id: &str, snapshot_id: &str) -> Result<Value> {
        if self.version == "1" || ![dataset_id, snapshot_id].iter().all(|s| id(&Value::from(*s))) { return Err(Error::invalid()); }
        self.request("GET", &format!("/snapshots/{}?dataset_id={}", escape(snapshot_id), escape(dataset_id)), None, &[200])
    }
    pub fn export_dataset(&self, dataset_id: &str) -> Result<Value> {
        if self.version == "1" || !id(&Value::from(dataset_id)) { return Err(Error::invalid()); }
        self.request("GET", &format!("/reports/dataset?dataset_id={}", escape(dataset_id)), None, &[200])
    }
}
fn bad() -> Error { Error::new("PROTOCOL_INVALID", None, "query_first", None) }
fn zero(value: &Value) -> bool { text(value).trim_matches(|c| c == '0' || c == '.').is_empty() }
fn unique_units(value: &Value) -> bool { let mut seen = HashSet::new(); items(value).iter().all(|unit| seen.insert(text(at(unit, "unit")))) }
fn evidence(value: &Value) -> bool { one(at(value, "status"), &["verified", "stale", "denied"]) == has(value, "eligibility_id") }
fn capability(family: &Value) -> &str { match text(family) { "speech_input" => "transcription", "speech_output" => "synthesis", other => other } }
fn selection(value: &Value, key: &str) -> bool { is(at(value, "selection_kind"), "known_model") == has(value, key) && text(at(value, "capability")) == capability(at(value, "operation_family")) }
fn event_valid(value: &Value, version: &str) -> bool {
    if !named(value, version, "event") || !is(at(value, "integration_version"), version) { return false; }
    let kind = text(at(value, "kind"));
    if matches!(kind, "activity" | "attempt_started") && ((at(value, "root_run_id") == at(value, "run_id")) == has(value, "parent_run_id") || at(value, "parent_run_id") == at(value, "run_id")) { return false; }
    if version != "1" {
        if kind == "activity" && is(at(value, "activity_kind"), "outcome") && !has(value, "outcome") { return false; }
        if kind == "attempt_started" && (is(at(value, "model_identity_state"), "known") != has(value, "model_id") || one(at(value, "attempt_role"), &["retry", "fallback"]) != has(value, "predecessor_attempt_id")) { return false; }
        if kind == "decision" && (!evidence(at(value, "eligibility_evidence")) || version == "3" && !selection(value, "selected_model_id")) { return false; }
        if kind == "usage" {
            let units = is(at(value, "usage_state"), "known"); let cost = is(at(value, "cost_state"), "known");
            if !unique_units(at(value, "native_units")) || units != (has(value, "native_units") && has(value, "usage_provenance")) || !units && (has(value, "native_units") || has(value, "usage_provenance")) { return false; }
            let fields = ["currency", "amount_decimal", "cost_basis", "price_ref", "price_version"];
            if cost != fields.iter().all(|key| has(value, key)) || !cost && (fields.iter().any(|key| has(value, key)) || has(value, "zero_basis")) || cost && zero(at(value, "amount_decimal")) != has(value, "zero_basis") { return false; }
        }
    } else if kind == "usage" && is(at(value, "usage_state"), "known") && (!unique_units(at(value, "native_units")) || zero(at(value, "amount_decimal")) != has(value, "zero_basis")) { return false; }
    true
}
fn snapshot_valid(value: &Value, version: &str) -> bool {
    if version == "1" || !is(at(value, "integration_version"), version) || !named(value, version, "snapshot") { return false; }
    let (key, other) = if is(at(value, "snapshot_kind"), "feature") { ("features", "selected_action") } else { ("selected_action", "features") };
    if is(at(value, "status"), "captured") != has(value, key) || has(value, other) || text(at(value, "source_at")) > text(at(value, "available_at")) || text(at(value, "available_at")) > text(at(value, "retention_until")) || has(value, "source_expires_at") && text(at(value, "source_expires_at")) < text(at(value, "retention_until")) { return false; }
    let action = at(value, "selected_action");
    !has(value, "selected_action") || evidence(at(action, "eligibility_evidence")) && (version != "3" || selection(action, "selected_model_id"))
}
fn receipt(value: &Value, dataset_id: &str, event_id: &str) -> bool {
    is(at(value, "dataset_id"), dataset_id) && is(at(value, "event_id"), event_id) && one(at(value, "kind"), &["activity", "attempt_started", "decision", "result", "usage", "lineage", "account_resolution"]) && pattern(text(at(value, "event_digest")), "^sha256:[0-9a-f]{64}$") && one(at(value, "membership_at_receipt"), &["included", "excluded_before_activation", "pending_start"])
}
fn eligibility_valid(value: &Value, dataset_id: &str, account_id: &str, operation: bool) -> bool {
    is(at(value, "dataset_id"), dataset_id) && is(at(value, "account_id"), account_id) && positive(at(value, "account_revision")) && at(value, "usable").is_boolean()
        && (one(at(value, "reason"), &["usable", "account_disabled", "model_not_permitted"]) || operation && is(at(value, "reason"), "operation_not_permitted"))
        && at(value, "usable").as_bool() == Some(is(at(value, "reason"), "usable"))
}
fn digest_valid(value: &Value) -> Result<bool> {
    let mut signed = value.clone(); if let Some(map) = signed.as_object_mut() { map.remove("eligibility_digest"); }
    Ok(id(at(value, "eligibility_id")) && utc(at(value, "evaluated_at")) && is(at(value, "eligibility_digest"), &digest(&signed)?))
}
