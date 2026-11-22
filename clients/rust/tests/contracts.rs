use base64::Engine;
use ezllmrouter_client::{canonical, parse_object, Client, IntegrationClient, Options, Request, Response, Result, Transport, TransportError, Value};
use std::collections::BTreeMap;
use std::io::{self, Cursor, Read};
use std::sync::{atomic::{AtomicBool, AtomicUsize, Ordering}, Arc};
use std::time::Duration;

struct Body { reader: Cursor<Vec<u8>>, closed: Arc<AtomicBool>, reads: Arc<AtomicUsize> }
impl Read for Body { fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> { self.reads.fetch_add(1, Ordering::SeqCst); self.reader.read(buffer) } }
impl Drop for Body { fn drop(&mut self) { self.closed.store(true, Ordering::SeqCst); } }
struct Fake { fixture: Value, calls: AtomicUsize, closed: Arc<AtomicBool>, reads: Arc<AtomicUsize> }
impl Transport for Fake {
    fn send(&self, request: Request) -> std::result::Result<Response, TransportError> {
        let index = self.calls.fetch_add(1, Ordering::SeqCst); let calls = self.fixture["expected"]["calls"].as_array().unwrap();
        assert!(index < calls.len(), "unexpected transport invocation"); let call = &calls[index];
        assert_eq!(request.method, call["method"].as_str().unwrap());
        let path = request.url.strip_prefix("http://synthetic.invalid").unwrap(); assert_eq!(path, call["path"].as_str().unwrap());
        for (key, value) in call["headers"].as_object().unwrap() { assert_eq!(request.headers.get(key).map(String::as_str), value.as_str()); }
        let body = request.body.as_ref().map(|raw| parse_object(raw).unwrap()).unwrap_or(Value::Null); assert_eq!(body, call["body"]);
        if self.fixture["lost"] == true { return Err(TransportError { http_status: None }); }
        let mut headers = BTreeMap::new(); headers.insert("EzLLMRouter-Contract-Version".into(), self.fixture["wire"].as_str().unwrap_or("0.2").into()); headers.insert("EzLLMRouter-Integration-Version".into(), self.fixture["version"].as_str().unwrap_or("1").into());
        if let Some(extra) = self.fixture["response_headers"].as_object() { for (key, value) in extra { headers.insert(key.clone(), value.as_str().unwrap().into()); } }
        let raw = if let Some(raw) = self.fixture["raw"].as_str() { base64::engine::general_purpose::STANDARD.decode(raw).unwrap() } else { canonical(&self.fixture["response"]).unwrap() };
        Ok(Response { status: self.fixture["status"].as_u64().unwrap_or(200) as u16, headers,
            body: Box::new(Body { reader: Cursor::new(raw), closed: self.closed.clone(), reads: self.reads.clone() }) })
    }
}
fn invoke(client: &Client, integration: &IntegrationClient, fixture: &Value) -> Result<Value> {
    let args = fixture["args"].as_array().unwrap(); let s = |i: usize| args[i].as_str().unwrap(); let wait = fixture["wait_ms"].as_u64().map(|n| n as u32);
    match fixture["action"].as_str().unwrap() {
        "submit" => client.submit(&args[0], wait), "submit_in_run" => client.submit_in_run(&args[0], s(1), wait),
        "get_status" => client.get_status(&args[0]), "get_capabilities" => client.get_capabilities(),
        "get_successor_status" => client.get_successor_status(&args[0]), "submit_embedding" => client.submit_embedding(&args[0], wait), "submit_rerank" => client.submit_rerank(&args[0], wait),
        "start_run" => client.start_run(&args[0]), "get_run" => client.get_run(s(0)), "report_outcome" => client.report_outcome(&args[0]), "get_outcome_receipt" => client.get_outcome_receipt(s(0)),
        "create_dataset" => integration.create_dataset(&args[0]), "register_account" => integration.register_account(&args[0]),
        "set_account_state" => integration.set_account_state(s(0), &args[1]), "set_account_permissions" => integration.set_account_permissions(s(0), &args[1]),
        "submit_observation" => integration.submit_observation(&args[0]), "recover_receipt" => integration.recover_receipt(s(0), s(1)),
        "eligibility" => integration.eligibility(s(0), s(1), s(2)), "operation_eligibility" => integration.operation_eligibility(s(0), s(1), &args[2]),
        "report" => integration.report(s(0)), "submit_snapshot" => integration.submit_snapshot(&args[0]),
        "snapshot" => integration.snapshot(s(0), s(1)), "export_dataset" => integration.export_dataset(s(0)), _ => panic!("unknown action"),
    }
}
#[test]
fn shared_contract_cases() {
    let fixtures: Value = serde_json::from_str(include_str!("../../../tests/client_languages/cases.json")).unwrap();
    for fixture in fixtures.as_array().unwrap() {
        let name = fixture["name"].as_str().unwrap(); let expected = &fixture["expected"];
        let fake = Arc::new(Fake { fixture: fixture.clone(), calls: AtomicUsize::new(0), closed: Arc::new(AtomicBool::new(false)), reads: Arc::new(AtomicUsize::new(0)) });
        let options = || Options { transport: Some(fake.clone()), ..Options::default() };
        let client = Client::with_options("http://synthetic.invalid", "synthetic-token", options()).unwrap();
        let integration = IntegrationClient::with_options("http://synthetic.invalid", "synthetic-token", fixture["version"].as_str().unwrap_or("1"), options()).unwrap();
        let result = invoke(&client, &integration, fixture);
        if expected["ok"] == true {
            let result = result.unwrap_or_else(|error| panic!("{name}: {error:?}")); let action = fixture["action"].as_str().unwrap();
            let wanted = if matches!(action, "start_run" | "get_run") { &fixture["response"]["run"] } else if matches!(action, "report_outcome" | "get_outcome_receipt") { &fixture["response"]["receipt"] } else { &fixture["response"] };
            assert_eq!(&result, wanted, "{name}");
        } else {
            let error = result.expect_err(name); assert_eq!(error.code, expected["code"].as_str().unwrap(), "{name}");
            assert_eq!(error.retry_guidance, expected["retry_guidance"].as_str().unwrap(), "{name}");
            assert_eq!(u64::from(error.http_status.unwrap_or(0)), expected["http_status"].as_u64().unwrap(), "{name}");
            assert_eq!(error.selector.as_ref().unwrap_or(&Value::Null), &expected["selector"], "{name}"); assert_eq!(error.handle.as_ref().unwrap_or(&Value::Null), &expected["handle"], "{name}");
        }
        assert_eq!(fake.calls.load(Ordering::SeqCst), expected["calls"].as_array().unwrap().len(), "{name}");
        if fake.calls.load(Ordering::SeqCst) > 0 && fixture["lost"] != true { assert!(fake.closed.load(Ordering::SeqCst), "{name}: body leaked"); }
        if matches!(name, "oversize" | "compressed") { assert_eq!(fake.reads.load(Ordering::SeqCst), 0, "{name}"); }
    }
}
#[test]
fn strict_json_and_lifecycle() {
    for raw in [r#"{"a":1,"a":2}"#, r#"{"x":1.5}"#, r#"{"x":1e0}"#, r#"{"x":9007199254740992}"#, r#"{"x":"\ud800"}"#] { assert!(parse_object(raw.as_bytes()).is_err()); }
    let unicode = "{\"a\":\"é\",\"n\":7,\"z\":\"<>&\u{2028}\"}";
    assert_eq!(canonical(&parse_object(unicode.as_bytes()).unwrap()).unwrap(), unicode.as_bytes());
    for origin in ["file:///tmp/a", "http://u:p@example.com", "http://example.com/path", "http://example.com?", "http://example.com#"] { assert!(Client::new(origin, "token").is_err()); }
    let client = Client::new("http://synthetic.invalid", "token").unwrap(); client.close(); assert_eq!(client.get_capabilities().unwrap_err().code, "CLIENT_CLOSED");
}
#[test]
fn large_embedding_matches_the_request_profile() {
    let fixtures: Value = serde_json::from_str(include_str!("../../../tests/client_languages/cases.json")).unwrap();
    let mut fixture = fixtures.as_array().unwrap().iter().find(|row| row["name"] == "embedding").unwrap().clone();
    let mut request = fixture["args"][0].clone();
    request["requested_configuration_ref"] = "cfg.new".into();
    request["input"]["profile"]["dimensions"] = 2048.into(); request["input"]["profile"]["profile_id"] = "profile.new".into(); request["input"]["profile"]["model_ref"] = "model.new".into();
    let mut inputs = Vec::new(); let mut vectors = Vec::new();
    for index in 0..25 {
        let id = format!("item.{index}"); inputs.push(serde_json::json!({"item_id":id.as_str(),"text":"synthetic"}));
        vectors.push(serde_json::json!({"item_id":id.as_str(),"input_index":index,"values":vec!["0.1234567890123456";2048]}));
    }
    request["input"]["items"] = inputs.into();
    fixture["response"]["result"]["dimensions"] = 2048.into(); fixture["response"]["result"]["profile_id"] = "profile.new".into(); fixture["response"]["result"]["model_ref"] = "model.new".into(); fixture["response"]["result"]["vectors"] = vectors.into();
    fixture["expected"]["calls"][0]["body"] = request.clone(); assert!(canonical(&fixture["response"]).unwrap().len() > 1024 * 1024);
    let fake = Arc::new(Fake { fixture, calls: AtomicUsize::new(0), closed: Arc::new(AtomicBool::new(false)), reads: Arc::new(AtomicUsize::new(0)) });
    let client = Client::with_options("http://synthetic.invalid", "synthetic-token", Options { transport: Some(fake.clone()), ..Options::default() }).unwrap();
    let reply = client.submit_embedding(&request, None).unwrap(); assert_eq!(reply["result"]["vectors"].as_array().unwrap().len(), 25);
    assert_eq!(fake.calls.load(Ordering::SeqCst), 1); assert!(fake.closed.load(Ordering::SeqCst));
}
#[test]
fn native_http() {
    let Ok(origin) = std::env::var("EZLLMROUTER_TEST_ORIGIN") else { return; };
    let policy: Value = serde_json::from_slice(&std::fs::read(std::env::var("EZLLMROUTER_TEST_MATRIX").unwrap()).unwrap()).unwrap();
    let cases = policy["cases"].as_array().unwrap(); assert_eq!(cases.len(), 28);
    for row in cases {
        let mode = row["id"].as_str().unwrap();
        let endpoint = if mode == "untrusted_tls" { std::env::var("EZLLMROUTER_TEST_TLS_ORIGIN").unwrap() } else { origin.clone() };
        let options = Options { timeout: Some(Duration::from_millis(row["timeout_ms"].as_u64().unwrap())), ..Options::default() };
        let client = Client::with_options(&endpoint, &format!("synthetic-native-{mode}"), options).unwrap(); let result = client.get_capabilities();
        if row["code"].is_null() { assert_eq!(result.unwrap()["profile"], "initial_1a@1"); }
        else {
            let error = result.unwrap_err(); assert_eq!(error.code, row["code"].as_str().unwrap(), "{mode}");
            assert_eq!(error.retry_guidance, row["retry_guidance"].as_str().unwrap(), "{mode}");
            assert!(row["http_status"].as_array().unwrap().iter().any(|value| value.as_u64() == Some(u64::from(error.http_status.unwrap_or(0)))), "{mode}: unexpected status");
        }
    }
}
