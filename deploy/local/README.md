# EzLLMRouter local synthetic operator profile

Provider credentials and local connector credentials use independent keyrings.
See [encryption and rotation](../../docs/ENCRYPTION.md) for offline maintenance
and the complete set of files required for backup and restoration.

This guide covers the existing frozen-input Docker profile. Its artifact names,
environment variables, and project identifiers retain their historical names.
Current CognitiveDynamics packages and the standalone accounting service are
documented in the [project README](../../README.md).

This profile runs the real Coordinator, persistent SQLite metadata store, isolated LiteLLM worker, trusted final guard and owned synthetic sender. Its browser console is a local, authenticated metadata view. It uses the frozen 117-wheel gateway set and the installed Python client wheel from the declared artifact store. It does not use a real provider.

## DEV-07 registry upgrade checkpoint

The DEV-07 branch adds persistent synthetic Models & Pricing and Users & Access records and an additive schema migration. `profile.py backup` uses SQLite's online backup API, includes committed WAL state, checks the copied database and writes a private `0600` copy under ignored `deploy/local/.state/backups/`. The one-use `dev07_run.py` performs that backup before changing the running profile, then runs the finite target matrix. It never removes named volumes. The migration is also tested against a disposable DEV-06-style database copy. Target observations are recorded separately in [the DEV-07 result](../../docs/development/dev-07/RESULT.md).

The target runner requires a fresh `dev07-...` namespace and the verified artifact root. It stages from the checkout, builds only missing changed images and installed-client actor images offline, runs 13 planned synthetic receiver requests and one caller lookup, verifies three queued revocations through actual management writes and pool observations, then checks an ordinary persistence restart. It stops at the first failure and saves bounded redacted evidence in ignored `.state/dev07-runs/NAMESPACE/`; the namespace cannot be reused. Run it only when the review handoff names the checked source commit. The browser walkthrough is a separate read/write observation on the resulting running profile and is not hidden in the 13-request count.

An administrator may register inactive human or service identities through the authenticated console. To provision one locally without printing the secret, use `python3 deploy/local/provision.py PRINCIPAL_ID EXPECTED_REVISION` after the DEV-07 profile starts. It writes the one-time credential to ignored `.state/provisioned/PRINCIPAL_ID.credential` with restrictive permissions. The registered identity needs explicit activation and an exact model grant before it can submit work. Service credentials cannot sign into the human console. The Models & Pricing catalogue may contain unsupported drafts; only the fixed synthetic model identities can be enabled.

## Inputs and operation

Set `DURANKI_ARTIFACT_ROOT` to a verified custody directory containing `ARTIFACT-CUSTODY.json` and `inputs/`. The current `certifi==2026.10.19` local copy is `/Users/larrymitchell/Mach33/Duranki-artifacts/dev09-certifi-20261022-01`; its [review record](../../docs/development/dev-09/RESULT.md) describes the change. The earlier `dev06-20261021-01` custody remains historical and does not satisfy the current gateway lock. Keep the pinned Python base image available in Docker Desktop. The script stages source and verifies frozen hashes offline; it neither downloads packages nor pulls an image.

```sh
DURANKI_ARTIFACT_ROOT=/Users/larrymitchell/Mach33/Duranki-artifacts/dev09-certifi-20261022-01 python3.12 deploy/local/profile.py up-and-verify
```

`up-and-verify` is an **explicit synthetic exercise**. It starts the profile, verifies worker and service identity and separation, invokes fixed text, two-round lookup and no-store text demos through the authenticated operator API, checks four new receiver arrivals and one caller lookup, then performs a normal stop/start and metadata readback. It leaves the profile running on success. A failure records redacted command outputs under `deploy/local/.state/commands/` and stops only containers created by this invocation; it preserves named metadata volumes.

The console URL is `http://127.0.0.1:8780/`. The launcher prints the private operator credential-file path; its current path is `deploy/local/.state/operator-password`. Read that file locally to sign in. The launcher never prints the credential value. The `.state` directory is mode 0700 and ignored by Git; all host credential files are mode 0600. Setup sends their contents over stdin to a network-isolated initializer, which writes mode 0400 copies owned by UID 10001 in a dedicated Docker volume. The trusted service mounts that volume read-only. The worker receives neither credential nor trusted code. Existing complete credential files are adopted without rotation; interrupted new setup resumes from its atomically saved private bundle. Ambiguous legacy partial files require inspection before setup can continue.

For ordinary use without an automatic demonstration, run `python3 deploy/local/profile.py up` with the same artifact-root setting. The launcher prints each completed stage and announces its bounded readiness wait. If a start is interrupted or the browser refuses a connection, run `python3 deploy/local/profile.py diagnose`; it reads existing profile container status and bounded redacted logs without building, starting, stopping, or sending work. After correcting source, `DURANKI_ARTIFACT_ROOT=... python3 deploy/local/profile.py restart` stops only the owned profile without removing volumes, prepares and builds from current source with frozen inputs, then starts it and checks readiness. `python3 deploy/local/profile.py status` checks a healthy current state. To stop while **preserving metadata**, run:

```sh
python3 deploy/local/profile.py stop
```

After a separately recorded explicit synthetic exercise, `python3 deploy/local/profile.py audit` performs a **read-only live correlation**. It requires `deploy/local/.state/last-explicit-exercise.json`, checks the running build and topology negative controls, then compares its four submission IDs and trusted guard receipts with independent receiver arrival metadata. It does not build, restart or send a provider request. It writes a safe summary to `deploy/local/.state/last-live-audit.json` and leaves the profile running. Run it from the owner Terminal while the profile is live; the executor cannot access Docker Desktop.

After a successful audit, `python3 deploy/local/profile.py verify-persistence` checks that all submissions are complete, records the receiver count, performs an ordinary owned `down --remove-orphans` and `up -d --no-build` without `-v`, then reads back the four recorded submissions and checks that receiver arrivals did not increase. It uses the existing staged build and frozen images; it does not prepare, build, or send new work. It leaves the profile running. If restart/readback fails, the containers and redacted command records remain for diagnosis; it does not silently resend or clear volumes.

The fixed project is `duranki-dev06-local`; the script refuses an unowned project collision. It builds only three local images with `--pull=false --network=none`, and keeps the worker in `network_mode: none`. The service and receiver share an internal project network namespace without a host port. A credential-free, read-only Python ingress container from the pinned base image joins only a dedicated publish network, mounts only a dedicated console socket volume, and relays only to `/console/operator.sock`. It publishes only `127.0.0.1:8780` on the host; it has no network path to the receiver and no sender or credential mount. The launcher checks the actual published binding before its readiness wait and saves console-socket diagnostics on failure. The disposable DEV-04/05 test projects and their volumes are separate.

## Console behavior and limits

Overview, Activity, Usage, Configuration, Models & Pricing, Users & Access and Build views read allowlisted service metadata. The browser never gets a database mount, trusted bearer token, signing key, provider key, candidate body, no-store content or tool arguments. A one-time newly provisioned credential is shown once to the authorized administrator; keep it private. Session cookies are HttpOnly and expire after 30 minutes; CSRF is checked on mutation. Host and Origin are restricted to local console names. Demo operation IDs are persisted before dispatch; a repeated accepted ID is a status query, and an interrupted running launch becomes `outcome_unknown` on restart without automatic resubmission. A deliberately new click gets fresh work/generation identities.

The normal profile regenerates its process signing key at startup. It retains permitted metadata on ordinary quiescent stop/start and does not resume pending or unknown work. It does not establish crash recovery, complete task drain, whole-memory/WAL erasure, TLS/HTTP2, real-provider safety, arbitrary tool execution or production acceptance. DEV-07 management changes apply only to approved local synthetic records. Hard budgets and cancellation remain absent. Usage is shown with latest-replacement semantics; priced synthetic attempts are labelled calculated, while unknown and older unpriced work remain honest.

The executor cannot access Docker Desktop. The owner reached the authenticated Overview, passed the live sender/receiver audit for four separately attributed synthetic attempts, and passed an ordinary stop/start readback with stable receiver count. A later temporary headless Chrome session rendered Activity and an existing no-store detail, Usage, Configuration and Build; Tab and Enter navigated to Usage, and sign-out returned to login with API access denied. Service submissions and dispatched attempts stayed at seven. Safe screenshots and a bounded result are in the [DEV-06 browser evidence at the fixed history commit](https://github.com/33fg/duranki/tree/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-06/evidence/browser-walkthrough-20261021-07).
