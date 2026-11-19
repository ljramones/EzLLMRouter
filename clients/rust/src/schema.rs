use crate::json::{canonical, scalar, MAX_INTEGER};
use regex::Regex;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::{LazyLock, Mutex};

pub(crate) fn at<'a>(value: &'a Value, key: &str) -> &'a Value { value.get(key).unwrap_or(&Value::Null) }
pub(crate) fn text(value: &Value) -> &str { value.as_str().unwrap_or("") }
pub(crate) fn number(value: &Value) -> i64 { value.as_i64().unwrap_or(0) }
pub(crate) fn items(value: &Value) -> &[Value] { value.as_array().map(Vec::as_slice).unwrap_or(&[]) }
pub(crate) fn has(value: &Value, key: &str) -> bool { value.as_object().is_some_and(|map| map.contains_key(key)) }
pub(crate) fn is(value: &Value, s: &str) -> bool { value.as_str() == Some(s) }
pub(crate) fn one(value: &Value, choices: &[&str]) -> bool { value.as_str().is_some_and(|s| choices.contains(&s)) }
static PATTERNS: LazyLock<Mutex<HashMap<String, Regex>>> = LazyLock::new(|| Mutex::new(HashMap::new()));
pub(crate) fn pattern(value: &str, expression: &str) -> bool {
    let expression = expression.replace(r"(?![\s\S])", "$");
    let Ok(mut cache) = PATTERNS.lock() else { return false; };
    if !cache.contains_key(&expression) { let Ok(regex) = Regex::new(&expression) else { return false; }; cache.insert(expression.clone(), regex); }
    cache.get(&expression).is_some_and(|regex| regex.is_match(value))
}
pub(crate) fn id(value: &Value) -> bool { value.is_string() && pattern(text(value), r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$") }
pub(crate) fn positive(value: &Value) -> bool { value.as_i64().is_some_and(|n| n > 0 && n <= MAX_INTEGER) }
pub(crate) fn utc(value: &Value) -> bool {
    let s = text(value);
    s.len() == 20 && !s.starts_with("0000") && pattern(s, r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
        && s.get(17..19).and_then(|seconds| seconds.parse::<u8>().ok()).is_some_and(|seconds| seconds < 60)
        && chrono::DateTime::parse_from_rfc3339(s).is_ok()
}
pub(crate) fn keys(value: &Value, required: &[&str], optional: &[&str]) -> bool {
    value.as_object().is_some_and(|map| required.iter().all(|key| map.contains_key(*key)) && map.keys().all(|key| required.contains(&key.as_str()) || optional.contains(&key.as_str())))
}
pub(crate) fn ids(value: &Value, names: &[&str]) -> bool { names.iter().all(|key| id(at(value, key))) }
static BUNDLES: LazyLock<BTreeMap<&'static str, Value>> = LazyLock::new(|| {
    [
        ("0.2", include_str!("../schemas/wire02.json")),
        ("0.3", include_str!("../schemas/dev12_schemas.json")),
        ("1", include_str!("../schemas/integration_schema.json")),
        ("2", include_str!("../schemas/integration_schema_v2.json")),
        ("3", include_str!("../schemas/integration_schema_v3.json")),
    ].into_iter().map(|(version, source)| {
        let bundle: Value = serde_json::from_str(source).expect("embedded client schema");
        (version, bundle["$defs"].clone())
    }).collect()
});
pub(crate) fn named(value: &Value, version: &str, name: &str) -> bool {
    BUNDLES.get(version).is_some_and(|defs| defs.get(name).is_some_and(|shape| matches(value, shape, defs)))
}
fn bound(shape: &Value, key: &str, fallback: i64) -> i64 { at(shape, key).as_i64().unwrap_or(fallback) }
fn matches(value: &Value, shape: &Value, defs: &Value) -> bool {
    if let Some(reference) = at(shape, "$ref").as_str() {
        let Some(name) = reference.strip_prefix("#/$defs/") else { return false; };
        return defs.get(name).is_some_and(|target| (!matches!(name, "utc" | "UtcSecond") || utc(value)) && matches(value, target, defs));
    }
    if items(at(shape, "allOf")).iter().any(|part| !matches(value, part, defs)) { return false; }
    if has(shape, "anyOf") && !items(at(shape, "anyOf")).iter().any(|part| matches(value, part, defs)) { return false; }
    if has(shape, "oneOf") && items(at(shape, "oneOf")).iter().filter(|part| matches(value, part, defs)).count() != 1 { return false; }
    if has(shape, "not") && matches(value, at(shape, "not"), defs) { return false; }
    if has(shape, "if") { let branch = if matches(value, at(shape, "if"), defs) { "then" } else { "else" }; if has(shape, branch) && !matches(value, at(shape, branch), defs) { return false; } }
    if has(shape, "const") && value != at(shape, "const") { return false; }
    if has(shape, "enum") && !items(at(shape, "enum")).contains(value) { return false; }
    if let Some(map) = value.as_object() {
        if items(at(shape, "required")).iter().any(|key| !map.contains_key(text(key))) { return false; }
        for (key, item) in map {
            if let Some(property) = at(shape, "properties").get(key) { if !matches(item, property, defs) { return false; } }
            else if at(shape, "additionalProperties") == &Value::Bool(false) || at(shape, "additionalProperties").is_object() && !matches(item, at(shape, "additionalProperties"), defs) { return false; }
        }
    }
    match text(at(shape, "type")) {
        "object" => value.is_object(),
        "array" => value.as_array().is_some_and(|array| {
            if (array.len() as i64) < bound(shape, "minItems", 0) || (array.len() as i64) > bound(shape, "maxItems", MAX_INTEGER) { return false; }
            if at(shape, "uniqueItems") == &Value::Bool(true) { let mut seen = HashSet::new(); for item in array { let Ok(raw) = canonical(item) else { return false; }; if !seen.insert(raw) { return false; } } }
            !has(shape, "items") || array.iter().all(|item| matches(item, at(shape, "items"), defs))
        }),
        "string" => value.as_str().is_some_and(|s| scalar(s) && s.chars().count() as i64 >= bound(shape, "minLength", 0) && s.chars().count() as i64 <= bound(shape, "maxLength", MAX_INTEGER) && (!has(shape, "pattern") || pattern(s, text(at(shape, "pattern"))))),
        "integer" => value.as_i64().is_some_and(|n| n >= bound(shape, "minimum", -MAX_INTEGER) && n <= bound(shape, "maximum", MAX_INTEGER)),
        "boolean" => value.is_boolean(), "null" => value.is_null(), _ => true,
    }
}
