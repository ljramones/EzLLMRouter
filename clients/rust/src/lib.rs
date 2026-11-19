//! Execution and external accounting clients for a trusted EzLLMRouter service.
//! No operation dispatches directly to a model provider or is automatically replayed.
mod attribution;
mod client;
mod integration;
mod json;
mod protocol;
mod schema;
pub mod transport;

pub use client::Client;
pub use integration::IntegrationClient;
pub use json::{canonical, parse_object};
pub use serde_json::{json, Value};
pub use transport::{Options, Request, Response, Transport, TransportError};

pub const VERSION: &str = "0.3.0";
pub type Result<T> = std::result::Result<T, Error>;

/// Recovery evidence for an API or transport failure. No raw request payload is attached.
#[derive(Debug, Clone)]
pub struct Error {
    pub code: String,
    pub http_status: Option<u16>,
    pub retry_guidance: String,
    pub correlation_id: Option<String>,
    pub selector: Option<Value>,
    pub handle: Option<Value>,
    pub work_key: Option<Value>,
    pub attempt_id: Option<String>,
    pub failure_stage: Option<String>,
}
impl Error {
    pub(crate) fn new(code: &str, status: Option<u16>, guidance: &str, selector: Option<&Value>) -> Self {
        Self { code: code.into(), http_status: status, retry_guidance: guidance.into(), correlation_id: None,
            selector: selector.cloned(), handle: None, work_key: None, attempt_id: None, failure_stage: None }
    }
    pub(crate) fn invalid() -> Self { Self::new("SCHEMA_INVALID", None, "never", None) }
    pub fn requires_query(&self) -> bool { self.retry_guidance == "query_first" }
}
impl std::fmt::Display for Error {
    fn fmt(&self, out: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { out.write_str(&self.code) }
}
impl std::error::Error for Error {}
