# Local isolated execution profile

The optional profile runs the Coordinator, registry, SQLite store, isolated
request worker, trusted sender and a controlled receiver. The standalone
accounting console is documented in the [project README](../../README.md).

## Inputs

Use a verified artifact store containing `ARTIFACT-CUSTODY.json` and `inputs/`,
the frozen 117-wheel set and pinned base images. Python and JavaScript clients
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
Service regressions run in a validation stage; the final service
image contains the server, console, local entry points and required fixture data,
without test/evidence Python sources. The worker's target check is also a temporary
build mount. LiteLLM-dependent alternate-handler and usage-model checks run only
in the worker build, with their temporary validation mount. The service validates
the frozen HTTP interface counterexamples with a read-only wheel mount.
Isolated owner proof commands mount their separately staged fixtures
read-only; ordinary profile startup has no fixture-code mounts. These Dockerfile
changes need qualification in the target Docker environment with the existing
reviewed lock and pinned images.

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
