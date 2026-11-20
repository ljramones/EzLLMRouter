package com.cognitivedynamics.ezllmrouter;

import static com.cognitivedynamics.ezllmrouter.Values.*;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Base64;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

public final class ClientTest {
    private ClientTest() {}
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    private static final class Body extends ByteArrayInputStream {
        boolean closed; int reads;
        Body(byte[] bytes) { super(bytes); }
        @Override public synchronized int read(byte[] bytes, int offset, int length) { reads++; return super.read(bytes, offset, length); }
        @Override public void close() { closed = true; }
    }
    private static Map<String, Object> invoke(EzLLMRouterClient client, IntegrationClient integration, Map<String, Object> test) {
        List<?> args = array(test.get("args")); Integer wait = test.containsKey("wait_ms") ? (int) number(test.get("wait_ms")) : null;
        return switch (text(test.get("action"))) {
            case "submit" -> client.submit(object(args.get(0)), wait);
            case "submit_in_run" -> client.submitInRun(object(args.get(0)), text(args.get(1)), wait);
            case "get_status" -> client.getStatus(object(args.get(0)));
            case "get_capabilities" -> client.getCapabilities();
            case "get_successor_status" -> client.getSuccessorStatus(object(args.get(0)));
            case "submit_embedding" -> client.submitEmbedding(object(args.get(0)), wait);
            case "submit_rerank" -> client.submitRerank(object(args.get(0)), wait);
            case "start_run" -> client.startRun(object(args.get(0)));
            case "get_run" -> client.getRun(text(args.get(0)));
            case "report_outcome" -> client.reportOutcome(object(args.get(0)));
            case "get_outcome_receipt" -> client.getOutcomeReceipt(text(args.get(0)));
            case "create_dataset" -> integration.createDataset(object(args.get(0)));
            case "register_account" -> integration.registerAccount(object(args.get(0)));
            case "set_account_state" -> integration.setAccountState(text(args.get(0)), object(args.get(1)));
            case "set_account_permissions" -> integration.setAccountPermissions(text(args.get(0)), object(args.get(1)));
            case "submit_observation" -> integration.submitObservation(object(args.get(0)));
            case "recover_receipt" -> integration.recoverReceipt(text(args.get(0)), text(args.get(1)));
            case "eligibility" -> integration.eligibility(text(args.get(0)), text(args.get(1)), text(args.get(2)));
            case "operation_eligibility" -> integration.operationEligibility(text(args.get(0)), text(args.get(1)), object(args.get(2)));
            case "report" -> integration.report(text(args.get(0)));
            case "submit_snapshot" -> integration.submitSnapshot(object(args.get(0)));
            case "snapshot" -> integration.snapshot(text(args.get(0)), text(args.get(1)));
            case "export_dataset" -> integration.exportDataset(text(args.get(0)));
            default -> throw new AssertionError("unknown action");
        };
    }
    private static void parity(Map<String, Object> test) {
        Map<String, Object> expected = field(test, "expected"); List<?> calls = array(expected.get("calls")); AtomicInteger count = new AtomicInteger(); Body[] observed = new Body[1];
        Transport transport = request -> {
            int index = count.getAndIncrement(); check(index < calls.size(), "unexpected transport invocation"); Map<String, Object> call = object(calls.get(index));
            check(eq(request.method(), call.get("method")), "method mismatch");
            String path = request.uri().getRawPath() + (request.uri().getRawQuery() == null ? "" : "?" + request.uri().getRawQuery());
            check(URLDecoder.decode(path, StandardCharsets.UTF_8).equals(URLDecoder.decode(text(call.get("path")), StandardCharsets.UTF_8)), "path mismatch");
            field(call, "headers").forEach((key, value) -> check(eq(request.headers().get(key), value), "header " + key));
            check(eq(request.body() == null ? null : Json.parse(request.body()), call.get("body")), "body mismatch");
            if (Boolean.TRUE.equals(test.get("lost"))) throw new IOException("synthetic lost reply");
            Map<String, String> headers = new HashMap<>(); headers.put("EzLLMRouter-Contract-Version", test.containsKey("wire") ? text(test.get("wire")) : "0.2"); headers.put("EzLLMRouter-Integration-Version", test.containsKey("version") ? text(test.get("version")) : "1");
            field(test, "response_headers").forEach((key, value) -> headers.put(key, text(value)));
            observed[0] = new Body(test.containsKey("raw") ? Base64.getDecoder().decode(text(test.get("raw"))) : Json.bytes(test.get("response")));
            return new Transport.Response(test.containsKey("status") ? (int) number(test.get("status")) : 200, headers, observed[0]);
        };
        String version = test.containsKey("version") ? text(test.get("version")) : "1";
        try (EzLLMRouterClient client = new EzLLMRouterClient("http://synthetic.invalid", "synthetic-token", transport);
             IntegrationClient integration = new IntegrationClient("http://synthetic.invalid", "synthetic-token", version, transport)) {
            try {
                Map<String, Object> result = invoke(client, integration, test); check(Boolean.TRUE.equals(expected.get("ok")), "expected error " + expected.get("code"));
                Object want = test.get("response"); String action = text(test.get("action"));
                if (List.of("start_run", "get_run").contains(action)) want = field(test, "response").get("run");
                if (List.of("report_outcome", "get_outcome_receipt").contains(action)) want = field(test, "response").get("receipt");
                check(eq(result, want), "result mismatch");
            } catch (EzLLMRouterException error) {
                check(eq(error.getCode(), expected.get("code")), "error " + error.getCode() + " != " + expected.get("code"));
                check(eq(error.getRetryGuidance(), expected.get("retry_guidance")), "guidance mismatch");
                check(error.getHttpStatus() == number(expected.get("http_status")), "HTTP status mismatch");
                check(eq(error.getSelector(), expected.get("selector")) && eq(error.getHandle(), expected.get("handle")), "recovery evidence mismatch");
            }
        }
        check(count.get() == calls.size(), "call count");
        if (observed[0] != null) { check(observed[0].closed, "body not closed"); if (List.of("oversize", "compressed").contains(text(test.get("name")))) check(observed[0].reads == 0, "read rejected body"); }
    }
    private static void safety() {
        for (String origin : List.of("file:///tmp/a", "http://u:p@example.com", "http://example.com/path", "http://example.com?", "http://example.com#")) {
            try (EzLLMRouterClient ignored = new EzLLMRouterClient(origin, "token")) { throw new AssertionError("invalid origin accepted by " + ignored.getClass().getSimpleName()); }
            catch (IllegalArgumentException expected) { /* rejected before transport */ }
        }
        for (String json : List.of("{\"a\":1,\"a\":2}", "{\"a\":1.0}", "{\"a\":1e0}", "{\"a\":9007199254740992}", "{\"a\":\"\\ud800\"}")) {
            try { Json.parse(json); throw new AssertionError("invalid JSON accepted"); } catch (IllegalArgumentException expected) { /* strict grammar */ }
        }
        String unicode = "{\"a\":\"é\",\"n\":7,\"z\":\"<>&\u2028\"}";
        check(Json.stringify(Json.parse(unicode)).equals(unicode), "canonical Unicode");
        EzLLMRouterClient closed = new EzLLMRouterClient("http://synthetic.invalid", "token", request -> { throw new AssertionError("closed transport used"); }); closed.close();
        try { closed.getCapabilities(); throw new AssertionError("closed client accepted"); } catch (EzLLMRouterException expected) { check(expected.getCode().equals("CLIENT_CLOSED"), "closed client error"); }
        Transport slow = request -> new Transport.Response(200, Map.of(), new InputStream() {
            @Override public int read() throws IOException { try { Thread.sleep(10000); } catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IOException("interrupted"); } return -1; }
        });
        try (EzLLMRouterClient client = new EzLLMRouterClient("http://synthetic.invalid", "token", Duration.ofMillis(20), slow)) {
            try { client.getCapabilities(); throw new AssertionError("timeout accepted"); } catch (EzLLMRouterException expected) { check(expected.getCode().equals("TRANSPORT_OUTCOME_UNKNOWN"), "body timeout"); }
        }
    }
    public static void main(String[] args) throws IOException {
        if (args[0].equals("--http")) { http(args[1]); return; }
        List<?> cases = array(Json.parse(Files.readAllBytes(Path.of(args[0])))); int failures = 0;
        for (Object raw : cases) { Map<String, Object> test = object(raw); try { parity(test); } catch (AssertionError | RuntimeException error) { failures++; System.err.println(test.get("name") + ": " + error); } }
        safety();
        largeEmbedding(object(cases.stream().filter(row -> eq(object(row).get("name"), "embedding")).findFirst().orElseThrow()));
        check(failures == 0, failures + " parity failures"); System.out.println("Java: " + cases.size() + " contract cases and safety checks passed.");
    }
    private static void http(String origin) {
        for (String mode : List.of("success", "redirect", "compressed", "oversize", "chunked", "truncated", "slow")) {
            try (EzLLMRouterClient client = new EzLLMRouterClient(origin, "synthetic-native-" + mode, Duration.ofMillis(mode.equals("slow") ? 150 : 35000), null)) {
                try {
                    Map<String, Object> result = client.getCapabilities();
                    check(List.of("success", "chunked").contains(mode) && eq(result.get("profile"), "initial_1a@1"), "HTTP response accepted: " + mode);
                } catch (EzLLMRouterException error) {
                    check(!List.of("success", "chunked").contains(mode), "valid HTTP response rejected: " + mode);
                    check(error.getCode().equals(mode.equals("redirect") ? "PROTOCOL_INVALID" : "TRANSPORT_OUTCOME_UNKNOWN") && error.getRetryGuidance().equals("query_first"), "HTTP error: " + mode);
                }
            }
        }
        System.out.println("Java: native HTTP transport checks passed.");
    }
    private static void largeEmbedding(Map<String, Object> fixture) {
        Map<String, Object> test = Json.snapshot(fixture), request = object(array(test.get("args")).get(0)), input = field(request, "input"), profile = field(input, "profile");
        profile.put("dimensions", 2048L); profile.put("profile_id", "profile.new"); profile.put("model_ref", "model.new"); request.put("requested_configuration_ref", "cfg.new");
        Map<String, Object> reply = field(test, "response"), result = field(reply, "result");
        result.put("dimensions", 2048L); result.put("profile_id", "profile.new"); result.put("model_ref", "model.new");
        List<Object> items = new ArrayList<>(), vectors = new ArrayList<>();
        for (int index = 0; index < 25; index++) {
            String id = "item." + index; items.add(Map.of("item_id", id, "text", "synthetic"));
            vectors.add(Map.of("item_id", id, "input_index", (long) index, "values", java.util.Collections.nCopies(2048, "0.1234567890123456")));
        }
        input.put("items", items); result.put("vectors", vectors); byte[] bytes = Json.bytes(reply); check(bytes.length > 1024 * 1024, "large fixture too small");
        AtomicInteger calls = new AtomicInteger();
        Transport transport = sent -> { calls.incrementAndGet(); return new Transport.Response(200, Map.of("EzLLMRouter-Contract-Version", "0.3"), new ByteArrayInputStream(bytes)); };
        try (EzLLMRouterClient client = new EzLLMRouterClient("http://synthetic.invalid", "token", transport)) {
            check(array(field(client.submitEmbedding(request), "result").get("vectors")).size() == 25 && calls.get() == 1, "large result rejected");
        }
    }
}
