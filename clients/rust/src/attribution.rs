use crate::json::snapshot;
use crate::protocol;
use crate::schema::*;
use crate::transport::escape;
use crate::{Client, Error, Result, Value};
use std::collections::BTreeMap;

impl Client {
    pub fn start_run(&self, value: &Value) -> Result<Value> {
        let body = snapshot(value)?;
        let extras: &[&str] = match text(at(&body, "mode")) {
            "direct_human" => &[], "autonomous_agent" => &["agent_id", "agent_version"],
            "user_delegated_agent" => &["agent_id", "agent_version", "initiating_user_id"],
            "nested_agent" => &["agent_id", "agent_version", "parent_run_id"], _ => return Err(Error::invalid()),
        };
        let mut required = vec!["version", "run_id", "task_id", "task_class", "evaluation_ref", "mode"]; required.extend_from_slice(extras);
        if !keys(&body, &required, &[]) || !is(at(&body, "version"), "1") || !ids(&body, &["run_id", "task_id", "task_class", "evaluation_ref"]) || !ids(&body, extras) { return Err(Error::invalid()); }
        self.attribution("POST", "/v1/attribution-runs", Some(&body), false, text(at(&body, "run_id")))
    }
    pub fn get_run(&self, run_id: &str) -> Result<Value> {
        if !id(&Value::from(run_id)) { return Err(Error::invalid()); }
        self.attribution("GET", &format!("/v1/attribution-runs/{}", escape(run_id)), None, false, run_id)
    }
    pub fn report_outcome(&self, value: &Value) -> Result<Value> {
        let body = snapshot(value)?; let mut required = vec!["version", "event_id", "run_id", "kind", "subject_revision", "verdict", "evaluator_version", "evidence_ref"];
        let mut valid = is(at(&body, "version"), "1") && ids(&body, &["event_id", "run_id", "evaluator_version", "evidence_ref"]) && positive(at(&body, "subject_revision"));
        match text(at(&body, "kind")) {
            "task_outcome" => valid &= one(at(&body, "verdict"), &["accepted", "rejected", "abandoned"]),
            "step_evaluation" => { required.extend_from_slice(&["step_id", "step_revision", "execution_generation"]); valid &= ids(&body, &["step_id", "execution_generation"]) && positive(at(&body, "step_revision")) && one(at(&body, "verdict"), &["correct", "incorrect", "undetermined"]); }
            _ => valid = false,
        }
        if !valid || !keys(&body, &required, &[]) { return Err(Error::invalid()); }
        self.attribution("POST", "/v1/outcomes", Some(&body), true, text(at(&body, "event_id")))
    }
    pub fn get_outcome_receipt(&self, event_id: &str) -> Result<Value> {
        if !id(&Value::from(event_id)) { return Err(Error::invalid()); }
        self.attribution("GET", &format!("/v1/outcomes/{}", escape(event_id)), None, true, event_id)
    }
    fn attribution(&self, method: &str, path: &str, body: Option<&Value>, receipt: bool, expected_id: &str) -> Result<Value> {
        let (value, status) = self.connection.request(method, path, "EzLLMRouter-Contract-Version", "0.2", body, BTreeMap::new(), 1024 * 1024, None)?;
        if named(&value, "0.2", "ErrorResponse") && status >= 400 { return Err(protocol::evidence(at(&value, "error"), status, None, None, &value)); }
        let (version, key, id_key) = if receipt { ("outcome_version", "receipt", "event_id") } else { ("attribution_version", "run", "run_id") };
        let item = at(&value, key); let mut valid = keys(&value, &["contract_version", version, key], &[]) && is(at(&value, version), "1") && (status == 200 || receipt && status == 201) && is(at(item, id_key), expected_id);
        if receipt {
            valid &= keys(item, &["version", "event_id", "run_id", "kind", "subject_revision", "recorded_at", "event_digest"], &[]) && is(at(item, "version"), "1") && ids(item, &["event_id", "run_id", "event_digest"]) && positive(at(item, "subject_revision")) && utc(at(item, "recorded_at")) && one(at(item, "kind"), &["task_outcome", "step_evaluation"]);
        } else {
            valid &= keys(item, &["run_id", "principal_id", "charging_owner_id", "initiating_user_id", "agent_id", "agent_version", "parent_run_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "mode", "created_at", "status", "request_digest"], &["terminal_at"])
                && ids(item, &["run_id", "principal_id", "charging_owner_id", "root_run_id", "task_id", "task_class", "evaluation_ref", "request_digest"]) && utc(at(item, "created_at")) && (!has(item, "terminal_at") || utc(at(item, "terminal_at")))
                && one(at(item, "mode"), &["direct_human", "autonomous_agent", "user_delegated_agent", "nested_agent"]) && one(at(item, "status"), &["running", "accepted", "rejected", "abandoned"])
                && ["initiating_user_id", "agent_id", "agent_version", "parent_run_id"].iter().all(|key| at(item, key).is_null() || id(at(item, key)));
        }
        if !valid { return Err(protocol::bad(status, None, None)); } Ok(item.clone())
    }
}
