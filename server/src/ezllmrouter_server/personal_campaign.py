"""One local personal test allowance. Amounts are decimal strings, never floats."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .cache_accounting import SEMANTICS as CACHE_SEMANTICS
from .cache_accounting import exposure_bound
from .canonical import ContractError
from .formatting import money, utc_timestamp
from .identifiers import valid_identifier
from .repositories import personal_campaign as _queries
from .repositories import authority as authority_queries
from .store import encode

CENT_NANO = Decimal("0.000000001")


def _exposure(bound, cost, state):
    if state == "released":
        return Decimal(0)
    if state == "settled":
        return Decimal(cost if cost is not None else bound)
    if state in ("over_bound", "acknowledged"):
        return max(Decimal(bound), Decimal(cost or "0"))
    return Decimal(bound)


def _amount(value):
    if type(value) is not str or not value or len(value) > 32:
        raise ValueError("invalid allowance")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid allowance") from exc
    if not number.is_finite() or number <= 0 or number.as_tuple().exponent < -9:
        raise ValueError("invalid allowance")
    return number


def _time(value):
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("invalid expiry")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid expiry") from exc
    if result <= datetime.now(timezone.utc):
        raise ValueError("campaign expiry has passed")
    return value


class PersonalCampaign:
    def __init__(self, store, registry):
        self.store, self.registry = store, registry

        # A service restart loses the in-memory send position. A persisted
        # reservation may already have reached the provider, so keep its full
        # exposure and require explicit reconciliation before another send.
        def recover():
            rows = self.store.database.execute(
                _queries.RECOVER_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS
            ).fetchall()
            if not rows:
                return
            self.store.database.execute(_queries.RECOVER_UPDATE_PERSONAL_CAMPAIGN_ATTEMPTS)
            for campaign_id in {row[0] for row in rows}:
                row = self.store.database.execute(
                    _queries.RECOVER_SELECT_PERSONAL_CAMPAIGNS, (campaign_id,)
                ).fetchone()
                if row:
                    record = json.loads(row[0])
                    if record["state"] != "closed":
                        record["state"] = "paused"
                        record["revision"] += 1
                        self.store.database.execute(
                            _queries.ACTION_UPDATE_PERSONAL_CAMPAIGNS, (encode(record), campaign_id)
                        )
                    self._audit(
                        self.store.database, "recover_unknown", "system", campaign_id=campaign_id
                    )

        self._authority_transaction(recover)

    def _authority_transaction(self, action):
        with self.registry.send_authority.gate:

            def mutate():
                result = action()
                row = self.store.database.execute(authority_queries.REVISION).fetchone()
                return result, int(row[0])

            result, epoch = self.store.database.transaction(mutate)
            # Read inside the transaction, publish only after commit. A failed
            # post-commit query must never leave the in-memory epoch behind.
            self.registry.send_authority.epoch = epoch
            return result

    def _record(self, db):
        row = db.execute(_queries.RECORD_SELECT_PERSONAL_CAMPAIGNS).fetchone()
        return json.loads(row[0]) if row else None

    def _audit(self, db, action, actor, *, campaign_id=None):
        if campaign_id is None:
            campaign_id = self._record(db)["id"]
        db.execute(
            _queries.AUDIT_INSERT_PERSONAL_CAMPAIGN_AUDIT,
            (campaign_id, action, actor, utc_timestamp(datetime.now(timezone.utc), precise=True)),
        )
        authority_queries.record_change(
            db,
            actor=actor,
            action="campaign_" + action,
            subject=campaign_id,
            old_revision=None,
            new_revision=json.loads(
                db.execute(_queries.RECOVER_SELECT_PERSONAL_CAMPAIGNS, (campaign_id,)).fetchone()[0]
            )["revision"],
            at=utc_timestamp(datetime.now(timezone.utc), precise=True),
        )

    def configure(self, actor, data):
        if actor != self.registry.identity.owner_id or set(data) != {
            "connection_id",
            "configuration_ref",
            "principal_id",
            "currency",
            "allowance_decimal",
            "per_request_decimal",
            "max_requests",
            "max_input_bytes",
            "max_output_tokens",
            "expires_at",
        }:
            raise ValueError("invalid campaign configuration")
        allowance, per_request = (
            _amount(data["allowance_decimal"]),
            _amount(data["per_request_decimal"]),
        )
        if per_request > allowance or data["currency"] != "USD":
            raise ValueError("unsupported campaign currency or ceiling")
        for name, maximum in (
            ("max_requests", 100),
            ("max_input_bytes", 4096),
            ("max_output_tokens", 4096),
        ):
            if type(data[name]) is not int or not 1 <= data[name] <= maximum:
                raise ValueError("invalid campaign limit")
        _time(data["expires_at"])
        connection = self.registry.connection(data["connection_id"])
        model = self.registry.model(data["configuration_ref"])
        caller = self.registry.principal(data["principal_id"])
        if (
            not connection
            or connection.get("funding_kind") != "personal_testing"
            or connection["owner"] != actor
            or connection["adapter_id"] != "openai.responses.v1"
            or not model
            or model.get("kind") != "provider_deployment"
            or model["destination"].get("connection_id") != connection["connection_id"]
            or not caller
            or caller["status"] != "active"
            or caller["owner"] != actor
        ):
            raise ValueError("campaign setup, deployment or caller is not eligible")
        record = {
            **data,
            "id": "personal.local.1",
            "owner": actor,
            "state": "draft",
            "revision": 1,
            "connection_revision": connection["revision"],
            "credential_version": connection["credential_version"],
            "model_revision": model["revision"],
            "price_version": model.get("price_version"),
        }

        def action():
            old = self._record(self.store.database)
            if old and old["state"] not in ("draft", "paused", "closed"):
                raise ValueError("existing campaign and exposure must be retained")
            if (
                old
                and old["state"] != "closed"
                and self.store.database.execute(
                    _queries.ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS, (old["id"],)
                ).fetchone()
            ):
                raise ValueError("unresolved exposure prevents a new allowance")
            if old and old["state"] != "closed":
                if self.store.database.execute(
                    _queries.ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS_4, (old["id"],)
                ).fetchone():
                    raise ValueError("close the existing campaign before configuring another")
                record["id"] = old["id"]
                record["revision"] = old["revision"] + 1
            elif old:
                record["id"] = "personal.local." + str(int(old["id"].rsplit(".", 1)[1]) + 1)
            self.store.database.execute(
                _queries.ACTION_INSERT_PERSONAL_CAMPAIGNS, (record["id"], encode(record))
            )
            self._audit(self.store.database, "configure", actor)
            return record

        return self._authority_transaction(action)

    def transition(self, actor, state):
        if actor != self.registry.identity.owner_id or state not in ("active", "paused", "closed"):
            raise ValueError("invalid campaign action")

        def action():
            record = self._record(self.store.database)
            if not record or record["state"] == "closed":
                raise ValueError("campaign unavailable")
            if state == "active":
                if record["state"] not in ("draft", "paused"):
                    raise ValueError("campaign already active")
                self._current(record)
                if self.store.database.execute(
                    _queries.ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS, (record["id"],)
                ).fetchone():
                    raise ValueError("unresolved exposure prevents activation")
            record["state"] = state
            record["revision"] += 1
            self.store.database.execute(
                _queries.ACTION_UPDATE_PERSONAL_CAMPAIGNS, (encode(record), record["id"])
            )
            self._audit(self.store.database, state, actor)
            return record

        return self._authority_transaction(action)

    def revalidate(self, actor):
        """Bind current key/model/rate revisions without resetting spent attempts."""
        if actor != self.registry.identity.owner_id:
            raise PermissionError("OWNER_REQUIRED")

        def action():
            record = self._record(self.store.database)
            if (
                not record
                or record["state"] != "paused"
                or self.store.database.execute(
                    _queries.ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS, (record["id"],)
                ).fetchone()
            ):
                raise ValueError("pause and resolve all exposure before revalidation")
            connection = self.registry.connection(record["connection_id"])
            model = self.registry.model(record["configuration_ref"])
            prices = self.registry.prices(record["configuration_ref"])
            price = prices[-1] if prices else None
            if (
                not connection
                or connection["status"] != "active"
                or connection["credential_state"] != "present"
                or connection["owner"] != actor
                or not model
                or model["status"] != "enabled"
                or not price
                or price["currency"] != record["currency"]
                or price["usage_semantics_version"] != CACHE_SEMANTICS
                or not self.registry.explain(
                    record["principal_id"],
                    record["configuration_ref"],
                    "execution",
                    self.registry.identity.task_class,
                    ("text",),
                )["allowed"]
            ):
                raise ValueError("current setup, price or permission is not eligible")
            _time(record["expires_at"])
            record.update(
                connection_revision=connection["revision"],
                credential_version=connection["credential_version"],
                model_revision=model["revision"],
                price_version=price["price_version"],
                revision=record["revision"] + 1,
                state="draft",
            )
            self.store.database.execute(
                _queries.ACTION_UPDATE_PERSONAL_CAMPAIGNS, (encode(record), record["id"])
            )
            self._audit(self.store.database, "revalidate", actor)
            return record

        return self._authority_transaction(action)

    def acknowledge_exposure(self, actor, data):
        """Charge unresolved exposure to its allowance without inventing provider usage."""
        if actor != self.registry.identity.owner_id:
            raise PermissionError("OWNER_REQUIRED")
        if (
            type(data) is not dict
            or set(data) != {"campaign_id", "attempt_id", "expected_revision", "reason"}
            or not valid_identifier(data["campaign_id"])
            or not valid_identifier(data["attempt_id"])
            or type(data["expected_revision"]) is not int
            or data["expected_revision"] < 1
            or type(data["reason"]) is not str
            or not 1 <= len(data["reason"].strip()) <= 512
            or "\x00" in data["reason"]
        ):
            raise ValueError("invalid exposure acknowledgement")
        try:
            data["reason"].encode("utf-8", "strict")
        except UnicodeError as exc:
            raise ValueError("invalid exposure acknowledgement reason") from exc

        def action():
            db = self.store.database
            row = db.execute(_queries.ACKNOWLEDGE_SELECT_ATTEMPT, (data["attempt_id"],)).fetchone()
            saved = db.execute(
                _queries.RECOVER_SELECT_PERSONAL_CAMPAIGNS, (data["campaign_id"],)
            ).fetchone()
            if not row or not saved or row[3] != data["campaign_id"]:
                raise ValueError("campaign attempt unavailable")
            campaign = json.loads(saved[0])
            if campaign["owner"] != actor:
                raise PermissionError("OWNER_REQUIRED")
            history = campaign.setdefault("exposure_acknowledgements", [])
            if row[2] == "acknowledged":
                prior = next(
                    (
                        entry
                        for entry in reversed(history)
                        if entry["attempt_id"] == data["attempt_id"]
                    ),
                    None,
                )
                if prior and prior["reason"] == data["reason"].strip():
                    return prior
                raise ValueError("exposure already acknowledged")
            if (
                campaign["revision"] != data["expected_revision"]
                or campaign["state"] not in ("paused", "closed")
                or row[2] not in ("unknown", "over_bound")
            ):
                raise ValueError("pause and review unresolved exposure before acknowledgement")
            acknowledgement = {
                "attempt_id": data["attempt_id"],
                "campaign_id": data["campaign_id"],
                "reason": data["reason"].strip(),
                "actor": actor,
                "at": utc_timestamp(datetime.now(timezone.utc)),
                "charged_decimal": money(_exposure(row[0], row[1], "acknowledged")),
                "usage_revision": row[4],
            }
            history.append(acknowledgement)
            campaign["revision"] += 1
            db.execute(_queries.ACKNOWLEDGE_UPDATE_ATTEMPT, (data["attempt_id"],))
            db.execute(
                _queries.ACTION_UPDATE_PERSONAL_CAMPAIGNS, (encode(campaign), campaign["id"])
            )
            self._audit(db, "acknowledge_exposure", actor, campaign_id=campaign["id"])
            return acknowledgement

        return self._authority_transaction(action)

    def _current(self, record):
        connection = self.registry.connection(record["connection_id"])
        model = self.registry.model(record["configuration_ref"])
        schedule = self.registry.prices(record["configuration_ref"])
        active = schedule[-1] if schedule else None
        if (
            not connection
            or connection["status"] != "active"
            or connection["credential_state"] != "present"
            or connection["revision"] != record["connection_revision"]
            or connection["credential_version"] != record["credential_version"]
            or not model
            or model["revision"] != record["model_revision"]
            or not active
            or active["price_version"] != record["price_version"]
            or active["currency"] != record["currency"]
            or active["usage_semantics_version"] != CACHE_SEMANTICS
            or active.get("contract", {}).get("requested_model") != model["destination"]["model"]
        ):
            raise ValueError("campaign authority is stale")
        if not self.registry.explain(
            record["principal_id"],
            record["configuration_ref"],
            "execution",
            self.registry.identity.task_class,
            ("text",),
        )["allowed"]:
            raise ValueError("campaign model permission or caller grant is missing")
        _time(record["expires_at"])
        return active

    def reserve(self, db, record, messages_bytes, output_limit):
        campaign = self._record(db)
        if (
            not campaign
            or campaign["state"] != "active"
            or record["principal_id"] != campaign["principal_id"]
            or record["selected_destination"].get("connection_id") != campaign["connection_id"]
            or record["selected_destination"]["configuration_ref"] != campaign["configuration_ref"]
            or messages_bytes > campaign["max_input_bytes"]
            or output_limit > campaign["max_output_tokens"]
        ):
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        try:
            rate = self._current(campaign)
        except ValueError as exc:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403) from exc
        # The reviewed provider context ceiling covers tokenization, framing
        # and multibyte input. Each input token occupies one disjoint bucket;
        # charging all at the highest rate bounds any cold/write/read mix.
        try:
            bound = exposure_bound(rate, output_limit)
        except (KeyError, ValueError) as exc:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403) from exc
        if bound <= 0 or bound > _amount(campaign["per_request_decimal"]):
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        rows = db.execute(
            _queries.RESERVE_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS, (campaign["id"],)
        ).fetchall()
        exposure = sum(
            (_exposure(bound, cost, state) for bound, cost, state in rows),
            Decimal(0),
        )
        if (
            len(rows) >= campaign["max_requests"]
            or any(state in ("reserved", "unknown") for _, _, state in rows)
            or exposure + bound > _amount(campaign["allowance_decimal"])
        ):
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        db.execute(
            _queries.RESERVE_INSERT_PERSONAL_CAMPAIGN_ATTEMPTS,
            (
                record["attempt_id"],
                record["submission_id"],
                campaign["id"],
                money(bound),
                None,
                "reserved",
                None,
            ),
        )
        return {
            "campaign_id": campaign["id"],
            "campaign_revision": campaign["revision"],
            "reserved_decimal": money(bound),
            "currency": campaign["currency"],
            "input_token_bound": rate["contract"]["input_token_ceiling"],
            "output_token_bound": output_limit,
            "price_version": rate["price_version"],
            "contract_version": rate["contract"]["version"],
        }

    def check(self, attempt_id, revision):
        with self.store.database.read():
            campaign = self._record(self.store.database)
            row = self.store.database.execute(
                _queries.CHECK_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS, (attempt_id,)
            ).fetchone()
        if (
            not campaign
            or campaign["state"] != "active"
            or campaign["revision"] != revision
            or not row
            or row != ("reserved", campaign["id"])
        ):
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        try:
            self._current(campaign)
        except ValueError as exc:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403) from exc

    def settle(self, attempt_id, usage=None, *, before_transmit=False):
        def action():
            row = self.store.database.execute(
                _queries.ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS_2, (attempt_id,)
            ).fetchone()
            if (
                not row
                or row[1] not in ("reserved", "unknown")
                or (row[1] == "unknown" and before_transmit)
            ):
                return
            state, cost, revision = "unknown", None, None
            if before_transmit:
                state = "released"
            elif usage and usage.get("cost", {}).get("status") == "calculated":
                cost = usage["cost"]["amount_decimal"]
                revision = usage.get("revision")
                state = "settled"
            if cost is not None and Decimal(cost) > Decimal(row[0]):
                state = "over_bound"
            self.store.database.execute(
                _queries.ACTION_UPDATE_PERSONAL_CAMPAIGN_ATTEMPTS,
                (state, cost, revision, attempt_id),
            )
            if state != "settled" and state != "released":
                campaign_row = self.store.database.execute(
                    _queries.RECOVER_SELECT_PERSONAL_CAMPAIGNS, (row[2],)
                ).fetchone()
                campaign = json.loads(campaign_row[0])
                if campaign["state"] != "closed":
                    campaign["state"] = "paused"
                    campaign["revision"] += 1
                    self.store.database.execute(
                        _queries.ACTION_UPDATE_PERSONAL_CAMPAIGNS,
                        (encode(campaign), campaign["id"]),
                    )
                self._audit(self.store.database, state, "system", campaign_id=campaign["id"])

        self._authority_transaction(action)

    def reconcile_recorded_usage(self, actor):
        """Owner-requested local reconciliation; never replays provider work."""
        if actor != self.registry.identity.owner_id:
            raise PermissionError("OWNER_REQUIRED")

        def action():
            changed = 0
            changed_campaigns = set()
            rows = self.store.database.execute(
                _queries.ACTION_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS_3
            ).fetchall()
            for attempt_id, bound, state, prior_revision, campaign_id, raw_usage in rows:
                if state == "released":
                    continue
                if raw_usage is None:
                    continue
                usage = json.loads(raw_usage)
                revision = usage.get("revision")
                cost = usage.get("cost", {})
                if (
                    type(revision) is not int
                    or (prior_revision is not None and revision <= prior_revision)
                    or cost.get("status") != "calculated"
                    or cost.get("currency") != "USD"
                ):
                    continue
                try:
                    amount = Decimal(cost["amount_decimal"])
                except (KeyError, ValueError, InvalidOperation):
                    continue
                if not amount.is_finite() or amount < 0:
                    continue
                next_state = "over_bound" if amount > Decimal(bound) else "settled"
                self.store.database.execute(
                    _queries.ACTION_UPDATE_PERSONAL_CAMPAIGN_ATTEMPTS,
                    (next_state, money(amount), revision, attempt_id),
                )
                changed += 1
                changed_campaigns.add(campaign_id)
                if next_state == "over_bound":
                    campaign = json.loads(
                        self.store.database.execute(
                            _queries.RECOVER_SELECT_PERSONAL_CAMPAIGNS, (campaign_id,)
                        ).fetchone()[0]
                    )
                    if campaign["state"] != "closed":
                        campaign["state"] = "paused"
                        campaign["revision"] += 1
                        self.store.database.execute(
                            _queries.ACTION_UPDATE_PERSONAL_CAMPAIGNS,
                            (encode(campaign), campaign["id"]),
                        )
            for campaign_id in sorted(changed_campaigns):
                self._audit(
                    self.store.database, "reconcile_recorded_usage", actor, campaign_id=campaign_id
                )
            return changed

        return self._authority_transaction(action)

    def summary(self):
        with self.store.database.read():
            campaign = self._record(self.store.database)
            rows = (
                self.store.database.execute(
                    _queries.SUMMARY_SELECT_PERSONAL_CAMPAIGN_ATTEMPTS, (campaign["id"],)
                ).fetchall()
                if campaign
                else []
            )
            prior_count = self.store.database.execute(
                _queries.SUMMARY_SELECT_PERSONAL_CAMPAIGNS
            ).fetchone()[0]
            prior_unresolved = (
                self.store.database.execute(
                    _queries.SUMMARY_SELECT_PRIOR_UNRESOLVED, (campaign["id"],)
                ).fetchall()
                if campaign
                else []
            )
        if not campaign:
            return {"state": "not_configured", "effective_state": "not_configured", "attempts": []}
        incurred = sum(
            (
                _exposure(bound, cost, state)
                for _, _, bound, cost, state, _ in rows
                if state in ("settled", "over_bound", "acknowledged")
            ),
            Decimal(0),
        )
        outstanding = sum(
            (
                Decimal(bound)
                for _, _, bound, _, state, _ in rows
                if state in ("reserved", "unknown")
            ),
            Decimal(0),
        )
        available = max(Decimal(0), _amount(campaign["allowance_decimal"]) - incurred - outstanding)
        effective_state = campaign["state"]
        if effective_state == "active":
            try:
                self._current(campaign)
            except ValueError:
                effective_state = "paused_stale_authority"
        return {
            **campaign,
            "effective_state": effective_state,
            "previous_campaigns": max(0, prior_count - 1),
            "unresolved_prior_attempts": [
                {
                    "attempt_id": attempt,
                    "bound_decimal": bound,
                    "cost_decimal": cost,
                    "state": state,
                    "campaign_id": campaign_id,
                    "campaign_revision": json.loads(saved)["revision"],
                }
                for attempt, bound, cost, state, campaign_id, saved in prior_unresolved
            ],
            "incurred_decimal": money(incurred),
            "outstanding_decimal": money(outstanding),
            "available_decimal": money(available),
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
