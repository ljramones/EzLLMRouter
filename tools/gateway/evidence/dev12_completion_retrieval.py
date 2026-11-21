"""dev12_completion_handlers retrieval domain; entry points remain on the facade."""

from __future__ import annotations


def _retrieval_request(runtime, case, vector, suffix, selectors):
    """Make independently keyed, valid requests for controlled receiver modes."""
    from tools.gateway.evidence import dev12_completion_handlers as _api
    from ezllmrouter_server.successor_contract import content_digest

    request = _api._case_request(runtime, case, vector)
    request["work_selector"]["step_id"] += "." + suffix
    if request["operation"]["type"] == "embedding.create":
        request["input"]["items"] = [
            {"item_id": selector, "text": ("Sky", "Earth 🌍", "River")[index % 3]}
            for index, selector in enumerate(selectors)
        ]
    else:
        sample = request["input"]["candidates"][0]
        request["input"]["candidates"] = []
        for index, selector in enumerate(selectors):
            candidate = {
                **sample,
                "candidate_id": selector,
                "text": ("Sky", "Earth 🌍", "River")[index % 3],
            }
            candidate["content_digest"] = content_digest(candidate)
            request["input"]["candidates"].append(candidate)
        request["input"]["top_k"] = min(2, len(selectors))
    return request


def retrieval_workflow(runtime, case):
    """Exercise the normal fixed retrieval sends and controlled invalid replies."""
    from tools.gateway.evidence import dev12_completion_handlers as _api

    scenario = case["scenario_id"]
    if case["variant"] != "composed" or scenario not in {"t51", "t52", "t53", "t54", "t55"}:
        raise NotImplementedError("retrieval workflow variant not implemented")
    from ezllmrouter_server.successor_contract import result_valid

    observations = {}
    supplemental = {}
    before = _api._census(runtime)

    def call(label, vector, selectors, *, mutate=None):
        request = _api._retrieval_request(runtime, case, vector, label, selectors)
        if mutate is not None:
            mutate(request)
        earlier = _api._census(runtime)
        response = _api._post(runtime, request, _api._headers(runtime, vector))
        later = _api._census(runtime)
        status = response["status"] or {}
        aid = response["reply"].get("attempt_id")
        attempt = status.get("attempts", [{}])[0]
        record = {
            "request": request,
            "response": response,
            "before": earlier,
            "after": later,
            "attempt_id": aid,
            "one_arrival": later["receiver_arrivals"] == earlier["receiver_arrivals"] + 1,
            "valid_result": result_valid(attempt.get("result"), request, aid)
            if aid and "result" in attempt
            else False,
        }
        observations[label] = record
        return record

    if scenario == "t51":
        good = call("ordered", "DIRECT_DOCUMENT", ["doc.first", "doc.second", "doc.third"])
        short = call("short", "DIRECT_DOCUMENT", ["doc.result.short", "doc.second"])
        dimension = call("dimension", "DIRECT_DOCUMENT", ["doc.result.dimension"])
        nonfinite = call("nonfinite", "DIRECT_DOCUMENT", ["doc.result.nonfinite"])
        vector = good["response"]["status"].get("attempts", [{}])[0].get("result", {})
        checks = {
            "t51.ordered_batch": (
                good["valid_result"]
                and good["one_arrival"]
                and [row["item_id"] for row in vector.get("vectors", [])]
                == ["doc.first", "doc.second", "doc.third"],
                "Three ordered items yielded exact item/index mapping through one real guarded send",
            ),
            "t51.wrong_count": (
                short["one_arrival"]
                and short["response"]["status"].get("submission_state") == "failed"
                and short["response"]["status"]["attempts"][0]["delivery_state"] == "invalid",
                "Receiver omitted one vector; result validation rejected delivered result",
            ),
            "t51.wrong_dimension": (
                dimension["one_arrival"]
                and dimension["response"]["status"].get("submission_state") == "failed",
                "Receiver returned two-dimensional vector against fixed three-dimensional binding",
            ),
            "t51.nonfinite_vector": (
                nonfinite["one_arrival"]
                and nonfinite["response"]["status"].get("submission_state") == "failed",
                "Receiver returned NaN vector component; result validation rejected it",
            ),
            "t51.no_truncation": (
                good["valid_result"]
                and len(vector.get("vectors", [])) == len(good["request"]["input"]["items"]) == 3,
                "Successful batch preserved all three input items without truncation",
            ),
        }
    elif scenario == "t52":
        wrong_space = call("space", "DIRECT_DOCUMENT", ["doc.result.space"])
        wrong_index = call(
            "index",
            "DIRECT_DOCUMENT",
            ["doc.index"],
            mutate=lambda request: request["input"]["profile"].update(
                {"index_version": "index.wrong"}
            ),
        )
        good = call("compatible", "DIRECT_DOCUMENT", ["doc.compatible"])
        checks = {
            "t52.wrong_vector_space": (
                wrong_space["one_arrival"]
                and wrong_space["response"]["status"].get("submission_state") == "failed",
                "Delivered wrong vector-space profile rejected after guarded arrival",
            ),
            "t52.wrong_index_profile": (
                wrong_index["response"]["http_status"] >= 400
                and wrong_index["after"]["receiver_arrivals"]
                == wrong_index["before"]["receiver_arrivals"],
                "Wrong index version rejected before send",
            ),
            "t52.compatible_positive": (
                good["valid_result"]
                and good["one_arrival"]
                and good["response"]["status"].get("submission_state") == "completed",
                "Correct profile/index pair produced valid delivery",
            ),
        }
    elif scenario == "t53":
        good = call("ordered", "DELEGATED_RERANK", ["doc.first", "doc.second", "doc.third"])
        duplicate = call("duplicate", "DELEGATED_RERANK", ["doc.result.duplicate", "doc.second"])
        beyond = call("range", "DELEGATED_RERANK", ["doc.result.out_of_range"])
        wrong_order = call("order", "DELEGATED_RERANK", ["doc.result.order", "doc.second"])
        checks = {
            "t53.valid_rerank": (
                good["one_arrival"]
                and good["valid_result"]
                and good["response"]["status"].get("submission_state") == "completed",
                "Ordered top-k rerank result passed exact rank/index/candidate binding",
            ),
            "t53.malformed_duplicate": (
                duplicate["one_arrival"]
                and duplicate["response"]["status"].get("submission_state") == "failed",
                "Duplicate candidate in delivered ranking rejected",
            ),
            "t53.out_of_range": (
                beyond["one_arrival"]
                and beyond["response"]["status"].get("submission_state") == "failed",
                "Out-of-range candidate index in delivered ranking rejected",
            ),
            "t53.wrong_order": (
                wrong_order["one_arrival"]
                and wrong_order["response"]["status"].get("submission_state") == "failed",
                "Ascending score order in delivered ranking rejected",
            ),
        }
    elif scenario == "t54":
        failed = call("failed", "DELEGATED_RERANK", ["doc.failure.known"])
        unknown = call("unknown", "DELEGATED_RERANK", ["doc.unknown.recoverable"])
        unknown_sid = unknown["response"]["reply"].get("handle", {}).get("submission_id")
        if not unknown_sid:
            raise AssertionError("rerank unknown outcome lacks admitted submission")
        paused = _api._census(runtime)
        collected = runtime.successor.collect_receiver_receipt(
            unknown_sid, _api._trusted(runtime, "DELEGATED_RERANK")
        )
        resumed = runtime.successor.resume_campaign(
            unknown_sid,
            _api._trusted(runtime, "DELEGATED_RERANK"),
            "test controlled rerank unknown receipt",
        )
        after_correction = _api._census(runtime)
        supplemental = {
            "paused": paused,
            "receipt_collection": collected,
            "resume": resumed,
            "after_correction": after_correction,
        }
        status = failed["response"]["status"]
        usage = status.get("attempts", [{}])[0].get("usage_revision", {})
        checks = {
            "t54.rerank_failure_unknown": (
                failed["one_arrival"]
                and status.get("submission_state") == "failed"
                and status.get("attempts", [{}])[0].get("delivery_state") == "invalid"
                and usage.get("cost_status") == "calculated"
                and unknown["one_arrival"]
                and unknown["response"]["status"].get("submission_state") == "unknown"
                and paused["campaign"]["paused"]
                and collected == "accepted"
                and resumed.get("decision") == "resumed",
                "Failed known-charge and unknown-outcome reranks retain separate delivery and financial states",
            ),
            "t54.labelled_degradation": (
                status.get("attempts", [{}])[0].get("failure", {}).get("code") == "RESULT_INVALID"
                and status.get("candidate_access") == "unavailable_due_failure",
                "Failure is visibly labelled and does not masquerade as a successful fallback",
            ),
            "t54.no_hidden_second_call": (
                failed["after"]["receiver_arrivals"] == failed["before"]["receiver_arrivals"] + 1
                and failed["after"]["guard_ownership"] == failed["before"]["guard_ownership"] + 1
                and after_correction["receiver_arrivals"] == paused["receiver_arrivals"]
                and after_correction["campaign"]["possible_send_count"]
                == paused["campaign"]["possible_send_count"],
                "Each rerank used one guarded send; historical correction sent nothing",
            ),
        }
    else:
        document = call("document", "DIRECT_DOCUMENT", ["doc.ingest"])
        query = call("query", "AUTONOMOUS_QUERY", ["doc.query"])
        rerank = call("rerank", "DELEGATED_RERANK", ["doc.rank"])
        completed = all(
            row["valid_result"] and row["response"]["status"].get("submission_state") == "completed"
            for row in (document, query, rerank)
        )
        distinct_attempts = {row["attempt_id"] for row in (document, query, rerank)}
        checks = {
            "t55.ingest_once": (
                completed
                and document["one_arrival"]
                and document["request"]["input"]["role"] == "document",
                "Document ingestion creates one isolated guarded embedding attempt",
            ),
            "t55.distinct_query_rerank": (
                completed
                and query["request"]["input"]["role"] == "query"
                and rerank["request"]["operation"]["type"] == "rerank"
                and len(distinct_attempts) == 3,
                "Query embedding and rerank are distinct operations and attempts",
            ),
            "t55.unique_allocation": (
                completed
                and len(distinct_attempts) == 3
                and all(row["one_arrival"] for row in (document, query, rerank)),
                "Each operation owns one unique attempt, reservation and receiver arrival",
            ),
        }

    after = _api._census(runtime)
    stages = {
        "admission": {"new_submissions": after["submissions"] - before["submissions"]},
        "receiver": {"new_arrivals": after["receiver_arrivals"] - before["receiver_arrivals"]},
        "delivery": {
            label: row["response"]["status"].get("submission_state", "absent")
            if row["response"]["status"]
            else "rejected"
            for label, row in observations.items()
        },
        "settlement": {
            label: row["response"]["status"]
            .get("attempts", [{}])[0]
            .get("settlement_state", "absent")
            if row["response"]["status"]
            else "not_admitted"
            for label, row in observations.items()
        },
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {"runs": observations, "supplemental": supplemental, "before": before, "after": after},
        next((row["attempt_id"] for row in observations.values() if row["attempt_id"]), "none"),
    )
