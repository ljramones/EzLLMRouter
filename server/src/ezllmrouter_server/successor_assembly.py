"""Explicit reusable assembly for the supported standalone synthetic profile.

The ordinary application remains wire 0.2 unless this composition is called.
The caller owns the qualified isolated executor and finite synthetic authority;
this module never selects a commercial provider or creates credentials.
"""

from __future__ import annotations

from .successor_service import SuccessorService


def attach_standalone_synthetic(
    coordinator,
    *,
    store,
    contexts_by_credential,
    authority,
    executor,
    allowance,
    read_allowed,
    usage_write_allowed,
    clock=None,
    receiver_receipts=None,
):
    if (
        coordinator.store is not store
        or authority.store is not store
        or allowance.store is not store
        or getattr(coordinator, "successor", None) is not None
        or executor is None
        or not contexts_by_credential
        or not callable(read_allowed)
        or not callable(usage_write_allowed)
    ):
        raise ValueError("incomplete or mismatched standalone synthetic assembly")
    kwargs = {"read_allowed": read_allowed, "usage_write_allowed": usage_write_allowed}
    if receiver_receipts is not None:
        kwargs["receiver_receipts"] = receiver_receipts
    if clock is not None:
        kwargs["clock"] = clock
    successor = SuccessorService(
        store, contexts_by_credential, authority, executor, allowance, **kwargs
    )
    coordinator.successor = successor
    return successor
