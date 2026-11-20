use crate::json::{canonical, snapshot};
use crate::protocol::{self, SELECTOR};
use crate::schema::{at, has, id, is, named, one, text};
use crate::transport::{escape, Connection, Options};
use crate::{Error, Result, Value};
use std::collections::BTreeMap;

/// Synchronous text/tools, embedding/rerank, attribution and outcome client.
pub struct Client { pub(crate) connection: Connection }
impl Client {
    pub fn new(origin: &str, token: &str) -> Result<Self> { Self::with_options(origin, token, Options::default()) }
    pub fn with_options(origin: &str, token: &str, options: Options) -> Result<Self> { Ok(Self { connection: Connection::new(origin, token, options)? }) }
    pub fn close(&self) { self.connection.close(); }
    pub fn submit(&self, request: &Value, wait_ms: Option<u32>) -> Result<Value> { self.submit_inner(request, None, wait_ms) }
    pub fn submit_in_run(&self, request: &Value, run_id: &str, wait_ms: Option<u32>) -> Result<Value> {
        if !id(&Value::from(run_id)) { return Err(Error::invalid()); }
        self.submit_inner(request, Some(run_id), wait_ms)
    }
    fn submit_inner(&self, request: &Value, run_id: Option<&str>, wait_ms: Option<u32>) -> Result<Value> {
        let body = snapshot(request)?;
        if !crate::schema::value_policy(&body, false, false) { return Err(Error::invalid()); }
        let selector = Value::Object(SELECTOR.iter().map(|key| ((*key).into(), at(&body, key).clone())).collect());
        if !named(&selector, "0.2", "WorkSelector") { return Err(Error::invalid()); }
        let mut headers = wait_headers(wait_ms)?;
        if let Some(run) = run_id { headers.insert("EzLLMRouter-Attribution-Version".into(), "1".into()); headers.insert("EzLLMRouter-Attribution-Run".into(), run.into()); }
        self.wire("POST", "/v1/submissions", "0.2", "submit", Some(&body), Some(&selector), headers)
    }
    pub fn get_status(&self, selector: &Value) -> Result<Value> { self.status(selector, "0.2") }
    pub fn get_successor_status(&self, selector: &Value) -> Result<Value> { self.status(selector, "0.3") }
    fn status(&self, selector: &Value, version: &str) -> Result<Value> {
        let selected = snapshot(selector)?;
        if version == "0.3" && !named(&selected, version, "StatusQuery") { return Err(Error::invalid()); }
        let work = if version == "0.3" && has(&selected, "work_selector") { at(&selected, "work_selector") } else { &selected };
        let path = if selected.as_object().is_some_and(|map| map.len() == 1) && id(at(&selected, "submission_id")) {
            "/v1/submissions/".to_owned() + &escape(text(at(&selected, "submission_id")))
        } else if named(work, version, "WorkSelector") {
            let parts: Vec<_> = SELECTOR.iter().map(|key| if *key == "step_revision" { at(work, key).to_string() } else { escape(text(at(work, key))) }).collect();
            "/v1/submissions/by-work/".to_owned() + &parts.join("/")
        } else { return Err(Error::invalid()); };
        self.wire("GET", &path, version, "status", None, Some(work), BTreeMap::new())
    }
    pub fn get_capabilities(&self) -> Result<Value> { self.wire("GET", "/v1/capabilities", "0.2", "capabilities", None, None, BTreeMap::new()) }
    pub fn submit_embedding(&self, request: &Value, wait_ms: Option<u32>) -> Result<Value> { self.successor(request, "embedding.create", wait_ms) }
    pub fn submit_rerank(&self, request: &Value, wait_ms: Option<u32>) -> Result<Value> { self.successor(request, "rerank", wait_ms) }
    fn successor(&self, request: &Value, operation: &str, wait_ms: Option<u32>) -> Result<Value> {
        let body = snapshot(request)?;
        if !named(&body, "0.3", "SubmitRequest") || !is(at(at(&body, "operation"), "type"), operation) { return Err(Error::invalid()); }
        if canonical(&body)?.len() > 262144 { return Err(Error::new("LIMIT_EXCEEDED", None, "never", None)); }
        self.wire("POST", "/v1/submissions", "0.3", "submit", Some(&body), Some(at(&body, "work_selector")), wait_headers(wait_ms)?)
    }
    #[allow(clippy::too_many_arguments)]
    fn wire(&self, method: &str, path: &str, version: &str, kind: &str, body: Option<&Value>, selector: Option<&Value>, headers: BTreeMap<String, String>) -> Result<Value> {
        let limit = if version == "0.3" { 16 * 1024 * 1024 } else { 1024 * 1024 };
        let (value, status) = self.connection.request(method, path, "EzLLMRouter-Contract-Version", version, body, headers, limit, selector)?;
        let handle = protocol::matching_handle(&value, selector, version);
        let envelope_error = if version == "0.3" { has(&value, "code") } else { has(&value, "error") && !has(&value, "state") };
        if envelope_error {
            let valid = if version == "0.3" { protocol::successor_error(&value, status, kind) } else { named(&value, version, "ErrorResponse") && status >= 400 };
            if !valid { return Err(protocol::bad(status, selector, None)); }
            return Err(protocol::evidence(if version == "0.3" { &value } else { at(&value, "error") }, status, selector, None, &value));
        }
        let mut valid = if version == "0.3" { protocol::successor(&value, status, kind, body) } else { protocol::wire02(&value, status, kind) };
        if let Some(selector) = selector {
            if handle.is_none() && !(version == "0.2" && kind == "submit" && is(at(&value, "state"), "rejected") && at(&value, "selector") == selector) { valid = false; }
        }
        if !valid { return Err(protocol::bad(status, selector, handle)); }
        if one(at(&value, "state"), &["failed", "rejected"]) { return Err(protocol::evidence(at(&value, "error"), status, selector, handle, &value)); }
        Ok(value)
    }
}
fn wait_headers(wait: Option<u32>) -> Result<BTreeMap<String, String>> {
    let mut headers = BTreeMap::new();
    if let Some(wait) = wait { if wait > 30000 { return Err(Error::invalid()); } headers.insert("EzLLMRouter-Wait-Ms".into(), wait.to_string()); }
    Ok(headers)
}
