"""Fixed synthetic caller workflows through the installed wire-0.2 client."""

from __future__ import annotations

from copy import deepcopy
import time
import uuid


class DemoRunner:
    def __init__(self, request, scenarios, service_url, token, client_factory=None):
        if client_factory is None:
            from ezllmrouter_client import EzLLMRouterClient

            client_factory = EzLLMRouterClient
        self.request = request
        self.scenarios = scenarios
        self.service_url = service_url
        self.token = token
        self.client_factory = client_factory

    def _candidate(self, client, request, on_handle, no_store=False):
        reply = client.submit(request, {"wait_ms": 3000})
        handle = reply["handle"]["submission_id"]
        on_handle(handle)
        if reply["state"] == "delivered":
            return reply["candidate"], handle
        if reply["state"] != "pending" or no_store:
            raise RuntimeError("DEMO_OUTCOME_UNKNOWN")
        end = time.monotonic() + 8
        while time.monotonic() < end:
            status = client.getStatus({"submission_id": handle})
            if status["candidate_access"] == "present":
                return status["candidate"], handle
            if status["submission_state"] != "admitted":
                raise RuntimeError("DEMO_NO_CANDIDATE")
            time.sleep(0.1)
        raise RuntimeError("DEMO_OUTCOME_UNKNOWN")

    def run(self, kind, on_handle):
        if kind not in ("text", "tool", "no_store_text"):
            raise ValueError("unsupported demo")
        suffix = uuid.uuid4().hex
        request = deepcopy(self.request)
        request["step_id"] = f"step.dev06.{kind}.{suffix}"
        request["execution_generation"] = "gen." + uuid.uuid4().hex
        request["messages"][1]["blocks"][0]["text"] = (
            "Use lookup for synthetic." if kind == "tool" else "Hi"
        )
        if kind == "no_store_text":
            request["messages"][1]["blocks"][0]["source_labels"] = {
                "lineage_ids": ["src.user.no_store"],
                "sensitivity": "confidential",
                "restrictions": ["no.content.store"],
            }
        if kind == "tool":
            request["requested_features"] = ["text", "tools"]
            request["tool_definitions"] = [deepcopy(self.scenarios["tool_definition"])]
            request["tool_choice"] = "auto"
        with self.client_factory(self.service_url, self.token) as client:
            first, first_id = self._candidate(
                client, request, on_handle, no_store=kind == "no_store_text"
            )
            if kind != "tool":
                # The candidate is deliberately not returned to the console.
                return {"submission_ids": [first_id], "caller_lookups": 0}
            if (
                first.get("finish_reason") != "tool_calls"
                or len(first.get("output_blocks", [])) != 1
            ):
                raise RuntimeError("DEMO_TOOL_SHAPE")
            call = first["output_blocks"][0]
            if (
                call.get("kind") != "tool_call"
                or call.get("tool_name") != "lookup"
                or call.get("arguments") != {"key": "synthetic"}
            ):
                raise RuntimeError("DEMO_TOOL_SHAPE")
            # This caller alone executes the fixed harmless lookup.
            result = {"value": "synthetic"}
            followup = deepcopy(request)
            followup["execution_generation"] = "gen." + uuid.uuid4().hex
            followup["messages"].append({"role": "assistant", "blocks": [call]})
            followup["messages"].append(
                {
                    "role": "tool",
                    "blocks": [
                        {
                            "block_id": "block.result.1",
                            "kind": "tool_result",
                            "call_id": call["call_id"],
                            "result_value": result,
                            "source_labels": deepcopy(self.scenarios["result_source_labels"]),
                        }
                    ],
                }
            )
            second, second_id = self._candidate(client, followup, on_handle)
            if second.get("finish_reason") != "stop":
                raise RuntimeError("DEMO_FINAL_SHAPE")
            return {"submission_ids": [first_id, second_id], "caller_lookups": 1}


class ProviderValidationRunner:
    """One explicit, fixed text request through the installed client and trusted path."""

    def __init__(self, request, service_url, token, principal_id, client_factory=None):
        if client_factory is None:
            from ezllmrouter_client import EzLLMRouterClient

            client_factory = EzLLMRouterClient
        self.request = request
        self.service_url = service_url
        self.token = token
        self.principal_id = principal_id
        self.client_factory = client_factory

    def run(self, configuration_ref, operation_id, max_output_tokens, on_handle, token=None):
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32:
            raise ValueError("invalid provider validation output allowance")
        request = deepcopy(self.request)
        request["requested_configuration_ref"] = configuration_ref
        request["step_id"] = "step.provider.validation." + operation_id
        request["execution_generation"] = "gen.provider.validation." + operation_id
        request["messages"][1]["blocks"][0]["text"] = "Say hello."
        request["generation_settings"]["max_output_tokens"] = max_output_tokens
        request["generation_settings"]["total_timeout_ms"] = 10000
        with self.client_factory(self.service_url, token or self.token) as client:
            reply = client.submit(request, {"wait_ms": 15000})
        on_handle(reply["handle"]["submission_id"])
        if reply["state"] == "delivered":
            return {"state": "completed", "candidate": reply["candidate"]}
        if reply["state"] == "pending":
            return {"state": "outcome_unknown"}
        raise RuntimeError("PROVIDER_VALIDATION_REPLY_INVALID")
