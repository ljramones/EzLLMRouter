"""personal_campaign campaign reporting domain; entry points remain on the facade."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from .records import Record
from .database import Row

if TYPE_CHECKING:
    from .personal_campaign import PersonalCampaign


def reconcile_recorded_usage(self: PersonalCampaign, actor: str) -> int:
    """Owner-requested local reconciliation; never replays provider work."""
    from ezllmrouter_server import personal_campaign as _api

    if actor != self.registry.identity.owner_id:
        raise PermissionError("OWNER_REQUIRED")

    def action() -> int:
        changed = 0
        changed_campaigns: set[str] = set()
        rows = self.store.database.execute(
            _api._queries.CAMPAIGN_ATTEMPTS_WITH_LATEST_USAGE
        ).fetchall()
        for attempt_id, bound, state, prior_revision, campaign_id, raw_usage in rows:
            if state == "released":
                continue
            if raw_usage is None:
                continue
            usage = _api.json.loads(cast(str, raw_usage))
            revision = usage.get("revision")
            cost = usage.get("cost", {})
            if (
                type(revision) is not int
                or (prior_revision is not None and revision <= cast(int, prior_revision))
                or cost.get("status") != "calculated"
                or cost.get("currency") != "USD"
            ):
                continue
            try:
                amount = _api.Decimal(cost["amount_decimal"])
            except (KeyError, ValueError, _api.InvalidOperation):
                continue
            if not amount.is_finite() or amount < 0:
                continue
            next_state = "over_bound" if amount > _api.Decimal(cast(str, bound)) else "settled"
            self.store.database.execute(
                _api._queries.ACTION_UPDATE_PERSONAL_CAMPAIGN_ATTEMPTS,
                (next_state, _api.money(amount), revision, attempt_id),
            )
            changed += 1
            changed_campaigns.add(cast(str, campaign_id))
            if next_state == "over_bound":
                campaign = _api.json.loads(
                    cast(
                        str,
                        cast(
                            Row,
                            self.store.database.execute(
                                _api._queries.RECOVER_SELECT_PERSONAL_CAMPAIGNS, (campaign_id,)
                            ).fetchone(),
                        )[0],
                    )
                )
                if campaign["state"] != "closed":
                    campaign["state"] = "paused"
                    campaign["revision"] += 1
                    self.store.database.execute(
                        _api._queries.ACTION_UPDATE_PERSONAL_CAMPAIGNS,
                        (_api.encode(campaign), campaign["id"]),
                    )
        for campaign_id in sorted(changed_campaigns):
            self._audit(
                self.store.database,
                "reconcile_recorded_usage",
                actor,
                campaign_id=campaign_id,
            )
        return changed

    return self._authority_transaction(action)


def summary(self: PersonalCampaign) -> Record:
    from ezllmrouter_server import personal_campaign as _api

    with self.store.database.read():
        campaign = self._record(self.store.database)
        rows = (
            self.store.database.execute(
                _api._queries.SUMMARY_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS, (campaign["id"],)
            ).fetchall()
            if campaign
            else []
        )
        prior_count = cast(
            Row,
            self.store.database.execute(_api._queries.SUMMARY_SELECT_PERSONAL_CAMPAIGNS).fetchone(),
        )[0]
        prior_unresolved = (
            self.store.database.execute(
                _api._queries.SUMMARY_SELECT_PRIOR_UNRESOLVED, (campaign["id"],)
            ).fetchall()
            if campaign
            else []
        )
    if not campaign:
        return {"state": "not_configured", "effective_state": "not_configured", "attempts": []}
    incurred = sum(
        (
            _api._exposure(cast(str, bound), cast(str | None, cost), cast(str, state))
            for _, _, bound, cost, state, _ in rows
            if state in ("settled", "over_bound", "acknowledged")
        ),
        _api.Decimal(0),
    )
    outstanding = sum(
        (
            _api.Decimal(cast(str, bound))
            for _, _, bound, _, state, _ in rows
            if state in ("reserved", "unknown")
        ),
        _api.Decimal(0),
    )
    available = max(
        _api.Decimal(0), _api._amount(campaign["allowance_decimal"]) - incurred - outstanding
    )
    effective_state = campaign["state"]
    if effective_state == "active":
        try:
            self._current(campaign)
        except ValueError:
            effective_state = "paused_stale_authority"
    return {
        **campaign,
        "effective_state": effective_state,
        "previous_campaigns": max(0, cast(int, prior_count) - 1),
        "unresolved_prior_attempts": [
            {
                "attempt_id": attempt,
                "bound_decimal": bound,
                "cost_decimal": cost,
                "state": state,
                "campaign_id": campaign_id,
                "campaign_revision": _api.json.loads(cast(str, saved))["revision"],
            }
            for attempt, bound, cost, state, campaign_id, saved in prior_unresolved
        ],
        "incurred_decimal": _api.money(incurred),
        "outstanding_decimal": _api.money(outstanding),
        "available_decimal": _api.money(available),
        "request_count": len(rows),
        "attempts": [
            dict(
                zip(
                    (
                        "attempt_id",
                        "submission_id",
                        "bound_decimal",
                        "cost_decimal",
                        "state",
                        "usage_revision",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in rows
        ],
    }
