package com.cognitivedynamics.ezllmrouter;

import static com.cognitivedynamics.ezllmrouter.Values.*;

import java.math.BigDecimal;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class Protocol {
    private Protocol() {}
    static final List<String> SELECTOR = List.of("task_id", "step_id", "step_revision", "execution_generation");
    static Map<String, Object> matchingHandle(Map<String, Object> value, Map<String, Object> selector, String version) {
        Map<String, Object> handle = field(value, "handle");
        if (selector == null || !Schema.named(handle, version, version.equals("0.3") ? "Handle" : "SubmissionHandle")) return null;
        if (selector.containsKey("submission_id")) return eq(handle.get("submission_id"), selector.get("submission_id")) ? handle : null;
        return SELECTOR.stream().allMatch(key -> eq(field(handle, "work_key").get(key), selector.get(key))) ? handle : null;
    }
    static EzLLMRouterException invalid() { return Connection.error("SCHEMA_INVALID", 0, "never", null); }
    static EzLLMRouterException bad(int status, Map<String, Object> selector, Map<String, Object> handle) {
        return new EzLLMRouterException("INTERNAL_UNAVAILABLE", status, "query_first", null, selector, handle, null, null);
    }
    static EzLLMRouterException evidence(Map<String, Object> error, int status, Map<String, Object> selector, Map<String, Object> handle, Map<String, Object> envelope) {
        return new EzLLMRouterException(text(error.get("code")), status, text(error.get("retry_guidance")), text(error.get("correlation_id")), selector, handle,
            envelope.get("attempt_id") instanceof String s ? s : null, envelope.get("failure_stage") instanceof String s ? s : null);
    }
    private static boolean usage(Map<String, Object> value, Object attempt) {
        if (!eq(value.get("state"), "available")) return true;
        Map<String, Object> revision = field(value, "revision");
        return eq(revision.get("attempt_id"), attempt) && (!revision.containsKey("previous_revision") || number(revision.get("previous_revision")) < number(revision.get("revision")));
    }
    private static boolean candidate(Map<String, Object> value) {
        if (!usage(field(value, "usage"), value.get("attempt_id"))) return false;
        Set<Object> blocks = new HashSet<>(), calls = new HashSet<>(); boolean tool = false;
        for (Object raw : array(value.get("output_blocks"))) {
            Map<String, Object> block = object(raw); if (!blocks.add(block.get("block_id"))) return false;
            if (eq(block.get("kind"), "tool_call")) { tool = true; if (!calls.add(block.get("call_id"))) return false; }
        }
        return !eq(value.get("finish_reason"), "tool_calls") || tool;
    }
    static boolean wire02(Map<String, Object> value, int status, String kind) {
        String name = switch (kind) { case "submit" -> "SubmitReply"; case "status" -> "StatusSnapshot"; default -> "CapabilityResponse"; };
        if (!Schema.named(value, "0.2", name)) return false;
        if (kind.equals("capabilities")) return status == 200 && array(value.get("supported_features")).stream().noneMatch(array(value.get("disabled_features"))::contains);
        Object generation = field(field(value, "handle"), "work_key").get("execution_generation");
        if (kind.equals("submit")) return switch (text(value.get("state"))) {
            case "delivered" -> status == 200 && candidate(field(value, "candidate")) && eq(field(value, "candidate").get("execution_generation"), generation);
            case "pending" -> status == 202;
            case "failed", "rejected" -> status >= 400;
            default -> false;
        };
        if (status != 200) return false;
        Set<Object> seen = new HashSet<>(); List<?> attempts = array(value.get("attempts"));
        for (Object raw : attempts) {
            Map<String, Object> attempt = object(raw);
            if (!seen.add(attempt.get("attempt_id")) || !eq(attempt.get("execution_generation"), generation) || !usage(field(attempt, "usage"), attempt.get("attempt_id"))) return false;
        }
        if (value.containsKey("terminal_attempt_id") && !seen.contains(value.get("terminal_attempt_id"))) return false;
        if (eq(value.get("candidate_access"), "present")) {
            Map<String, Object> result = field(value, "candidate");
            if (!candidate(result) || !eq(result.get("execution_generation"), generation)) return false;
            return attempts.stream().map(Values::object).anyMatch(attempt -> {
                Map<String, Object> a = field(attempt, "usage"), b = field(result, "usage");
                return eq(attempt.get("attempt_id"), result.get("attempt_id")) && eq(a.get("state"), b.get("state")) && (!eq(a.get("state"), "available") || eq(field(a, "revision").get("revision"), field(b, "revision").get("revision")));
            });
        }
        return true;
    }
    private static BigDecimal decimal(Object raw, boolean score) {
        if (!(raw instanceof String value) || !value.matches("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]{1,3})?")) return null;
        String[] parts = value.toLowerCase(java.util.Locale.ROOT).split("e");
        if (parts[0].replace("-", "").replace(".", "").replaceFirst("^0+", "").length() > 17 || parts.length == 2 && Math.abs(Integer.parseInt(parts[1])) > 100) return null;
        BigDecimal number = new BigDecimal(value);
        if (number.signum() == 0 && value.startsWith("-") || number.abs().compareTo(BigDecimal.valueOf(1000000)) > 0 || score && (number.signum() < 0 || number.compareTo(BigDecimal.ONE) > 0)) return null;
        return number;
    }
    private static boolean result(Map<String, Object> value, Object attempt, Map<String, Object> request) {
        if (!Schema.named(value, "0.3", "Result") || !eq(value.get("attempt_id"), attempt) || request != null && !eq(value.get("operation"), request.get("operation"))) return false;
        Map<String, Object> input = request == null ? Map.of() : field(request, "input");
        if (eq(field(value, "operation").get("type"), "embedding.create")) {
            List<?> vectors = array(value.get("vectors"));
            for (int i = 0; i < vectors.size(); i++) {
                Map<String, Object> vector = object(vectors.get(i)); List<?> coordinates = array(vector.get("values"));
                if (number(vector.get("input_index")) != i || coordinates.size() != number(value.get("dimensions")) || coordinates.stream().anyMatch(n -> decimal(n, false) == null)) return false;
            }
            if (request == null) return true;
            Map<String, Object> profile = field(input, "profile"); List<?> items = array(input.get("items"));
            if (!eq(value.get("profile_id"), profile.get("profile_id")) || !eq(value.get("model_ref"), profile.get("model_ref")) || !eq(value.get("dimensions"), profile.get("dimensions")) || vectors.size() != items.size()) return false;
            for (int i = 0; i < vectors.size(); i++) if (!eq(object(vectors.get(i)).get("item_id"), object(items.get(i)).get("item_id"))) return false;
            return true;
        }
        List<?> ranking = array(value.get("results")); Set<Object> seen = new HashSet<>(); BigDecimal previous = null; long previousIndex = -1;
        for (int i = 0; i < ranking.size(); i++) {
            Map<String, Object> item = object(ranking.get(i)); BigDecimal score = decimal(item.get("score"), true); long index = number(item.get("input_index"));
            if (number(item.get("rank")) != i + 1 || score == null || !seen.add(item.get("candidate_id")) || previous != null && (previous.compareTo(score) < 0 || previous.compareTo(score) == 0 && previousIndex > index)) return false;
            previous = score; previousIndex = index;
            if (request != null) { List<?> candidates = array(input.get("candidates")); if (index < 0 || index >= candidates.size() || !eq(item.get("candidate_id"), object(candidates.get((int) index)).get("candidate_id"))) return false; }
        }
        return request == null || eq(value.get("ranking_profile_id"), input.get("ranking_profile_id")) && ranking.size() == number(input.get("top_k"));
    }
    private static final Map<String, Integer> ERROR_HTTP = Map.ofEntries(
        Map.entry("UNSUPPORTED_VERSION", 426), Map.entry("MALFORMED_JSON", 400), Map.entry("SCHEMA_INVALID", 400), Map.entry("LIMIT_EXCEEDED", 413), Map.entry("SEMANTIC_INVALID", 422), Map.entry("CAPABILITY_UNSUPPORTED", 422), Map.entry("WORK_CONFLICT", 409), Map.entry("WORK_VERSION_CONFLICT", 409), Map.entry("NOT_FOUND_OR_FORBIDDEN", 404), Map.entry("POLICY_DENIED", 403), Map.entry("FINANCIAL_AUTH_REQUIRED", 403), Map.entry("PLAN_INVALID_OR_STALE", 409), Map.entry("FDC_REJECTED", 409), Map.entry("INTENT_PERSIST_FAILED", 503), Map.entry("RESULT_INVALID", 502), Map.entry("USAGE_UNKNOWN", 502));
    static boolean successorError(Map<String, Object> error, int status, String kind) {
        if (!Schema.named(error, "0.3", "ErrorResponse")) return false;
        String code = text(error.get("code")), guidance = text(error.get("retry_guidance"));
        if (status == 401) return code.equals("POLICY_DENIED") && guidance.equals("never");
        if (ERROR_HTTP.getOrDefault(code, 0) != status) return false;
        if (code.equals("INTENT_PERSIST_FAILED")) return guidance.equals("query_first");
        if (List.of("WORK_CONFLICT", "WORK_VERSION_CONFLICT").contains(code)) return guidance.equals("never");
        return !code.equals("POLICY_DENIED") || !guidance.equals("query_first") || kind.equals("submit");
    }
    static boolean successor(Map<String, Object> value, int status, String kind, Map<String, Object> request) {
        if (!Schema.named(value, "0.3", kind.equals("submit") ? "SubmitReply" : "StatusSnapshot")) return false;
        if (kind.equals("submit")) return switch (text(value.get("state"))) {
            case "completed" -> status == 200 && result(field(value, "result"), value.get("attempt_id"), request);
            case "pending", "outcome_unknown" -> status == 202;
            case "failed" -> {
                String code = text(field(value, "error").get("code")); int expected = 0;
                if (eq(value.get("failure_stage"), "before_send")) { if (code.equals("INTENT_PERSIST_FAILED")) expected = 503; else if (List.of("FDC_REJECTED", "PLAN_INVALID_OR_STALE").contains(code)) expected = 409; }
                else if (List.of("RESULT_INVALID", "USAGE_UNKNOWN").contains(code)) expected = 502;
                yield status == expected && successorError(field(value, "error"), status, "submit");
            }
            default -> false;
        };
        List<?> attempts = array(value.get("attempts")); if (status != 200 || attempts.size() != 1) return false;
        Map<String, Object> attempt = object(attempts.get(0)), usage = field(attempt, "usage_revision");
        if (attempt.containsKey("usage_revision")) {
            if (!eq(usage.get("attempt_id"), attempt.get("attempt_id")) || !eq(attempt.get("settlement_state"), usage.get("cost_status"))) return false;
            if (eq(usage.get("cost_status"), "unknown")) { if (usage.containsKey("amount_decimal")) return false; }
            else {
                List<?> components = array(usage.get("components")); if (components.isEmpty()) return false; Map<String, Object> component = object(components.get(0));
                if (!eq(component.get("presence"), "known") || !eq(component.get("evidence"), "reported") || !positive(component.get("quantity")) || !usage.containsKey("amount_decimal")) return false;
            }
        } else if (!eq(attempt.get("settlement_state"), "pending")) return false;
        if (attempt.containsKey("result") && !result(field(attempt, "result"), attempt.get("attempt_id"), null)) return false;
        return switch (text(value.get("submission_state"))) {
            case "completed" -> eq(attempt.get("delivery_state"), "valid") && (eq(value.get("candidate_access"), "present") && attempt.containsKey("result") || eq(value.get("candidate_access"), "expired") && !attempt.containsKey("result"));
            case "failed" -> eq(value.get("candidate_access"), "unavailable_due_failure") && attempt.containsKey("failure") && !attempt.containsKey("result") && List.of("invalid", "pending").contains(text(attempt.get("delivery_state")));
            case "unknown" -> eq(value.get("candidate_access"), "unknown_outcome") && eq(attempt.get("dispatch_state"), "possible_send") && eq(attempt.get("delivery_state"), "unknown") && !attempt.containsKey("result");
            default -> eq(value.get("candidate_access"), "not_yet_available") && eq(attempt.get("delivery_state"), "pending") && !attempt.containsKey("result");
        };
    }
}
