package com.cognitivedynamics.ezllmrouter;

import static com.cognitivedynamics.ezllmrouter.Values.*;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.regex.Pattern;
import java.util.concurrent.ConcurrentHashMap;

final class Schema {
    private Schema() {}
    private static final Map<String, Map<String, Object>> BUNDLES = load();
    private static final Map<String, Pattern> PATTERNS = new ConcurrentHashMap<>();
    private static Map<String, Map<String, Object>> load() {
        Map<String, Map<String, Object>> out = new HashMap<>();
        Map<String, String> files = Map.of("0.2", "wire02.json", "0.3", "dev12_schemas.json", "1", "integration_schema.json", "2", "integration_schema_v2.json", "3", "integration_schema_v3.json");
        for (var file : files.entrySet()) {
            try (InputStream stream = Schema.class.getResourceAsStream("schemas/" + file.getValue())) {
                if (stream == null) throw new IOException("missing client schema");
                out.put(file.getKey(), field(object(Json.parse(stream.readAllBytes(), false)), "$defs"));
            } catch (IOException error) { throw new ExceptionInInitializerError(error); }
        }
        return out;
    }
    static boolean policy(Object value, boolean nulls, boolean controls) {
        if (value == null) return nulls;
        if (value instanceof String string) return !controls || string.chars().noneMatch(c -> c < 32 || c == 127);
        if (value instanceof Map<?, ?> map) return map.entrySet().stream().allMatch(e -> policy(e.getKey(), nulls, controls) && policy(e.getValue(), nulls, controls));
        if (value instanceof java.util.List<?> list) return list.stream().allMatch(item -> policy(item, nulls, controls));
        return true;
    }
    static boolean named(Object value, String version, String name) {
        Map<String, Object> definitions = BUNDLES.get(version);
        return (!version.equals("0.3") || policy(value, true, true)) && definitions != null && definitions.containsKey(name) && matches(value, object(definitions.get(name)), definitions);
    }
    private static long bound(Map<String, Object> shape, String key, long fallback) { return shape.get(key) instanceof Long n ? n : fallback; }
    private static boolean matches(Object value, Map<String, Object> shape, Map<String, Object> defs) {
        if (shape.get("$ref") instanceof String ref) {
            String name = ref.replaceFirst("^#/\\$defs/", "");
            if (name.equals("PublicText") && value instanceof String string && string.chars().anyMatch(c -> c < 32 || c == 127)) return false;
            return !name.equals(ref) && defs.containsKey(name) && (!(name.equals("utc") || name.equals("UtcSecond")) || utc(value)) && matches(value, object(defs.get(name)), defs);
        }
        for (Object part : array(shape.get("allOf"))) if (!matches(value, object(part), defs)) return false;
        if (shape.containsKey("anyOf") && array(shape.get("anyOf")).stream().noneMatch(part -> matches(value, object(part), defs))) return false;
        if (shape.containsKey("oneOf") && array(shape.get("oneOf")).stream().filter(part -> matches(value, object(part), defs)).count() != 1) return false;
        if (shape.containsKey("not") && matches(value, object(shape.get("not")), defs)) return false;
        if (shape.containsKey("if")) {
            String branch = matches(value, object(shape.get("if")), defs) ? "then" : "else";
            if (shape.containsKey(branch) && !matches(value, object(shape.get(branch)), defs)) return false;
        }
        if (shape.containsKey("const") && !eq(value, shape.get("const"))) return false;
        if (shape.containsKey("enum") && !array(shape.get("enum")).contains(value)) return false;
        if (value instanceof Map<?, ?>) {
            Map<String, Object> map = object(value), properties = field(shape, "properties");
            for (Object key : array(shape.get("required"))) if (!map.containsKey(text(key))) return false;
            for (var entry : map.entrySet()) {
                if (properties.containsKey(entry.getKey())) {
                    if (!matches(entry.getValue(), object(properties.get(entry.getKey())), defs)) return false;
                } else if (Boolean.FALSE.equals(shape.get("additionalProperties"))) return false;
                else if (shape.get("additionalProperties") instanceof Map<?, ?> && !matches(entry.getValue(), object(shape.get("additionalProperties")), defs)) return false;
            }
        }
        switch (text(shape.get("type"))) {
            case "object": return value instanceof Map<?, ?>;
            case "array":
                if (!(value instanceof java.util.List<?> list) || list.size() < bound(shape, "minItems", 0) || list.size() > bound(shape, "maxItems", Json.MAX_INTEGER)) return false;
                if (Boolean.TRUE.equals(shape.get("uniqueItems")) && new HashSet<>(list).size() != list.size()) return false;
                return !shape.containsKey("items") || list.stream().allMatch(item -> matches(item, object(shape.get("items")), defs));
            case "string":
                if (!(value instanceof String string) || !Json.scalar(string) || string.codePointCount(0, string.length()) < bound(shape, "minLength", 0) || string.codePointCount(0, string.length()) > bound(shape, "maxLength", Json.MAX_INTEGER)) return false;
                return !shape.containsKey("pattern") || PATTERNS.computeIfAbsent(text(shape.get("pattern")),
                    expression -> Pattern.compile(expression.endsWith("$") ? expression.substring(0, expression.length() - 1) + "\\z" : expression)).matcher(string).find();
            case "integer": return value instanceof Long n && n >= bound(shape, "minimum", -Json.MAX_INTEGER) && n <= bound(shape, "maximum", Json.MAX_INTEGER);
            case "boolean": return value instanceof Boolean;
            case "null": return value == null;
            default: return true;
        }
    }
}
