use ezllmrouter_client::{canonical, parse_object};
use serde_json::Value;

#[test]
fn independent_decoder_corpus() {
    let policy: Value = serde_json::from_str(include_str!("../../../tests/fixtures/contracts/transport-security/decoder_cases.json")).unwrap();
    let cases = policy["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 536, "decoder corpus inventory changed");
    for row in cases {
        let raw = row["raw_hex"].as_str().unwrap().as_bytes();
        let bytes: Vec<u8> = raw.chunks_exact(2).map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap()).collect();
        let actual = parse_object(&bytes).and_then(|value| canonical(&value)).ok().map(|bytes| String::from_utf8(bytes).unwrap());
        assert_eq!(actual.as_deref(), row["canonical"].as_str(), "decoder corpus mismatch: {}", row["id"]);
    }
}
