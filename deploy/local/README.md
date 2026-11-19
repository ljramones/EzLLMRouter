# Local isolated execution profile

The optional profile runs the Coordinator, registry, SQLite store, isolated
request worker, trusted sender and a controlled receiver. The standalone
accounting console is documented in the [project README](../../README.md).

## Inputs

Use a verified artifact store containing `ARTIFACT-CUSTODY.json` and `inputs/`,
the frozen 117-wheel set, declared client archives and pinned base images.
Build metadata is in [inputs/](inputs/README.md). Preparation verifies hashes
locally; it does not download replacement dependencies or pull images.

Set the existing artifact-store variable in your Terminal:

```sh
export DURANKI_ARTIFACT_ROOT=/absolute/path/to/verified/artifact-store
uv run --locked python deploy/local/profile.py prepare
```

Use the Python and Node versions recorded at the repository root. Source staging
copies server packages, browser assets, worker code and the selected client
artifacts into separate contexts. Build fingerprints include the active inputs.
The worker context contains no service credentials or trusted service package.

## Start and inspect

Run these commands only when you intend to operate the local Docker profile:

```sh
uv run --locked python deploy/local/profile.py up
uv run --locked python deploy/local/profile.py status
uv run --locked python deploy/local/profile.py audit
```

The console is published at `http://127.0.0.1:8780`. Named accounts follow the
[users guide](../../docs/USER-MANAGEMENT.md). Runtime preparation and starting the
profile are separate from selecting or authorizing any provider execution.

The initial database schema requires fresh instance storage; it does not adopt
prior development databases. See [database setup](../../docs/DATABASE.md).

## Stop, restart and backup

```sh
uv run --locked python deploy/local/profile.py stop
uv run --locked python deploy/local/profile.py restart
uv run --locked python deploy/local/profile.py backup
```

Normal stop/start retains named volumes. The backup command creates a private,
consistent SQLite copy; a complete recovery also needs the matching integration
secrets, connector keyring directory and provider vault. Follow
[encryption and recovery](../../docs/ENCRYPTION.md) for the full file set and
maintenance commands. Keep credentials and generated artifacts out of Git.

Local tests and package builds do not establish Docker deployment or production
acceptance. Use the [development checks](../../docs/DEVELOPMENT.md) and
[security policy](../../docs/SECURITY.md) when validating a new profile.
