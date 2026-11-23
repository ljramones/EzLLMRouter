# Local isolated execution profile

The optional profile runs the Coordinator, registry, SQLite store, isolated
request worker, trusted sender and a controlled receiver. The standalone
accounting console is documented in the [project README](../../README.md).

## Inputs

Use a verified artifact store containing `ARTIFACT-CUSTODY.json` and `inputs/`,
the frozen 117-wheel set, [reviewed offline Debian archives](inputs/os/README.md)
and pinned base images. Python and JavaScript clients
are built offline from the current repository sources and recorded by hash.
Build metadata is in [inputs/](inputs/README.md). Preparation verifies hashes
locally; it does not download replacement dependencies or pull images.

Set the artifact-store variable in your Terminal:

```sh
export EZLLMROUTER_ARTIFACT_ROOT=/absolute/path/to/verified/artifact-store
uv run --locked python deploy/local/local_profile.py prepare
```

Use the Python and Node versions recorded at the repository root. Source staging
copies server packages, browser assets, worker code and the selected client
artifacts into separate contexts. Build fingerprints include the active inputs.
The worker context contains no service credentials. Its validation directory
contains a temporary copy of the trusted code for build checks; BuildKit mounts that
directory read-only for the checks, and it never enters the worker image.

`local_profile.py` replaces the former `profile.py`, avoiding the standard-library
profiler module collision. Docker uses its selected context by default; set
`EZLLMROUTER_DOCKER_CONTEXT` explicitly to choose a context for these commands.
`DOCKER_CONTEXT` is also honored. No desktop context is hard-coded.

Preparation is explicit. `up` and `restart` use the last prepared build; they do
not prepare current source automatically. Run `prepare` separately when you intend
to adopt changed source. This does not restart any instance on its own.

BuildKit mounts the hash-checked wheel and client archives only during dependency
installation. The trusted service installs an 11-package subset of the reviewed
worker lock plus the current client wheel. LiteLLM is absent from its dependency,
validation and runtime stages, and both build and startup check that absence.
Preparation scans every wheel archive for startup hooks before installation.
It also verifies active dependency bounds, Python constraints and selected extras
against the Linux ARM64 target with the pinned development `packaging` parser.
No wheel code is imported during these checks.
Service regressions run in a validation stage; the final service
image contains the server, console, local entry points and required fixture data,
without test/evidence Python sources. The worker's target check is also a temporary
build mount. LiteLLM-dependent alternate-handler and usage-model checks run only
in the worker build, with their temporary validation mount. The service validates
the frozen HTTP interface counterexamples with a read-only wheel mount.
Isolated owner proof commands mount their separately staged fixtures
read-only; ordinary profile startup has no fixture-code mounts. These Dockerfile
changes passed disposable Linux ARM64 qualification at the runtime source in the
[validation record](../../docs/TESTING-ROADMAP.md#release-input-remediation-2026-11-22).
Other targets need their own qualification.

After reviewing replacement artifacts, assemble a separate immutable store:

```sh
.venv/bin/python -m tools.gateway.frozen_inputs \
  --source-store /absolute/path/to/existing-reviewed-store \
  --replacements /absolute/path/to/reviewed-wheels \
  --output /absolute/path/to/fresh-private-store
```

The command preserves the original store, copies the selected 117 wheels, and
records exact bytes, hashes and source-manifest identities in
`ezllmrouter-frozen-inputs-v1` custody. Unexpected, missing or incompatible wheels
fail. Select the new store explicitly with `EZLLMROUTER_ARTIFACT_ROOT`, then commit
runtime inputs before preparing fresh staging. Assembly does not restart a profile.

The six images include a derived `runtime_python` image for ingress and namespace
helpers. Build it before those roles start; the profile and qualification wrappers
do this automatically. All final Python images remove pip/ensurepip, and the final
JavaScript consumer removes global npm/corepack/yarn. Pinned upstream build images
retain vendor tooling and require separate security review.

The current OS selection uses Debian 13 (Trixie) while retaining Python 3.12.16
and Node 24.22.3. The separate seven-archive OS lock supplies the reviewed glibc,
OpenSSL, zlib and base-files updates without network access during builds.
Preserve the original artifact store and add the selected archives to a fresh
store as described in the [OS input guide](inputs/os/README.md). Staging binds
archive bytes and the build-only installer to the source packet. Final images
also remove APT; package consistency and an exact removal census protect the
remaining installed packages. Cached older images can still be reused; rebuilding
requires fresh preparation with these inputs.

The source-only `python -m tools.container_tests` check invokes the same pure
validation staging helpers, including profile preflights, and follows Docker
COPY, WORKDIR, stages and temporary mounts. It scans every tracked Dockerfile
and rejects validation commands without a qualified staging context. This check
does not prepare frozen inputs or start a Docker build.

Command capture is bounded and records timeouts as exit 124, with redacted output
in private evidence files. One-use catalogue/CRUD/usage run IDs accept valid
`YYYYMMDD` dates and reject collisions before starting work.

## Start and inspect

Run these commands only when you intend to operate the local Docker profile:

```sh
uv run --locked python deploy/local/local_profile.py up
uv run --locked python deploy/local/local_profile.py status
uv run --locked python deploy/local/local_profile.py audit
```

The console is published at `http://127.0.0.1:8780`. Named accounts follow the
[users guide](../../docs/USER-MANAGEMENT.md). Runtime preparation and starting the
profile are separate from selecting or authorizing any provider execution.

The service initializes fresh storage and upgrades version 1 or 2 storage to version
3 atomically. It does not adopt unversioned development databases. See
[database setup](../../docs/DATABASE.md).

## Stop, restart and backup

```sh
uv run --locked python deploy/local/local_profile.py stop
uv run --locked python deploy/local/local_profile.py restart
uv run --locked python deploy/local/local_profile.py backup
```

Normal stop/start retains named volumes. Rebuilt service/worker images use
separate sender and worker socket volumes, with each peer's mount read-only.
The former `link_data` volume can remain unused; this change does not remove it
or migrate data. Rebuild both images together before adopting the new Compose
configuration. The `topology` check tests worker-to-sender connectivity and
rejection of a worker attempt to remove the sender socket. Container mount and
signal behavior require target-runtime verification.

The service gets 330 seconds to drain accepted work before Docker can kill it;
the worker stops afterward with a 15-second grace period. Both run under Docker's
init process. Normal stop/start retains the database and credential volumes. The backup command creates a private,
consistent SQLite copy; a complete recovery also needs the matching integration
secrets, connector keyring directory and provider vault. Follow
[encryption and recovery](../../docs/ENCRYPTION.md) for the full file set and
maintenance commands. Keep credentials and generated artifacts out of Git.

## Provisioning an identity credential

`python deploy/local/provision.py PRINCIPAL_ID EXPECTED_REVISION` reserves an
owner-only `.state/provisioned/PRINCIPAL_ID.credential` file and writes a private
`PRINCIPAL_ID.provision.json` receipt containing the operation ID and expected
revision before issuing the management request. It never overwrites either file
or automatically repeats the issuance.

The credential is flushed and synced before success output. Output failure,
Ctrl-C or connection-close failure does not delete a saved credential. If the
reply is lost or persistence fails after possible issuance, the command retains
the reservation and operation receipt. An empty or partial credential file is
not a usable credential: inspect the principal's current revision and resolve
the uncertain issuance through an explicit credential rotation. Keep the files
until that review is complete. Failures before issuance remove only files
created by the current invocation. The receipt contains no credential and does
not establish whether the server committed the operation.

Local tests and package builds do not establish Docker deployment or production
acceptance. Use the [development checks](../../docs/DEVELOPMENT.md) and
[security policy](../../docs/SECURITY.md) when validating a new profile.


### Source preparation and instance identity

Commit runtime sources and inputs before preparation. The preparer rejects a
dirty source tree before building packages or staging images; its fingerprint
still records exact source and frozen-input identities.

New profiles use project `ezllmrouter-local` and descriptive receiver, worker,
service and actor image names. The wrapper reads `PROFILE-OWNER.json` and passes
that recorded project explicitly to Compose, preserving an older owned project.
Keep the ownership marker with the profile state and use the wrapper for operations
on that profile. Unowned resources under either the current or older project name
block new ownership. Source cleanup does not restart an existing daemon.

Diagnostic controls are `EZLLMROUTER_GATEWAY_GUARD_EVENTS` and
`EZLLMROUTER_GATEWAY_SEND_EVENTS`. Worker source stages as `ezllmrouter_worker`,
with explicitly listed common helpers and no trusted server package. Rebuild and
qualify the resulting image, mounts and stop behavior using the reviewed frozen
inputs before accepting an updated deployment.

### Disposable qualification

With the pinned development environment, the existing approved artifact store
configured in `EZLLMROUTER_ARTIFACT_ROOT`, and clean committed runtime sources,
prepare a separate staging directory:

```sh
mkdir -p .artifacts/qualification-staging
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -c 'from pathlib import Path; from deploy.local import prepare; prepare.STATE = Path(".artifacts/qualification-staging").resolve(); prepare.main()' > .artifacts/qualification-staging/prepare.log
.venv/bin/python -m tools.deployment_qualification \
  --build .artifacts/qualification-staging/current-build.json \
  --output .artifacts/qualification-target
```

Use a fresh output directory for each run. Docker access and an unused loopback
port 8780 are required. The runner uses fresh qualification projects, temporary
private credentials and separate restore volumes, and removes its own resources
afterward. It preserves the persistent profile. Only the four synthetic local
receiver requests belong to this check; it does not contact a real provider.
Its result binds staged source, harness hashes, image IDs, runtime checks,
restart and restore readback. Passing runtime checks does not approve a release.

The runtime footprint check inventories regular files and symbolic links across
the image filesystem, including copied tools in nonstandard directories. It
checks file modes and reviewed Perl module paths, rejects incomplete inventories,
and records a canonical metadata hash. Its absence observations cover the named,
unpacked components; renamed, archived or statically embedded code and retained
library advisories require separate review.

Capture and audit actual installed packages with the reviewed Rust metadata
artifact from the manual **Release input candidates** workflow:

```sh
.venv/bin/python -m tools.release_inventory \
  --rust /absolute/path/to/native-release-candidates/rust \
  --qualification .artifacts/qualification-target/qualification.json \
  --output .artifacts/qualification-audit --query
```

The audit inventories immutable image IDs with networking disabled, then sends
public package names/versions to OSV. It retains its inventory, CycloneDX SBOM,
all advisory pages and findings. `images.json` preserves actual installed package
metadata and embedded runtime versions; `attribution.json` separates each image's
matches from findings confined to declared inputs. PyPI aliases are normalized
when combining sources. High, critical and unrated matches fail the
gate; a failed gate requires review/remediation. Rust repository builds use the
tracked Cargo.lock with `--locked`; published library consumers resolve their
own dependency graph. See the [current qualification record](../../docs/TESTING-ROADMAP.md#deployment-qualification-and-package-audit-2026-11-22)
for the observed results and open release blockers.
