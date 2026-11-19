use crate::json::{canonical, parse_object};
use crate::schema::{at, is};
use crate::{Error, Result};
use reqwest::blocking::Client as HttpClient;
use serde_json::Value;
use std::collections::BTreeMap;
use std::io::Read;
use std::sync::{atomic::{AtomicBool, Ordering}, Arc};
use std::time::Duration;

/// A single service exchange. Implementations must not redirect or replay writes.
pub trait Transport: Send + Sync { fn send(&self, request: Request) -> std::result::Result<Response, TransportError>; }
pub struct Request { pub method: String, pub url: String, pub headers: BTreeMap<String, String>, pub body: Option<Vec<u8>>, pub timeout: Option<Duration> }
pub struct Response { pub status: u16, pub headers: BTreeMap<String, String>, pub body: Box<dyn Read + Send> }
impl Response { pub fn header(&self, name: &str) -> Option<&str> { self.headers.iter().find(|(key, _)| key.eq_ignore_ascii_case(name)).map(|(_, value)| value.as_str()) } }
#[derive(Debug)]
pub struct TransportError { pub http_status: Option<u16> }
pub struct Options { pub timeout: Option<Duration>, pub transport: Option<Arc<dyn Transport>> }
impl Default for Options { fn default() -> Self { Self { timeout: Some(Duration::from_secs(35)), transport: None } } }

struct HttpTransport(HttpClient);
impl Transport for HttpTransport {
    fn send(&self, request: Request) -> std::result::Result<Response, TransportError> {
        let method = reqwest::Method::from_bytes(request.method.as_bytes()).map_err(|_| TransportError { http_status: None })?;
        let mut builder = self.0.request(method, &request.url);
        if let Some(timeout) = request.timeout { builder = builder.timeout(timeout); }
        for (key, value) in request.headers { builder = builder.header(key.as_str(), value.as_str()); }
        if let Some(body) = request.body { builder = builder.body(body); }
        let response = builder.send().map_err(|error| TransportError { http_status: error.status().map(|s| s.as_u16()) })?;
        let status = response.status().as_u16(); let mut headers = BTreeMap::new();
        for (key, value) in response.headers() {
            let value = value.to_str().map_err(|_| TransportError { http_status: Some(status) })?;
            headers.entry(key.as_str().to_owned()).and_modify(|old: &mut String| { old.push(','); old.push_str(value); }).or_insert_with(|| value.to_owned());
        }
        Ok(Response { status, headers, body: Box::new(response) })
    }
}
pub(crate) struct Connection { origin: String, token: String, transport: Arc<dyn Transport>, timeout: Option<Duration>, closed: AtomicBool }
impl Connection {
    pub(crate) fn new(origin: &str, token: &str, options: Options) -> Result<Self> {
        let url = reqwest::Url::parse(origin).map_err(|_| Error::invalid())?;
        if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() || !url.username().is_empty() || url.password().is_some() || url.path() != "/" || url.query().is_some() || url.fragment().is_some() || token.is_empty() || !token.bytes().all(|b| (33..=126).contains(&b)) { return Err(Error::invalid()); }
        let transport: Arc<dyn Transport> = if let Some(transport) = options.transport { transport } else {
            let http = HttpClient::builder().redirect(reqwest::redirect::Policy::none()).no_proxy()
                .connect_timeout(Duration::from_secs(10)).timeout(options.timeout)
                .retry(reqwest::retry::never()).no_gzip().no_brotli().no_deflate().no_zstd()
                .pool_max_idle_per_host(0).build().map_err(|_| Error::invalid())?;
            Arc::new(HttpTransport(http))
        };
        Ok(Self { origin: origin.trim_end_matches('/').to_owned(), token: token.to_owned(), transport, timeout: options.timeout, closed: AtomicBool::new(false) })
    }
    pub(crate) fn close(&self) { self.closed.store(true, Ordering::Release); }
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn request(&self, method: &str, path: &str, header: &str, version: &str, body: Option<&Value>, extra: BTreeMap<String, String>, limit: usize, selector: Option<&Value>) -> Result<(Value, u16)> {
        if self.closed.load(Ordering::Acquire) { return Err(Error::new("CLIENT_CLOSED", None, "never", selector)); }
        let mut headers = extra; headers.insert("Authorization".into(), format!("Bearer {}", self.token)); headers.insert(header.into(), version.into()); headers.insert("Accept-Encoding".into(), "identity".into());
        let body = body.map(canonical).transpose()?; if body.is_some() { headers.insert("Content-Type".into(), "application/json".into()); }
        let mut response = self.transport.send(Request { method: method.into(), url: self.origin.clone() + path, headers, body, timeout: self.timeout }).map_err(|error| Error::new("TRANSPORT_OUTCOME_UNKNOWN", error.http_status, "query_first", selector))?;
        let status = response.status;
        let unknown = || Error::new("TRANSPORT_OUTCOME_UNKNOWN", Some(status), "query_first", selector);
        if response.header("Content-Encoding").is_some_and(|s| !s.trim().eq_ignore_ascii_case("identity")) { return Err(unknown()); }
        let declared = if let Some(s) = response.header("Content-Length") {
            if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) { return Err(unknown()); }
            let n = s.parse::<usize>().map_err(|_| unknown())?; if n > limit { return Err(unknown()); } Some(n)
        } else { None };
        let received_version = response.header(header).map(str::to_owned);
        let mut raw = Vec::new(); response.body.by_ref().take(limit as u64 + 1).read_to_end(&mut raw).map_err(|_| unknown())?;
        if raw.len() > limit || declared.is_some_and(|n| n != raw.len()) { return Err(unknown()); }
        let value = parse_object(&raw).map_err(|_| unknown())?;
        let field = if header == "Duranki-Integration-Version" { "integration_version" } else { "contract_version" };
        if !is(at(&value, field), version) || received_version.as_deref() != Some(version) { return Err(Error::new("UNSUPPORTED_VERSION", Some(status), "never", selector)); }
        Ok((value, status))
    }
}
pub(crate) fn escape(value: &str) -> String {
    let mut output = String::new();
    for b in value.bytes() { if b.is_ascii_alphanumeric() || b"-._~".contains(&b) { output.push(b as char); } else { output.push_str(&format!("%{b:02X}")); } }
    output
}
