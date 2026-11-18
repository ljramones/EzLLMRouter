# Approved Readiness Plan — Duranki Integration Readiness

**Correction 01:** [Focused successor commission](DURANKI-INTEGRATION-CORRECTION-01.md) and [living progress](DURANKI-INTEGRATION-PROGRESS.md). The independent review held the earlier v1 readiness claim pending IR01–IR09; the corrected 0.2.0 release result is preserved in [RESULT-v2.md](../development/integration-readiness/RESULT-v2.md). This pointer does not change the original criteria below.

**Correction 02:** [Residual correction commission](DURANKI-INTEGRATION-CORRECTION-02.md) and the same [living progress](DURANKI-INTEGRATION-PROGRESS.md). Independent Review 02 holds readiness for IC02-01–IC02-04 and requests IC02-05 review-manifest coverage. The original criteria below remain unchanged.

**Correction 03:** [Bounded lineage continuation](DURANKI-INTEGRATION-CORRECTION-03.md) and the same [living progress](DURANKI-INTEGRATION-PROGRESS.md). Independent Review 03 holds unconditional readiness for IC03-01, the continued-ingestion and mixed-version lineage residual. All original criteria below remain unchanged.

## Goal and starting status

**Starting status: NOT READY for the agreed Vega platform accounting integration.**

DEV-12 delivery is accepted with the named CT02-02b exception, but its closeout did not implement the general interface needed to record activity executed by the Vega platform.

Deliver a working local Duranki accounting service, a stable integration contract, and installable JavaScript and Python clients. The Vega platform integration team must be able to use these components without inventing missing APIs or modifying Duranki internals.

“Vega” means the entire Vega platform: its agents, delegated agents, services, and background work. The interface must represent their activity and attribution. Connecting and instrumenting those execution paths is the following milestone.

The initial purpose is usage and cost accounting and collection of a dataset for later routing work. Learned routing begins later at Larry’s direction.

## Existing foundations and required extensions

| Area | Existing foundation | Required extension |
| --- | --- | --- |
| Observation interface | APIs and accounting for Duranki-controlled submissions | Authenticated ingestion of independently executed platform activity and usage |
| Activity attribution | Agent/run attribution and task outcomes | External tasks, steps, tools, delegations, and attempts without requiring a controlled submission |
| Provider accounts | Registration, credentials, lifecycle, and model permissions | Vega-managed credential references and owner-controlled usability |
| Accounting and reports | Usage revisions, totals, authenticated reports, and exports | External provenance, actual environment/account identities, pricing provenance, and explicit missing values |
| Clients | Existing JavaScript and Python packages | Observation/account-read methods, updated documentation, new versions, and installed-artifact tests |
| Local operation | Existing service/container foundations | Reproducible local release, migration/configuration instructions, and verified persistence/restoration |

## Stage 1 — Define the integration contract

Produce a versioned contract that the service and both clients implement. Resolve the following as repository schemas, examples, and executable contract cases.

**Collection and identity**

Support a fresh dataset beginning when the first local Vega platform integration is activated. Identify the platform installation/environment, executing agent or service, workflow/task/step, parent/delegation, individual model attempt, and provider account.

Define dataset membership by the attempt’s start relative to that activation time. Exclude earlier activity from the new cohort; accept delayed completions and corrections for included attempts. Preserve the accumulated dataset when deployments change.

**Event lifecycle**

Record initial context and selected action separately from completion, native usage, corrections, and later task outcomes.

Preserve what was known before the model call independently of what was learned afterward. Define how late and out-of-order events are handled.

**Delivery behavior**

Define stable event identifiers, receipts, duplicate delivery, conflicting reuse of an identifier, retryable errors, and receipt recovery.

A telemetry retry repeats the delivery of an observation. It must never represent permission to repeat a model call. An actual model retry is a distinct attempt with its own accounting.

**Account interface**

Define provider-account registration, usable/disabled state, model permissions, credential-manager references, and a versioned eligibility response.

Support credentials managed by Vega without requiring a duplicate provider secret in Duranki. Keep owner permission to use an account separate from connection-check observations, health, and demonstrated capability.

**Authority and accounting**

Bind reporting to an authorized platform/owner scope. Distinguish account administration from reporting.

Preserve native units, currencies, price versions, cost provenance, and explicit unknowns.

**Stage 1 exit:** documented schemas, examples, and executable contract cases are committed and usable by service and client developers. Continue into implementation; this checkpoint is not a documentation-only completion.

## Stage 2 — Implement the Duranki accounting service

Extend the existing components to implement the contract.

1. **External observations and receipts.** Add the authenticated external-observation API, durable storage, and receipt recovery. Preserve external provenance. Do not create fictitious Duranki submissions, financial reservations, or sender evidence for activity executed by Vega.

2. **Activity and accounting history.** Store activity context, attempts, initial decision snapshots, subsequent usage, and outcomes. Preserve original observations and corrections. Each attempt contributes its effective amount once. Parent/delegation rollups must not count a child charge twice.

3. **Provider-account management.** Adapt registration and lifecycle management for credentials held by Vega. Provide registration and usable/disabled controls through the operator interface and API, plus the eligibility view consumed by clients. Disabling an account must still allow valid accounting for earlier or in-flight work.

4. **Pricing, reporting, and exports.** Support externally observed work with genuine platform/environment/account provenance. Preserve native values, currency, tariff identity/version, and cost basis. Keep unknown usage or cost visible rather than converting missing evidence into zero.

5. **Authorization and concurrent delivery.** Bind ingestion, administration, and reporting to authenticated scopes. Exercise conflicting events and simultaneous delivery. Reject unauthorized attribution without corrupting accepted records.

6. **Local operation and persistence.** Provide the service build and migration/configuration path. Verify that ordinary restart, upgrade, and backup restoration preserve accepted data and receipts. Persistent history must not inherit the offline conformance fixture’s 32-row context limit.

**Stage 2 exit:** the packaged service passes the contract cases through its normal authenticated HTTP surface.

Required cases include duplicate delivery, conflicting identifiers, distinct retry attempts, late/out-of-order results, unknown usage, corrections, account disable with late accounting, scope denial, concurrent ingestion, and report/export reconciliation.

Use isolated fixtures representing externally executed activity. These tests do not require a real LLM call, a new DEV-12 sender campaign, or changes to the owner’s running profile.

## Stage 3 — Deliver installable clients and prove the release

Extend the existing packages:

- JavaScript: `@mach33/duranki-client`
- Python: `mach33-duranki-client`

Add observation submission, receipt recovery, and account-eligibility reads. Update examples and protocol documentation together. Declare supported runtimes and issue new package versions.

Check the actual Vega platform runtime declarations early so the supported client profile fits the intended integration. If that information is unavailable, record the exact missing input and continue work that does not depend on it.

Deliver:

- An exact versioned npm tarball.
- An exact versioned Python wheel.
- A versioned local service build.
- Configuration and startup instructions.
- Service/API/client compatibility information.
- Artifact identities sufficient to identify the exact tested release.

Test clean consumers installed from those artifacts rather than importing client source directly from the development checkout.

**A hosted private registry is not an entry requirement for local integration.** Keep versioned archives in an approved company-private location. Later registry publication should distribute the same tested artifacts. Registry hosting and company-wide distribution automation can proceed separately.

Run a combined demonstration using the packaged service and installed clients. It must:

- Register provider accounts and read eligibility.
- Represent multiple agents and delegated work.
- Report attempts, results, usage, and outcomes.
- Resend an event without increasing totals.
- Record a distinct model retry as a separate attempt.
- Correct usage while preserving history.
- Retain an unknown result or cost explicitly.
- Disable an account in the eligibility view.
- Accept valid late accounting after disabling.
- Reconcile reports and exports against independently calculated expected totals.
- Preserve the dataset and receipts through restart and backup restoration.

**Stage 3 exit:** both installed language clients pass their contract cases against the service; the combined demonstration reconciles; and a separate clean consumer installation can follow the release instructions successfully.

## Integration readiness criteria

Declare:

`READY_FOR_VEGA_PLATFORM_INTEGRATION`

only when all of the following have been demonstrated:

1. The observation and account contract is documented, versioned, and implemented.
2. A clean local installation runs the packaged service and accepts authenticated external observations.
3. Exact installed JavaScript and Python artifacts exercise the supported contract.
4. Attribution, usage revisions, explicit unknowns, totals, and exports reconcile.
5. Account usability and authorization behavior match the contract, including late accounting after disabling.
6. Ordinary restart and backup restoration preserve the dataset and receipts.
7. The release identifies supported runtimes, compatible versions, installation/deployment instructions, and remaining limitations.

This status means a working Duranki product and installable interface are available for the Vega platform team to integrate against. It does not establish completed Vega instrumentation or production qualification.

## Following milestones

After Duranki meets the readiness criteria, the next milestone is local Vega platform integration.

That work will inventory agents and services, instrument relevant execution paths, implement a durable exporter, enforce account eligibility on new selection, activate fresh collection, and demonstrate platform coverage.

Coverage includes background jobs, delegated agents, tool-triggered model calls, direct SDK/HTTP paths, failures, retries, streaming, and other model operations used by the platform.

The platform exporter owns buffering, delivery retry, and visible backlog/loss behavior. The HTTP clients remain focused transport and validation components. Reporting outages must not cause model requests to be replayed.

After local acceptance, Vega and Duranki can be deployed as separate authenticated services while preserving the accumulated dataset. Qualify the actual chosen database and deployment topology for that deployment.

Learned classification/routing begins later at Larry’s direction. Historical usage import remains deferred.

## Existing DEV-12 exception

Keep `CT02-02b` **OPEN** and DEV-12 technical qualification **PARTIAL** in the historical release record. Delivery was accepted with that exception.

The exception concerns controlled-execution ownership. The new observation path should not invoke that ownership/sender machinery. Review any actual dependency before claiming readiness.

The older exception does not automatically require a repeat target campaign before this observation interface can be qualified. Verify the new observation path’s own concurrency and duplicate-delivery behavior.

## Commission execution boundary

This commission implements and verifies the three stages in isolation. It does not authorize production deployment, owner-profile changes, real provider calls, commercial spend, public publication, or a DEV-12 sender campaign. Vega instrumentation, its durable exporter, dataset activation and Vega-side eligibility enforcement belong to the following integration milestone.
