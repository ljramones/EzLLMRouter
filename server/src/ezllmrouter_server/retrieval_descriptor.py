"""Exact descriptor and recipe for the adopted synthetic retrieval profile."""

from .records import Record
from .successor_contract import domain_digest


def recipe_for(request: Record, work_hash: str, config: Record, descriptor: Record) -> Record:
    return {
        "work_digest": work_hash,
        "operation": request["operation"],
        "adapter_ref": config["adapter_ref"],
        "route": descriptor["route"],
        "handling_profile": request["handling_profile"],
        "timeout_ms": descriptor["timeout_ms"],
    }


def execution_descriptor(request: Record, work_hash: str, config: Record) -> Record:
    route = (
        "/synthetic/v1/rerank"
        if request["operation"]["type"] == "rerank"
        else "/synthetic/v1/embeddings"
    )
    descriptor = {
        "profile": "retrieval-synthetic@1",
        "method": "POST",
        "route": route,
        "host": "synthetic.invalid",
        "transport": "trusted_sender_tls@1",
        "content_type": "application/json",
        "adapter_ref": config["adapter_ref"],
        "timeout_ms": 5000,
        "max_request_bytes": 262144,
        "max_response_bytes": 65536,
        "handling_profile": request["handling_profile"],
        "retention_seconds": 604800,
        "lifecycle": "synchronous_one_attempt",
        "deadline": request["deadline"],
    }
    descriptor["recipe_digest"] = domain_digest(
        "ezllmrouter-preparation-v1\n", recipe_for(request, work_hash, config, descriptor)
    )
    return descriptor
