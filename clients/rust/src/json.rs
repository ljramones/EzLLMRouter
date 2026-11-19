use crate::{Error, Result};
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fmt;

pub(crate) const MAX_INTEGER: i64 = 9_007_199_254_740_991;
pub(crate) fn scalar(value: &str) -> bool {
    !value.chars().any(|c| c < ' ' || c == '\u{7f}')
}
struct Strict(Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        struct StrictVisitor;
        impl<'de> Visitor<'de> for StrictVisitor {
            type Value = Strict;
            fn expecting(&self, out: &mut fmt::Formatter<'_>) -> fmt::Result { out.write_str("strict protocol JSON") }
            fn visit_bool<E: de::Error>(self, value: bool) -> std::result::Result<Strict, E> { Ok(Strict(value.into())) }
            fn visit_unit<E: de::Error>(self) -> std::result::Result<Strict, E> { Ok(Strict(Value::Null)) }
            fn visit_i64<E: de::Error>(self, value: i64) -> std::result::Result<Strict, E> {
                if !(-MAX_INTEGER..=MAX_INTEGER).contains(&value) { return Err(E::custom("unsafe integer")); }
                Ok(Strict(value.into()))
            }
            fn visit_u64<E: de::Error>(self, value: u64) -> std::result::Result<Strict, E> {
                if value > MAX_INTEGER as u64 { return Err(E::custom("unsafe integer")); }
                Ok(Strict(value.into()))
            }
            fn visit_f64<E: de::Error>(self, _: f64) -> std::result::Result<Strict, E> { Err(E::custom("noninteger number")) }
            fn visit_str<E: de::Error>(self, value: &str) -> std::result::Result<Strict, E> {
                if !scalar(value) { return Err(E::custom("invalid scalar")); }
                Ok(Strict(value.into()))
            }
            fn visit_string<E: de::Error>(self, value: String) -> std::result::Result<Strict, E> { self.visit_str(&value) }
            fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> std::result::Result<Strict, A::Error> {
                let mut values = Vec::new();
                while let Some(Strict(item)) = sequence.next_element::<Strict>()? { values.push(item); }
                Ok(Strict(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<Strict, A::Error> {
                let mut values = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if !scalar(&key) || values.contains_key(&key) { return Err(de::Error::custom("invalid or duplicate key")); }
                    let Strict(value) = map.next_value::<Strict>()?; values.insert(key, value);
                }
                Ok(Strict(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(StrictVisitor)
    }
}

pub fn parse_object(bytes: &[u8]) -> Result<Value> {
    let mut parser = serde_json::Deserializer::from_slice(bytes);
    let Strict(value) = Strict::deserialize(&mut parser).map_err(|_| Error::invalid())?;
    parser.end().map_err(|_| Error::invalid())?;
    if !value.is_object() { return Err(Error::invalid()); }
    canonical(&value)?;
    Ok(value)
}

pub fn canonical(value: &Value) -> Result<Vec<u8>> {
    fn write(out: &mut String, value: &Value, depth: usize) -> Result<()> {
        if depth > 32 { return Err(Error::invalid()); }
        match value {
            Value::Null => out.push_str("null"),
            Value::Bool(v) => out.push_str(if *v { "true" } else { "false" }),
            Value::Number(v) => {
                let n = v.as_i64().ok_or_else(Error::invalid)?;
                if !(-MAX_INTEGER..=MAX_INTEGER).contains(&n) { return Err(Error::invalid()); }
                out.push_str(&n.to_string());
            }
            Value::String(v) => {
                if !scalar(v) { return Err(Error::invalid()); }
                out.push_str(&serde_json::to_string(v).map_err(|_| Error::invalid())?);
            }
            Value::Array(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() { if i > 0 { out.push(','); } write(out, item, depth + 1)?; }
                out.push(']');
            }
            Value::Object(map) => {
                out.push('{'); let mut entries: Vec<_> = map.iter().collect(); entries.sort_by(|a, b| a.0.cmp(b.0));
                for (i, (key, item)) in entries.into_iter().enumerate() {
                    if !scalar(key) { return Err(Error::invalid()); }
                    if i > 0 { out.push(','); }
                    out.push_str(&serde_json::to_string(key).map_err(|_| Error::invalid())?); out.push(':'); write(out, item, depth + 1)?;
                }
                out.push('}');
            }
        }
        Ok(())
    }
    let mut output = String::new(); write(&mut output, value, 0)?; Ok(output.into_bytes())
}
pub(crate) fn snapshot(value: &Value) -> Result<Value> { parse_object(&canonical(value)?) }
pub(crate) fn digest(value: &Value) -> Result<String> { Ok(format!("sha256:{:x}", Sha256::digest(canonical(value)?))) }
