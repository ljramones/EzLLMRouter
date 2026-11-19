package ezllmrouter

import (
	"math/big"
	"regexp"
	"strconv"
	"strings"
)

var decimalPattern = regexp.MustCompile(`^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?$`)

func decimal(v any, score bool) *big.Rat {
	s, ok := v.(string)
	if !ok || !decimalPattern.MatchString(s) {
		return nil
	}
	parts := strings.Split(strings.ToLower(s), "e")
	mantissa := parts[0]
	exponent := 0
	if len(parts) == 2 {
		exponent, _ = strconv.Atoi(parts[1])
	}
	digits := strings.TrimLeft(strings.NewReplacer("-", "", ".", "").Replace(mantissa), "0")
	if len(digits) > 17 || exponent < -100 || exponent > 100 {
		return nil
	}
	n, ok := new(big.Rat).SetString(mantissa)
	if !ok || n.Sign() == 0 && strings.HasPrefix(s, "-") {
		return nil
	}
	power := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(abs(exponent))), nil)
	if exponent < 0 {
		n.Quo(n, new(big.Rat).SetInt(power))
	} else {
		n.Mul(n, new(big.Rat).SetInt(power))
	}
	if n.Cmp(big.NewRat(-1000000, 1)) < 0 || n.Cmp(big.NewRat(1000000, 1)) > 0 || score && (n.Sign() < 0 || n.Cmp(big.NewRat(1, 1)) > 0) {
		return nil
	}
	return n
}
func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}
func resultValid(v Object, attempt any, request Object) bool {
	if !named(v, "0.3", "Result") || v["attempt_id"] != attempt || request != nil && !equal(v["operation"], request["operation"]) {
		return false
	}
	input := field(request, "input")
	if field(v, "operation")["type"] == "embedding.create" {
		vectors := array(v["vectors"])
		for i, raw := range vectors {
			vector := object(raw)
			if integer(vector["input_index"]) != int64(i) || int64(len(array(vector["values"]))) != integer(v["dimensions"]) {
				return false
			}
			for _, n := range array(vector["values"]) {
				if decimal(n, false) == nil {
					return false
				}
			}
		}
		if request == nil {
			return true
		}
		profile := field(input, "profile")
		if v["profile_id"] != profile["profile_id"] || v["model_ref"] != profile["model_ref"] || v["dimensions"] != profile["dimensions"] || len(vectors) != len(array(input["items"])) {
			return false
		}
		for i, raw := range vectors {
			if object(raw)["item_id"] != object(array(input["items"])[i])["item_id"] {
				return false
			}
		}
		return true
	}
	ranking := array(v["results"])
	seen := map[string]bool{}
	var previous *big.Rat
	var previousIndex int64
	for i, raw := range ranking {
		item := object(raw)
		score := decimal(item["score"], true)
		id := str(item["candidate_id"])
		index := integer(item["input_index"])
		if integer(item["rank"]) != int64(i+1) || score == nil || seen[id] || previous != nil && (previous.Cmp(score) < 0 || previous.Cmp(score) == 0 && previousIndex > index) {
			return false
		}
		seen[id] = true
		previous = score
		previousIndex = index
		if request != nil {
			candidates := array(input["candidates"])
			if index < 0 || index >= int64(len(candidates)) || id != str(object(candidates[index])["candidate_id"]) {
				return false
			}
		}
	}
	return request == nil || (v["ranking_profile_id"] == input["ranking_profile_id"] && int64(len(ranking)) == integer(input["top_k"]))
}

var errorHTTP = map[string]int{"UNSUPPORTED_VERSION": 426, "MALFORMED_JSON": 400, "SCHEMA_INVALID": 400, "LIMIT_EXCEEDED": 413, "SEMANTIC_INVALID": 422, "CAPABILITY_UNSUPPORTED": 422, "WORK_CONFLICT": 409, "WORK_VERSION_CONFLICT": 409, "NOT_FOUND_OR_FORBIDDEN": 404, "POLICY_DENIED": 403, "FINANCIAL_AUTH_REQUIRED": 403, "PLAN_INVALID_OR_STALE": 409, "FDC_REJECTED": 409, "INTENT_PERSIST_FAILED": 503, "RESULT_INVALID": 502, "USAGE_UNKNOWN": 502}

func successorError(v Object, status int, kind string) bool {
	if !named(v, "0.3", "ErrorResponse") {
		return false
	}
	code, guidance := str(v["code"]), str(v["retry_guidance"])
	if status == 401 {
		return code == "POLICY_DENIED" && guidance == "never"
	}
	if errorHTTP[code] != status {
		return false
	}
	if code == "INTENT_PERSIST_FAILED" {
		return guidance == "query_first"
	}
	if code == "WORK_CONFLICT" || code == "WORK_VERSION_CONFLICT" {
		return guidance == "never"
	}
	return code != "POLICY_DENIED" || guidance != "query_first" || kind == "submit"
}
func successorValid(v Object, status int, kind string, request Object) bool {
	name := "SubmitReply"
	if kind == "status" {
		name = "StatusSnapshot"
	}
	if !named(v, "0.3", name) {
		return false
	}
	if kind == "submit" {
		switch v["state"] {
		case "completed":
			return status == 200 && resultValid(field(v, "result"), v["attempt_id"], request)
		case "pending", "outcome_unknown":
			return status == 202
		case "failed":
			code := str(field(v, "error")["code"])
			expected := 0
			if v["failure_stage"] == "before_send" {
				switch code {
				case "INTENT_PERSIST_FAILED":
					expected = 503
				case "FDC_REJECTED", "PLAN_INVALID_OR_STALE":
					expected = 409
				}
			} else if code == "RESULT_INVALID" || code == "USAGE_UNKNOWN" {
				expected = 502
			}
			return expected == status && successorError(field(v, "error"), status, "submit")
		}
		return false
	}
	attempts := array(v["attempts"])
	if status != 200 || len(attempts) != 1 {
		return false
	}
	a := object(attempts[0])
	usage := field(a, "usage_revision")
	if usage != nil {
		if usage["attempt_id"] != a["attempt_id"] || a["settlement_state"] != usage["cost_status"] {
			return false
		}
		if usage["cost_status"] == "unknown" {
			if has(usage, "amount_decimal") {
				return false
			}
		} else {
			components := array(usage["components"])
			if len(components) == 0 {
				return false
			}
			part := object(components[0])
			if part["presence"] != "known" || part["evidence"] != "reported" || !positive(part["quantity"]) || !has(usage, "amount_decimal") {
				return false
			}
		}
	} else if a["settlement_state"] != "pending" {
		return false
	}
	if has(a, "result") && !resultValid(field(a, "result"), a["attempt_id"], nil) {
		return false
	}
	switch v["submission_state"] {
	case "completed":
		return a["delivery_state"] == "valid" && (v["candidate_access"] == "present" && has(a, "result") || v["candidate_access"] == "expired" && !has(a, "result"))
	case "failed":
		return v["candidate_access"] == "unavailable_due_failure" && has(a, "failure") && !has(a, "result") && (a["delivery_state"] == "invalid" || a["delivery_state"] == "pending")
	case "unknown":
		return v["candidate_access"] == "unknown_outcome" && a["dispatch_state"] == "possible_send" && a["delivery_state"] == "unknown" && !has(a, "result")
	default:
		return v["candidate_access"] == "not_yet_available" && a["delivery_state"] == "pending" && !has(a, "result")
	}
}
