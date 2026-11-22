# Encryption keys and rotation

This is the initial encryption format for a new installation. There are no
earlier-format readers, shared master keys, automatic imports or data migrations.

Each credential store uses `SecretBox` with an independently generated keyring:

| Store | Purpose | Keyring location |
| --- | --- | --- |
| Integration provider accounts | `integration-credentials` | `SECRETS_DIR/integration.keys.json` |
| Local connectors | `local-connector-credentials` | `DATABASE_PATH.secrets/local-connectors.keys.json` |
| Execution provider vault | `provider-credentials` | `VAULT_DIR/provider.keys.json` |

Keyrings are owner-only JSON files, saved atomically with mode `0600` inside
directories with mode `0700`. They contain a current AES-256-GCM encryption key,
its identifier, retained encryption keys, and an independent HMAC key for request
idempotency. No store borrows key material from another store. Encryption rotation
keeps the HMAC key stable so retries still match their original operation.

Every encryption uses a random 12-byte nonce. Authenticated associated data binds
the format version, purpose, key identifier and record identity. Integration
credentials additionally bind their version and provider; vault credentials bind
their connection and version. Swapping a ciphertext between records, purposes or
versions fails authentication. Missing keys and malformed files fail closed;
existing ciphertext never causes a replacement keyring to be generated.

## Rotate a write key and re-encrypt stored credentials

Stop services and other maintenance commands using the instance, then back up
its database, keyrings and vault files together. Run maintenance in the same
Python environment as the server. For the instance created by `start.sh`, from
the repository root:

```sh
uv run --project server --frozen --no-python-downloads \
  python -m ezllmrouter_server.secret_rotation rotate \
  --scope integration \
  --db "$PWD/local-instance/service.sqlite" \
  --keyring "$PWD/local-instance/secrets/integration.keys.json"

uv run --project server --frozen --no-python-downloads \
  python -m ezllmrouter_server.secret_rotation rotate \
  --scope connectors \
  --db "$PWD/local-instance/service.sqlite"
```

The provider vault belongs to the execution profile. Run its maintenance inside
the service environment, with that service stopped and its data volume available:

```sh
python -m ezllmrouter_server.secret_rotation rotate \
  --scope provider --db /data/store.sqlite --vault /data/provider-vault
```

Use the actual database path configured for that profile. `--keyring` can override
the connector keyring location for a separately configured connector store.
The command requires existing absolute paths and does not initialize an instance,
register accounts, discover models or call a provider. Its output contains only
the scope, active key identifier and number of rewritten secrets.

Maintenance acquires an exclusive instance lease before opening the database or
changing keys. Every writable `SQLiteStore` holds an exclusive lease until it
closes; read-only offline tools hold shared leases. A second service, rotation,
resume, retirement and `integration_local --backup` refuse a live
instance. The lease is the canonical database path plus `.instance.lock`, owned
by the service user with mode `0600`. Never remove that file while any owner may
still be running: replacing its inode would bypass exclusion. Older server
versions and external SQLite tools do not participate in the lease protocol and
must also be stopped explicitly.

Rotation publishes the new write key durably before rewriting ciphertext.
Database rewrites commit in one transaction per store. Vault files are replaced
atomically one at a time. Credential versions, account/connector revisions,
permissions, history and idempotency records stay unchanged.

If maintenance is interrupted, correct the reported fault and run the same
command with `resume` in place of `rotate`. Resume uses the already active key;
it does not generate another key. A completed resume reports zero rewrites when
all records already use that key. The keyring retains predecessors so partially
rewritten data and older backups remain decryptable. Rotation and resume never
delete predecessors. Retirement is a separate, explicit operation; HMAC-key
rotation is outside this command.

Disposable integration/connector tests kill real maintenance processes after key
publication, during database rewrite, before commit and after commit. Reopening
checks all unaffected tables, original identities and credential decryption.
Resume uses the published key and rewrites either the complete rolled-back set
or zero rows after a committed rewrite. These tests qualify process interruption,
not physical power loss or a production backup.

## Retire an old encryption key

Before rotating, run `resume` and record its active key identifier if you intend
to retire that key later. After rotation, complete `resume` and verify backups
before retiring it. Keep services stopped throughout maintenance.

Retirement scans references in all integration credential versions, every local
connector ciphertext, or every sealed provider-vault file for the selected scope.
It verifies decryption and record binding without rewriting ciphertext. Active
keys, referenced keys, unknown keys and unverifiable stored credentials prevent
retirement. Unselected and orphaned vault files are included and can block it.
The independent HMAC key is preserved.

The command cannot inspect external backups. `--confirm-no-dependent-backups`
is the owner's explicit acknowledgment that no retained backup or other data
still needs the selected key. Restore and re-encrypt needed backups first, or
retain their keyring securely instead of retiring the key. For example:

```sh
uv run --project server --frozen --no-python-downloads \
  python -m ezllmrouter_server.secret_rotation retire \
  --scope integration \
  --db "$PWD/local-instance/service.sqlite" \
  --keyring "$PWD/local-instance/secrets/integration.keys.json" \
  --key-id OLD_KEY_ID --confirm-no-dependent-backups
```

Use `--scope connectors` or `--scope provider` with the corresponding paths to
retire a key from those stores. This removes only the selected key from the live
keyring. It does not erase key material from copied keyrings, backups or storage
snapshots, and does not revoke those copies.

## Keyring caching and filesystem requirements

Each `SecretBox` caches its validated keyring and decoded cryptographic objects.
Every operation checks file identity, size, timestamps, owner and permissions;
a changed generation is read and validated again. Rotation by another instance
is observed on the next operation. Missing, corrupt, symlinked or insecure files
fail closed rather than using stale cached keys. Every encryption still creates
a fresh random nonce.

Use a local POSIX filesystem with coherent file metadata, working advisory
`flock`, atomic same-directory hard-link creation and replacement, and file and
directory `fsync`. Run services and maintenance under the same owning user.
Hard-linked database files are rejected; the maintenance command also rejects a
symlink as its database input. Network, FUSE and other filesystems are suitable
only when those guarantees have been established for the actual deployment.

Private publication writes a `0600` temporary file in the destination directory,
syncs its contents, publishes by link or replacement, then syncs the directory.
There is no in-place copy fallback when atomic publication is unsupported.
Existing destinations still block no-replace publication. An
`AtomicPublicationError` reports whether publication already occurred: directory
sync can fail after a complete new file becomes visible. Preserve credential
custody in that case, inspect the target and recover with the relevant resume
procedure rather than deleting a potentially committed credential or keyring.

## Resume provider credential cleanup

If the process stops after sealing a successor version but before committing its
registry record, the next authorized replacement atomically replaces that
unselected successor file. The exclusive store lease and send-authority gate
serialize this decision against the committed credential version. A selected
version is never overwritten. Failed or ambiguous transaction acknowledgements
retain the staged file because the database may already select it; retry the
original operation to obtain its durable receipt and resume retired-file cleanup.
Unrelated vault files are preserved for inspection.

Execution provider credential replacement/removal commits its registry record,
audit and idempotency receipt before deleting the retired sealed file. If that
file cleanup fails, correct the filesystem fault and repeat the original request
with the same actor, operation ID, expected revision and credential body.

The saved operation receipt identifies its retired version across retries and
registry/vault reopen. Replaying the operation resumes deletion, returns its
recorded reply and preserves the currently selected credential version. Later
rotations remain intact when an earlier operation's cleanup is retried.

## Back up and restore an instance

With the service and maintenance stopped, preserve the database, its
`DATABASE_PATH.secrets` directory, the configured integration secrets directory,
and the entire provider vault when present. Restore them as one consistent set,
keeping their private permissions. A SQLite-only backup does not contain the
decryption keys. Never put these files in Git or an evidence export; generated
default keyring names, lock files and sealed credentials are ignored by the
repository and excluded from runtime evidence capture. Keep custom keyring paths
outside the source and evidence trees as well.

The offline `integration_local --backup` command validates the source schema and
copies committed SQLite/WAL data into a private staging file in the destination
directory. It syncs the completed file before publishing a new destination and
syncs that directory afterward; an existing destination is never overwritten.
An interrupted copy can leave an owner-only `.partial` staging file, which is
never used as a completed backup. A retry can create a new staging file without
using that abandoned copy. A directory-sync error after publication reports
`AtomicPublicationError.published=True`; preserve and inspect the complete target.

Restore regressions move the original source path away before reopening the
snapshot. An older keyring missing the backup's encryption key fails closed.
A newer keyring remains compatible while it retains that key; retiring the
required key makes the backup unreadable. Tests cover these combinations in all
three scopes and verify that failed resolution rewrites neither rows nor keys.


Instance identity metadata and the local profile ownership marker belong with
consistent backups. Reopening preserves those identities; filesystem relocation
and profile ownership must be resolved explicitly using the recorded checkout and
project. Atomic file publication still requires the local POSIX guarantees above.
Unsupported hard-link/replacement/fsync behavior raises an error; there is no
copy fallback or automatic deletion of uncertain credential/key files.
