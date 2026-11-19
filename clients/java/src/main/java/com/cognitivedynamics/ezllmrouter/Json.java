package com.cognitivedynamics.ezllmrouter;

import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Integer-only protocol JSON. Decimal amounts and vector coordinates are strings. */
public final class Json {
    static final long MAX_INTEGER = 9007199254740991L;
    private Json() {}

    /** Decode UTF-8, rejecting duplicate keys, unsafe numbers and invalid scalars. */
    public static Object parse(byte[] bytes) { return parse(bytes, true); }
    public static Object parse(String text) {
        try {
            ByteBuffer encoded = StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(text));
            byte[] bytes = new byte[encoded.remaining()]; encoded.get(bytes); return parse(bytes);
        } catch (CharacterCodingException error) { throw invalid(); }
    }
    /** Decode a record without an unchecked application-side cast. */
    public static Map<String, Object> parseObject(byte[] bytes) {
        Object value = parse(bytes); if (!(value instanceof Map<?, ?>)) throw invalid(); return Values.object(value);
    }
    public static Map<String, Object> parseObject(String text) {
        Object value = parse(text); if (!(value instanceof Map<?, ?>)) throw invalid(); return Values.object(value);
    }
    static Object parse(byte[] bytes, boolean strict) {
        try {
            String text = StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes)).toString();
            Parser parser = new Parser(text, strict);
            Object value = parser.value(0);
            parser.space();
            if (parser.index != text.length()) throw invalid();
            return value;
        } catch (CharacterCodingException error) { throw invalid(); }
    }

    /** Return compact UTF-8 JSON with keys sorted in the service's Unicode order. */
    public static String stringify(Object value) {
        StringBuilder out = new StringBuilder();
        write(out, value, 0);
        return out.toString();
    }
    static byte[] bytes(Object value) { return stringify(value).getBytes(StandardCharsets.UTF_8); }
    static Map<String, Object> snapshot(Map<String, Object> value) { return Values.object(parse(bytes(value))); }
    static IllegalArgumentException invalid() { return new IllegalArgumentException("invalid protocol JSON"); }
    static boolean scalar(String value) {
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == 0) return false;
            if (Character.isHighSurrogate(c)) {
                if (++i >= value.length() || !Character.isLowSurrogate(value.charAt(i))) return false;
            } else if (Character.isLowSurrogate(c)) return false;
        }
        return true;
    }
    private static final Comparator<String> KEY_ORDER = (left, right) -> {
        var a = left.codePoints().iterator(); var b = right.codePoints().iterator();
        while (a.hasNext() && b.hasNext()) {
            int comparison = Integer.compare(a.nextInt(), b.nextInt());
            if (comparison != 0) return comparison;
        }
        return Boolean.compare(a.hasNext(), b.hasNext());
    };
    private static void quote(StringBuilder out, String value) {
        if (!scalar(value)) throw invalid();
        out.append('"');
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"', '\\' -> { out.append('\\'); out.append(c); }
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 32) out.append("\\u00").append(Character.forDigit(c >> 4, 16)).append(Character.forDigit(c & 15, 16));
                    else out.append(c);
                }
            }
        }
        out.append('"');
    }
    private static void write(StringBuilder out, Object value, int depth) {
        if (depth > 32) throw invalid();
        if (value == null) out.append("null");
        else if (value instanceof String text) quote(out, text);
        else if (value instanceof Boolean) out.append(value);
        else if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long) {
            long number = ((Number) value).longValue();
            if (number < -MAX_INTEGER || number > MAX_INTEGER) throw invalid();
            out.append(number);
        } else if (value instanceof Map<?, ?> map) {
            List<String> keys = new ArrayList<>();
            for (Object key : map.keySet()) { if (!(key instanceof String)) throw invalid(); keys.add((String) key); }
            keys.sort(KEY_ORDER); out.append('{');
            boolean first = true;
            for (String key : keys) { if (!first) out.append(','); first = false; quote(out, key); out.append(':'); write(out, map.get(key), depth + 1); }
            out.append('}');
        } else if (value instanceof List<?> list) {
            out.append('['); boolean first = true;
            for (Object item : list) { if (!first) out.append(','); first = false; write(out, item, depth + 1); }
            out.append(']');
        } else throw invalid();
    }

    private static final class Parser {
        final String text; final boolean strict; int index;
        Parser(String text, boolean strict) { this.text = text; this.strict = strict; }
        void space() { while (index < text.length() && " \t\r\n".indexOf(text.charAt(index)) >= 0) index++; }
        char take() { if (index >= text.length()) throw invalid(); return text.charAt(index++); }
        boolean accept(char c) { space(); if (index < text.length() && text.charAt(index) == c) { index++; return true; } return false; }
        void expect(char c) { if (!accept(c)) throw invalid(); }
        String string() {
            if (take() != '"') throw invalid(); StringBuilder out = new StringBuilder();
            while (true) {
                char c = take();
                if (c == '"') break;
                if (c < 32) throw invalid();
                if (c == '\\') {
                    c = take();
                    switch (c) {
                        case '"', '\\', '/' -> out.append(c);
                        case 'b' -> out.append('\b'); case 'f' -> out.append('\f');
                        case 'n' -> out.append('\n'); case 'r' -> out.append('\r'); case 't' -> out.append('\t');
                        case 'u' -> { int code = 0; for (int i = 0; i < 4; i++) { char hex = take(); int digit = "0123456789abcdef".indexOf(Character.toLowerCase(hex)); if (digit < 0) throw invalid(); code = code * 16 + digit; } out.append((char) code); }
                        default -> throw invalid();
                    }
                } else out.append(c);
            }
            String value = out.toString(); if (strict && !scalar(value)) throw invalid(); return value;
        }
        Object value(int depth) {
            if (depth > (strict ? 32 : 128)) throw invalid(); space();
            if (index >= text.length()) throw invalid(); char c = text.charAt(index);
            if (c == '"') return string();
            if (c == '{') {
                index++; Map<String, Object> out = new LinkedHashMap<>(); if (accept('}')) return out;
                do { space(); String key = string(); if (out.containsKey(key)) throw invalid(); expect(':'); out.put(key, value(depth + 1)); } while (accept(','));
                expect('}'); return out;
            }
            if (c == '[') {
                index++; List<Object> out = new ArrayList<>(); if (accept(']')) return out;
                do { out.add(value(depth + 1)); } while (accept(',')); expect(']'); return out;
            }
            for (String word : List.of("true", "false", "null")) {
                if (text.startsWith(word, index)) { index += word.length(); return word.equals("null") ? null : Boolean.valueOf(word); }
            }
            int start = index; if (c == '-') index++;
            if (index >= text.length()) throw invalid(); c = text.charAt(index++);
            if (c >= '1' && c <= '9') { while (index < text.length() && text.charAt(index) >= '0' && text.charAt(index) <= '9') index++; }
            else if (c != '0') throw invalid();
            try { long n = Long.parseLong(text.substring(start, index)); if (n < -MAX_INTEGER || n > MAX_INTEGER) throw invalid(); return n; }
            catch (NumberFormatException error) { throw invalid(); }
        }
    }
}
