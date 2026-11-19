package com.cognitivedynamics.ezllmrouter;

import static com.cognitivedynamics.ezllmrouter.Values.*;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/** Synchronous wire 0.2, wire 0.3 and attribution client. No operation is replayed by this client. */
public final class EzLLMRouterClient implements AutoCloseable {
    public static final String VERSION = "0.3.0";
    final Connection connection;
    public EzLLMRouterClient(String origin, String token) { this(origin, token, Duration.ofSeconds(35), null); }
    public EzLLMRouterClient(String origin, String token, Transport transport) { this(origin, token, Duration.ofSeconds(35), transport); }
    public EzLLMRouterClient(String origin, String token, Duration timeout, Transport transport) { connection = new Connection(origin, token, timeout, transport); }
    @Override public void close() { connection.close(); }
    static String escape(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20"); }
    static Map<String, Object> snapshot(Map<String, Object> value) {
        try { if (value == null) throw Protocol.invalid(); return Json.snapshot(value); }
        catch (IllegalArgumentException failure) { throw Protocol.invalid(); }
    }
    private static Map<String, String> waitHeader(Integer waitMs) {
        if (waitMs == null) return Map.of(); if (waitMs < 0 || waitMs > 30000) throw Protocol.invalid();
        return Map.of("EzLLMRouter-Wait-Ms", waitMs.toString());
    }
    public Map<String, Object> submit(Map<String, Object> request) { return submit(request, null); }
    public Map<String, Object> submit(Map<String, Object> request, Integer waitMs) { return submitInRun(request, null, waitMs); }
    public Map<String, Object> submitInRun(Map<String, Object> request, String runId, Integer waitMs) {
        Map<String, Object> body = snapshot(request), selector = new LinkedHashMap<>();
        for (String key : Protocol.SELECTOR) selector.put(key, body.get(key));
        if (!Schema.named(selector, "0.2", "WorkSelector") || runId != null && !id(runId)) throw Protocol.invalid();
        Map<String, String> headers = new HashMap<>(waitHeader(waitMs));
        if (runId != null) { headers.put("EzLLMRouter-Attribution-Version", "1"); headers.put("EzLLMRouter-Attribution-Run", runId); }
        return wire("POST", "/v1/submissions", "0.2", "submit", body, selector, headers);
    }
    public Map<String, Object> getStatus(Map<String, Object> selector) { return status(selector, "0.2"); }
    public Map<String, Object> getSuccessorStatus(Map<String, Object> selector) { return status(selector, "0.3"); }
    private Map<String, Object> status(Map<String, Object> value, String version) {
        Map<String, Object> selector = snapshot(value), work = selector; String path;
        if (version.equals("0.3")) { if (!Schema.named(selector, version, "StatusQuery")) throw Protocol.invalid(); if (selector.containsKey("work_selector")) work = field(selector, "work_selector"); }
        if (selector.size() == 1 && id(selector.get("submission_id"))) path = "/v1/submissions/" + escape(text(selector.get("submission_id")));
        else if (Schema.named(work, version, "WorkSelector")) {
            StringBuilder out = new StringBuilder("/v1/submissions/by-work"); for (String key : Protocol.SELECTOR) out.append('/').append(escape(work.get(key).toString())); path = out.toString();
        } else throw Protocol.invalid();
        return wire("GET", path, version, "status", null, work, Map.of());
    }
    public Map<String, Object> getCapabilities() { return wire("GET", "/v1/capabilities", "0.2", "capabilities", null, null, Map.of()); }
    public Map<String, Object> submitEmbedding(Map<String, Object> request) { return submitEmbedding(request, null); }
    public Map<String, Object> submitEmbedding(Map<String, Object> request, Integer waitMs) { return successor(request, waitMs, "embedding.create"); }
    public Map<String, Object> submitRerank(Map<String, Object> request) { return submitRerank(request, null); }
    public Map<String, Object> submitRerank(Map<String, Object> request, Integer waitMs) { return successor(request, waitMs, "rerank"); }
    private Map<String, Object> successor(Map<String, Object> request, Integer waitMs, String operation) {
        Map<String, Object> body = snapshot(request);
        if (!Schema.named(body, "0.3", "SubmitRequest") || !eq(field(body, "operation").get("type"), operation)) throw Protocol.invalid();
        if (Json.bytes(body).length > 262144) throw Connection.error("LIMIT_EXCEEDED", 0, "never", null);
        return wire("POST", "/v1/submissions", "0.3", "submit", body, field(body, "work_selector"), waitHeader(waitMs));
    }
    private Map<String, Object> wire(String method, String path, String version, String kind, Map<String, Object> body, Map<String, Object> selector, Map<String, String> headers) {
        Connection.Reply response = connection.request(method, path, "EzLLMRouter-Contract-Version", version, body, headers, version.equals("0.3") ? 16 * 1024 * 1024 : 1024 * 1024, selector);
        Map<String, Object> value = response.value(), handle = Protocol.matchingHandle(value, selector, version); int status = response.status();
        boolean envelopeError = version.equals("0.3") ? value.containsKey("code") : value.containsKey("error") && !value.containsKey("state");
        if (envelopeError) {
            boolean valid = version.equals("0.3") ? Protocol.successorError(value, status, kind) : Schema.named(value, version, "ErrorResponse") && status >= 400;
            if (!valid) throw Protocol.bad(status, selector, null);
            throw Protocol.evidence(version.equals("0.3") ? value : field(value, "error"), status, selector, null, value);
        }
        boolean valid = version.equals("0.3") ? Protocol.successor(value, status, kind, body) : Protocol.wire02(value, status, kind);
        if (selector != null && handle == null && !(version.equals("0.2") && kind.equals("submit") && eq(value.get("state"), "rejected") && eq(value.get("selector"), selector))) valid = false;
        if (!valid) throw Protocol.bad(status, selector, handle);
        if (eq(value.get("state"), "failed") || eq(value.get("state"), "rejected")) throw Protocol.evidence(field(value, "error"), status, selector, handle, value);
        return value;
    }
    public Map<String, Object> startRun(Map<String, Object> run) { return Attribution.start(this, run); }
    public Map<String, Object> getRun(String runId) { if (!id(runId)) throw Protocol.invalid(); return Attribution.request(this, "GET", "/v1/attribution-runs/" + escape(runId), null, false, runId); }
    public Map<String, Object> reportOutcome(Map<String, Object> event) { return Attribution.report(this, event); }
    public Map<String, Object> getOutcomeReceipt(String eventId) { if (!id(eventId)) throw Protocol.invalid(); return Attribution.request(this, "GET", "/v1/outcomes/" + escape(eventId), null, true, eventId); }
}
