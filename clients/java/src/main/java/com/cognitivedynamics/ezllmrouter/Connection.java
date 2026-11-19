package com.cognitivedynamics.ezllmrouter;

import static com.cognitivedynamics.ezllmrouter.Values.*;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.Proxy;
import java.net.ProxySelector;
import java.net.SocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

final class Connection implements AutoCloseable {
    final String origin;
    private final String token;
    private final Duration timeout;
    private final Transport transport;
    private final AtomicBoolean closed = new AtomicBoolean();
    private final ExecutorService executor = Executors.newCachedThreadPool(task -> {
        Thread thread = new Thread(task, "ezllmrouter-client"); thread.setDaemon(true); return thread;
    });

    Connection(String origin, String token, Duration timeout, Transport transport) {
        URI uri;
        try { uri = URI.create(origin); } catch (RuntimeException error) { throw new IllegalArgumentException("HTTP(S) origin required"); }
        if (!List.of("http", "https").contains(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null || !List.of("", "/").contains(uri.getPath()) || token == null || token.isEmpty() || !token.chars().allMatch(c -> c >= 33 && c <= 126) || timeout == null || timeout.isNegative()) throw new IllegalArgumentException("HTTP(S) origin, token and timeout required");
        this.origin = origin.endsWith("/") ? origin.substring(0, origin.length() - 1) : origin;
        this.token = token; this.timeout = timeout;
        this.transport = transport == null ? nativeTransport() : transport;
    }
    private static Transport nativeTransport() {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NEVER).version(HttpClient.Version.HTTP_1_1)
            .proxy(new ProxySelector() {
                @Override public List<Proxy> select(URI uri) { return List.of(Proxy.NO_PROXY); }
                @Override public void connectFailed(URI uri, SocketAddress address, IOException error) { /* No proxy fallback. */ }
            }).build();
        return request -> {
            HttpRequest.Builder builder = HttpRequest.newBuilder(request.uri());
            if (!request.timeout().isZero()) builder.timeout(request.timeout());
            request.headers().forEach(builder::header);
            builder.method(request.method(), request.body() == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofByteArray(request.body()));
            HttpResponse<InputStream> response = client.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
            Map<String, String> headers = new HashMap<>(); response.headers().map().forEach((key, values) -> headers.put(key, String.join(",", values)));
            return new Transport.Response(response.statusCode(), headers, response.body());
        };
    }
    record Reply(Map<String, Object> value, int status) {}
    Reply request(String method, String path, String header, String version, Map<String, Object> body, Map<String, String> extra, int limit, Map<String, Object> selector) {
        if (closed.get()) throw error("CLIENT_CLOSED", 0, "never", selector);
        byte[] bytes;
        try { bytes = body == null ? null : Json.bytes(body); } catch (IllegalArgumentException failure) { throw error("SCHEMA_INVALID", 0, "never", selector); }
        Map<String, String> headers = new HashMap<>(extra);
        headers.put("Authorization", "Bearer " + token); headers.put(header, version); headers.put("Accept-Encoding", "identity");
        if (body != null) headers.put("Content-Type", "application/json");
        Transport.Request request = new Transport.Request(method, URI.create(origin + path), headers, bytes, timeout);
        AtomicReference<Transport.Response> received = new AtomicReference<>();
        Future<Reply> future;
        try {
            future = executor.submit(() -> {
                Transport.Response response = transport.send(request); received.set(response);
                if (response == null) throw new IOException("missing response");
                try (InputStream stream = response.body()) {
                    if (stream == null || !List.of("", "identity").contains(response.header("Content-Encoding").trim().toLowerCase(java.util.Locale.ROOT))) throw new IOException("unsupported response encoding");
                    String declared = response.header("Content-Length"); long length = -1;
                    if (!declared.isEmpty()) {
                        if (!declared.matches("[0-9]+")) throw new IOException("invalid response length");
                        try { length = Long.parseLong(declared); } catch (NumberFormatException failure) { throw new IOException("invalid response length"); }
                        if (length > limit) throw new IOException("response limit");
                    }
                    ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] chunk = new byte[65536];
                    while (true) { int count = stream.read(chunk, 0, Math.min(chunk.length, limit + 1 - out.size())); if (count < 0) break; if (count == 0) continue; out.write(chunk, 0, count); if (out.size() > limit) throw new IOException("response limit"); }
                    if (length >= 0 && out.size() != length) throw new IOException("response length mismatch");
                    Object parsed = Json.parse(out.toByteArray()); Map<String, Object> value = object(parsed);
                    String field = header.equals("EzLLMRouter-Integration-Version") ? "integration_version" : "contract_version";
                    if (!(parsed instanceof Map<?, ?>) || !version.equals(value.get(field)) || !version.equals(response.header(header))) throw error("UNSUPPORTED_VERSION", response.status(), "never", selector);
                    return new Reply(value, response.status());
                }
            });
        } catch (RejectedExecutionException failure) { throw error("CLIENT_CLOSED", 0, "never", selector); }
        try { return timeout.isZero() ? future.get() : future.get(timeout.toNanos(), TimeUnit.NANOSECONDS); }
        catch (InterruptedException failure) { future.cancel(true); closeBody(received.get()); Thread.currentThread().interrupt(); throw unknown(received.get(), selector); }
        catch (TimeoutException failure) { future.cancel(true); closeBody(received.get()); throw unknown(received.get(), selector); }
        catch (ExecutionException failure) { if (failure.getCause() instanceof EzLLMRouterException error) throw error; throw unknown(received.get(), selector); }
    }
    private static void closeBody(Transport.Response response) { if (response != null && response.body() != null) try { response.body().close(); } catch (IOException ignored) { /* Preserve outcome uncertainty. */ } }
    private static EzLLMRouterException unknown(Transport.Response response, Map<String, Object> selector) { return error("TRANSPORT_OUTCOME_UNKNOWN", response == null ? 0 : response.status(), "query_first", selector); }
    static EzLLMRouterException error(String code, int status, String guidance, Map<String, Object> selector) { return new EzLLMRouterException(code, status, guidance, null, selector, null, null, null); }
    @Override public void close() { if (closed.compareAndSet(false, true)) executor.shutdownNow(); }
}
