package com.cognitivedynamics.ezllmrouter;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.DateTimeException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

final class Values {
    private Values() {}
    @SuppressWarnings("unchecked")
    static Map<String, Object> object(Object value) { return value instanceof Map<?, ?> ? (Map<String, Object>) value : Map.of(); }
    static Map<String, Object> field(Map<String, Object> value, String key) { return object(value.get(key)); }
    static List<?> array(Object value) { return value instanceof List<?> list ? list : List.of(); }
    static String text(Object value) { return value instanceof String text ? text : ""; }
    static long number(Object value) { return value instanceof Long n ? n : 0; }
    static boolean eq(Object a, Object b) { return Objects.equals(a, b); }
    static boolean id(Object value) { return value instanceof String s && s.matches("[A-Za-z0-9][A-Za-z0-9._:-]{0,159}"); }
    static boolean positive(Object value) { return value instanceof Long n && n > 0 && n <= Json.MAX_INTEGER; }
    static boolean ids(Map<String, Object> value, String... keys) { for (String key : keys) if (!id(value.get(key))) return false; return true; }
    static boolean utc(Object value) {
        if (!(value instanceof String s) || !s.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z") || s.startsWith("0000")) return false;
        try { return Instant.parse(s).toString().equals(s); } catch (DateTimeException error) { return false; }
    }
    static boolean keys(Map<String, Object> value, Set<String> required, Set<String> optional) {
        return value.keySet().containsAll(required) && value.keySet().stream().allMatch(key -> required.contains(key) || optional.contains(key));
    }
    static String digest(Map<String, Object> value) {
        try { return "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Json.stringify(value).getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }
}
