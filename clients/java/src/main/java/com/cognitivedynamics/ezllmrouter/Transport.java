package com.cognitivedynamics.ezllmrouter;

import java.io.InputStream;
import java.net.URI;
import java.time.Duration;
import java.util.Map;

/** Injectable single-exchange transport. Implementations must not redirect or replay writes. */
@FunctionalInterface
public interface Transport {
    Response send(Request request) throws Exception;

    record Request(String method, URI uri, Map<String, String> headers, byte[] body, Duration timeout) {
        public Request { headers = Map.copyOf(headers); body = body == null ? null : body.clone(); }
        @Override public byte[] body() { return body == null ? null : body.clone(); }
    }
    /** The client owns and closes each returned body, including on invalid responses. */
    record Response(int status, Map<String, String> headers, InputStream body) {
        public Response { headers = Map.copyOf(headers); }
        String header(String name) {
            return headers.entrySet().stream().filter(entry -> entry.getKey().equalsIgnoreCase(name)).map(Map.Entry::getValue).findFirst().orElse("");
        }
    }
}
