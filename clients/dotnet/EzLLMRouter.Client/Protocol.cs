using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using static CognitiveDynamics.EzLLMRouter.Values;

namespace CognitiveDynamics.EzLLMRouter;

internal static class Protocol
{
    internal static readonly string[] SelectorKeys = ["task_id", "step_id", "step_revision", "execution_generation"];
    internal static EzLLMRouterException Invalid() => new("SCHEMA_INVALID");
    internal static JsonObject Snapshot(JsonObject value)
    {
        try { return ProtocolJson.Snapshot(value); }
        catch (Exception error) when (error is System.Text.Json.JsonException or ArgumentException or InvalidOperationException) { throw Invalid(); }
    }
    internal static JsonObject? MatchingHandle(JsonObject value, JsonObject? selector, string version)
    {
        var handle = At(value, "handle") as JsonObject;
        if (selector is null || !Schema.Named(handle, version, version == "0.3" ? "Handle" : "SubmissionHandle")) return null;
        bool matches = Has(selector, "submission_id") ? Eq(At(handle, "submission_id"), At(selector, "submission_id"))
            : SelectorKeys.All(key => Eq(At(At(handle, "work_key"), key), At(selector, key)));
        return matches ? handle : null;
    }
    internal static EzLLMRouterException Bad(int status, JsonObject? selector, JsonObject? handle) => new("INTERNAL_UNAVAILABLE", status, "query_first", selector) { Handle = handle?.DeepClone() as JsonObject };
    internal static EzLLMRouterException Evidence(JsonNode? evidence, int status, JsonObject? selector, JsonObject? handle, JsonObject envelope) => new(Text(At(evidence, "code")), status, Text(At(evidence, "retry_guidance")), selector)
    { CorrelationId = Text(At(evidence, "correlation_id")), Handle = handle?.DeepClone() as JsonObject,
      AttemptId = Has(envelope, "attempt_id") ? Text(At(envelope, "attempt_id")) : null,
      FailureStage = Has(envelope, "failure_stage") ? Text(At(envelope, "failure_stage")) : null };

    private static bool Usage(JsonNode? value, JsonNode? attempt)
    {
        if (!Is(At(value, "state"), "available")) return true;
        var revision = At(value, "revision");
        return Eq(At(revision, "attempt_id"), attempt) && (!Has(revision, "previous_revision") || Number(At(revision, "previous_revision")) < Number(At(revision, "revision")));
    }
    private static bool Candidate(JsonNode? value)
    {
        if (!Usage(At(value, "usage"), At(value, "attempt_id"))) return false;
        var ids = new HashSet<string>(); var calls = new HashSet<string>(); bool tool = false;
        foreach (var block in Items(At(value, "output_blocks")))
        {
            if (!ids.Add(Text(At(block, "block_id")))) return false;
            if (Is(At(block, "kind"), "tool_call")) { tool = true; if (!calls.Add(Text(At(block, "call_id")))) return false; }
        }
        return !Is(At(value, "finish_reason"), "tool_calls") || tool;
    }
    internal static bool Wire02(JsonObject value, int status, string kind)
    {
        string name = kind switch { "submit" => "SubmitReply", "status" => "StatusSnapshot", _ => "CapabilityResponse" };
        if (!Schema.Named(value, "0.2", name)) return false;
        if (kind == "capabilities") return status == 200 && !Items(At(value, "supported_features")).Any(feature => Items(At(value, "disabled_features")).Any(other => Eq(feature, other)));
        var generation = At(At(At(value, "handle"), "work_key"), "execution_generation");
        if (kind == "submit") return Text(At(value, "state")) switch
        {
            "delivered" => status == 200 && Candidate(At(value, "candidate")) && Eq(At(At(value, "candidate"), "execution_generation"), generation),
            "pending" => status == 202, "failed" or "rejected" => status >= 400, _ => false
        };
        if (status != 200) return false;
        var attempts = Items(At(value, "attempts")).ToArray(); var seen = new HashSet<string>();
        foreach (var attempt in attempts)
            if (!seen.Add(Text(At(attempt, "attempt_id"))) || !Eq(At(attempt, "execution_generation"), generation) || !Usage(At(attempt, "usage"), At(attempt, "attempt_id"))) return false;
        if (Has(value, "terminal_attempt_id") && !seen.Contains(Text(At(value, "terminal_attempt_id")))) return false;
        if (Is(At(value, "candidate_access"), "present"))
        {
            var candidate = At(value, "candidate");
            if (!Candidate(candidate) || !Eq(At(candidate, "execution_generation"), generation)) return false;
            return attempts.Any(attempt => Eq(At(attempt, "attempt_id"), At(candidate, "attempt_id")) && Eq(At(At(attempt, "usage"), "state"), At(At(candidate, "usage"), "state"))
                && (!Is(At(At(attempt, "usage"), "state"), "available") || Eq(At(At(At(attempt, "usage"), "revision"), "revision"), At(At(At(candidate, "usage"), "revision"), "revision"))));
        }
        return true;
    }

    private readonly record struct ExactDecimal(BigInteger Coefficient, int Exponent)
    {
        internal int Compare(ExactDecimal other)
        {
            int exponent = Math.Min(Exponent, other.Exponent);
            return (Coefficient * BigInteger.Pow(10, Exponent - exponent)).CompareTo(other.Coefficient * BigInteger.Pow(10, other.Exponent - exponent));
        }
    }
    private static ExactDecimal? DecimalValue(JsonNode? value, bool score)
    {
        string text = Text(value);
        if (!Regex.IsMatch(text, @"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$", RegexOptions.CultureInvariant)) return null;
        var parts = text.ToLowerInvariant().Split('e'); int exponent = parts.Length == 2 ? int.Parse(parts[1], CultureInfo.InvariantCulture) : 0;
        string digits = parts[0].Replace("-", "").Replace(".", "").TrimStart('0');
        if (digits.Length > 17 || Math.Abs(exponent) > 100 || digits.Length == 0 && text.StartsWith('-')) return null;
        BigInteger number = digits.Length == 0 ? BigInteger.Zero : BigInteger.Parse(digits, CultureInfo.InvariantCulture);
        if (text.StartsWith('-')) number = -number;
        int dot = parts[0].IndexOf('.'); if (dot >= 0) exponent -= parts[0].Length - dot - 1;
        var result = new ExactDecimal(number, exponent);
        if (result.Compare(new(-1000000, 0)) < 0 || result.Compare(new(1000000, 0)) > 0 || score && (result.Compare(new(0, 0)) < 0 || result.Compare(new(1, 0)) > 0)) return null;
        return result;
    }
    private static bool Result(JsonNode? value, JsonNode? attempt, JsonObject? request)
    {
        if (!Schema.Named(value, "0.3", "Result") || !Eq(At(value, "attempt_id"), attempt) || request is not null && !Eq(At(value, "operation"), At(request, "operation"))) return false;
        var input = At(request, "input");
        if (Is(At(At(value, "operation"), "type"), "embedding.create"))
        {
            var vectors = Items(At(value, "vectors")).ToArray();
            for (int i = 0; i < vectors.Length; i++)
                if (Number(At(vectors[i], "input_index")) != i || Items(At(vectors[i], "values")).Count() != Number(At(value, "dimensions")) || Items(At(vectors[i], "values")).Any(coordinate => DecimalValue(coordinate, false) is null)) return false;
            if (request is null) return true;
            var profile = At(input, "profile"); var items = Items(At(input, "items")).ToArray();
            return new[] { "profile_id", "model_ref", "dimensions" }.All(key => Eq(At(value, key), At(profile, key))) && vectors.Length == items.Length && vectors.Select((vector, i) => Eq(At(vector, "item_id"), At(items[i], "item_id"))).All(match => match);
        }
        var ranking = Items(At(value, "results")).ToArray(); var seen = new HashSet<string>(); ExactDecimal? previous = null; long previousIndex = -1;
        for (int i = 0; i < ranking.Length; i++)
        {
            var item = ranking[i]; var score = DecimalValue(At(item, "score"), true); long index = Number(At(item, "input_index"));
            if (Number(At(item, "rank")) != i + 1 || score is null || !seen.Add(Text(At(item, "candidate_id"))) || previous.HasValue && (previous.Value.Compare(score.Value) < 0 || previous.Value.Compare(score.Value) == 0 && previousIndex > index)) return false;
            previous = score; previousIndex = index;
            if (request is not null) { var candidates = Items(At(input, "candidates")).ToArray(); if (index < 0 || index >= candidates.Length || !Eq(At(item, "candidate_id"), At(candidates[(int)index], "candidate_id"))) return false; }
        }
        return request is null || Eq(At(value, "ranking_profile_id"), At(input, "ranking_profile_id")) && ranking.Length == Number(At(input, "top_k"));
    }
    private static readonly Dictionary<string, int> ErrorHttp = new()
    {
        ["UNSUPPORTED_VERSION"] = 426, ["MALFORMED_JSON"] = 400, ["SCHEMA_INVALID"] = 400, ["LIMIT_EXCEEDED"] = 413, ["SEMANTIC_INVALID"] = 422,
        ["CAPABILITY_UNSUPPORTED"] = 422, ["WORK_CONFLICT"] = 409, ["WORK_VERSION_CONFLICT"] = 409, ["NOT_FOUND_OR_FORBIDDEN"] = 404,
        ["POLICY_DENIED"] = 403, ["FINANCIAL_AUTH_REQUIRED"] = 403, ["PLAN_INVALID_OR_STALE"] = 409, ["FDC_REJECTED"] = 409,
        ["INTENT_PERSIST_FAILED"] = 503, ["RESULT_INVALID"] = 502, ["USAGE_UNKNOWN"] = 502
    };
    internal static bool SuccessorError(JsonNode? value, int status, string kind)
    {
        if (!Schema.Named(value, "0.3", "ErrorResponse")) return false;
        string code = Text(At(value, "code")), guidance = Text(At(value, "retry_guidance"));
        if (status == 401) return code == "POLICY_DENIED" && guidance == "never";
        if (!ErrorHttp.TryGetValue(code, out int expected) || status != expected) return false;
        return code switch { "INTENT_PERSIST_FAILED" => guidance == "query_first", "WORK_CONFLICT" or "WORK_VERSION_CONFLICT" => guidance == "never", "POLICY_DENIED" when guidance == "query_first" => kind == "submit", _ => true };
    }
    internal static bool Successor(JsonObject value, int status, string kind, JsonObject? request)
    {
        if (!Schema.Named(value, "0.3", kind == "submit" ? "SubmitReply" : "StatusSnapshot")) return false;
        if (kind == "submit")
        {
            if (Is(At(value, "state"), "completed")) return status == 200 && Result(At(value, "result"), At(value, "attempt_id"), request);
            if (One(At(value, "state"), "pending", "outcome_unknown")) return status == 202;
            string code = Text(At(At(value, "error"), "code"));
            int expected = Is(At(value, "failure_stage"), "before_send") ? code switch { "INTENT_PERSIST_FAILED" => 503, "FDC_REJECTED" or "PLAN_INVALID_OR_STALE" => 409, _ => 0 } : code is "RESULT_INVALID" or "USAGE_UNKNOWN" ? 502 : 0;
            return status == expected && SuccessorError(At(value, "error"), status, "submit");
        }
        var attempts = Items(At(value, "attempts")).ToArray(); if (status != 200 || attempts.Length != 1) return false;
        var attempt = attempts[0]; var usage = At(attempt, "usage_revision");
        if (Has(attempt, "usage_revision"))
        {
            if (!Eq(At(usage, "attempt_id"), At(attempt, "attempt_id")) || !Eq(At(attempt, "settlement_state"), At(usage, "cost_status"))) return false;
            if (Is(At(usage, "cost_status"), "unknown")) { if (Has(usage, "amount_decimal")) return false; }
            else
            {
                var component = Items(At(usage, "components")).FirstOrDefault();
                if (!Is(At(component, "presence"), "known") || !Is(At(component, "evidence"), "reported") || !Positive(At(component, "quantity")) || !Has(usage, "amount_decimal")) return false;
            }
        }
        else if (!Is(At(attempt, "settlement_state"), "pending")) return false;
        if (Has(attempt, "result") && !Result(At(attempt, "result"), At(attempt, "attempt_id"), null)) return false;
        return Text(At(value, "submission_state")) switch
        {
            "completed" => Is(At(attempt, "delivery_state"), "valid") && (Is(At(value, "candidate_access"), "present") && Has(attempt, "result") || Is(At(value, "candidate_access"), "expired") && !Has(attempt, "result")),
            "failed" => Is(At(value, "candidate_access"), "unavailable_due_failure") && Has(attempt, "failure") && !Has(attempt, "result") && One(At(attempt, "delivery_state"), "invalid", "pending"),
            "unknown" => Is(At(value, "candidate_access"), "unknown_outcome") && Is(At(attempt, "dispatch_state"), "possible_send") && Is(At(attempt, "delivery_state"), "unknown") && !Has(attempt, "result"),
            _ => Is(At(value, "candidate_access"), "not_yet_available") && Is(At(attempt, "delivery_state"), "pending") && !Has(attempt, "result")
        };
    }
}
