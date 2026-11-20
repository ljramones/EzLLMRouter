"""Named state domains; persist and serialize their plain string values."""

from enum import StrEnum


class SubmissionState(StrEnum):
    ADMITTED = "admitted"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    UNKNOWN = "unknown"
    FAILED_BEFORE_TRANSMIT = "failed_before_transmit"
    FAILED_AFTER_TRANSMIT = "failed_after_transmit"
    UNAVAILABLE = "unavailable"


class DispatchState(StrEnum):
    RESERVED = "reserved"
    PREPARED = "prepared"
    INTENT_PERSISTED = "intent_persisted"
    POSSIBLE_SEND = "possible_send"
    SENT = "sent"
    RESPONSE_OBSERVED = "response_observed"
    BLOCKED = "blocked"
    OUTCOME_UNKNOWN = "outcome_unknown"
    FAILED_BEFORE_DISPATCH = "failed_before_dispatch"
    COMMITTED = "committed"
    UNAVAILABLE = "unavailable"


class DeliveryState(StrEnum):
    NONE = "none"
    PENDING = "pending"
    VALID = "valid"
    UNKNOWN = "unknown"
    CANDIDATE_DELIVERED = "candidate_delivered"
    INVALID = "invalid"


class SettlementState(StrEnum):
    UNSETTLED = "unsettled"
    PENDING = "pending"


class CandidateAccess(StrEnum):
    NOT_YET_AVAILABLE = "not_yet_available"
    PRESENT = "present"
    UNAVAILABLE_DUE_FAILURE = "unavailable_due_failure"
    UNKNOWN_OUTCOME = "unknown_outcome"
    NOT_RETAINED = "not_retained"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"


class LaunchState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
