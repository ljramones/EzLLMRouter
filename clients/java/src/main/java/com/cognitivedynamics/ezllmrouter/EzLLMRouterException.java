package com.cognitivedynamics.ezllmrouter;

import java.util.Map;

/** Protocol or transport failure with query-first recovery evidence. */
public final class EzLLMRouterException extends RuntimeException {
    private static final long serialVersionUID = 1L;
    private final String code;
    private final int httpStatus;
    private final String retryGuidance;
    private final String correlationId;
    private final transient Map<String, Object> selector;
    private final transient Map<String, Object> handle;
    private final String attemptId;
    private final String failureStage;

    EzLLMRouterException(String code, int status, String guidance) { this(code, status, guidance, null, null, null, null, null); }
    EzLLMRouterException(String code, int status, String guidance, String correlation, Map<String, Object> selector, Map<String, Object> handle, String attempt, String stage) {
        super(code); this.code = code; this.httpStatus = status; this.retryGuidance = guidance;
        this.correlationId = correlation; this.selector = copy(selector); this.handle = copy(handle);
        this.attemptId = attempt; this.failureStage = stage;
    }
    private static Map<String, Object> copy(Map<String, Object> value) { return value == null ? null : Json.snapshot(value); }
    public String getCode() { return code; }
    /** Zero means no HTTP status was observed. */
    public int getHttpStatus() { return httpStatus; }
    public String getRetryGuidance() { return retryGuidance; }
    public String getCorrelationId() { return correlationId; }
    public Map<String, Object> getSelector() { return copy(selector); }
    public Map<String, Object> getHandle() { return copy(handle); }
    public Map<String, Object> getWorkKey() { return handle == null ? null : Json.snapshot(Values.field(handle, "work_key")); }
    public String getAttemptId() { return attemptId; }
    public String getFailureStage() { return failureStage; }
}
