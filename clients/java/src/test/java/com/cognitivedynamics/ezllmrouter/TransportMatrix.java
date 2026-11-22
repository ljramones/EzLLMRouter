package com.cognitivedynamics.ezllmrouter;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;

final class TransportMatrix {
    private TransportMatrix() {}
    static void run(String origin) throws IOException {
        var cases = Values.array(Json.parseObject(Files.readAllBytes(Path.of(System.getenv("EZLLMROUTER_TEST_MATRIX")))).get("cases"));
        if (cases.size() != 28) throw new AssertionError("transport matrix inventory changed");
        for (Object item : cases) {
            Map<String, Object> row = Values.object(item);
            String name = Values.text(row.get("id"));
            String endpoint = name.equals("untrusted_tls") ? System.getenv("EZLLMROUTER_TEST_TLS_ORIGIN") : origin;
            try (var client = new EzLLMRouterClient(endpoint, "synthetic-native-" + name, Duration.ofMillis(((Number) row.get("timeout_ms")).longValue()), null)) {
                try {
                    var result = client.getCapabilities();
                    if (row.get("code") != null || !"initial_1a@1".equals(result.get("profile"))) throw new AssertionError("unexpected HTTP success: " + name);
                } catch (EzLLMRouterException error) {
                    boolean status = Values.array(row.get("http_status")).stream().anyMatch(value -> ((Number) value).intValue() == error.getHttpStatus());
                    if (!java.util.Objects.equals(row.get("code"), error.getCode()) || !row.get("retry_guidance").equals(error.getRetryGuidance()) || !status)
                        throw new AssertionError(name + ": " + error.getCode() + "/" + error.getRetryGuidance() + "/" + error.getHttpStatus());
                }
            }
        }
        System.out.println("Java: " + cases.size() + " shared native HTTP cases passed.");
    }
}
