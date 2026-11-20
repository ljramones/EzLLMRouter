# Users and permissions

Named browser accounts are available in the main console and the standalone
accounting console. Accounts share the SQLite identity registry, keeping model
grants and recorded attribution attached to stable principal IDs.

## First sign-in

Run `./start.sh` from the project folder, then open
**http://127.0.0.1:48761/integration**. Stop the service with **Ctrl+C**.

For a database without console accounts:

- Username: **`admin`**
- Temporary password: randomly generated in
  **`local-instance/secrets/admin.password`** by the standard launcher. The file
  has mode `0600`; startup prints its path rather than its contents.

There is no shared default password. A restart reuses an unfinished bootstrap's
private password file and never replaces an existing account's password.
Library users can supply `bootstrap_password_file`; its default is
`.console-secrets/admin.password` beside the database.

The initial account is bound to the existing active human administrator, normally
`owner.local`. It cannot use the console until its temporary password is changed.
Passwords must contain 12–256 characters. Password changes sign out existing
sessions; sign in again with the new password.

To choose different initial credentials, set `EZLLMROUTER_ADMIN_USERNAME` and
`EZLLMROUTER_ADMIN_PASSWORD` in the service environment before its first start.
These values only seed an empty account table. Restarting the service or changing
the environment does not overwrite an existing account or password.

## Roles

| Role | Permissions |
| --- | --- |
| Administrator | Manage users, roles, identities, model grants, and connections; read activity, reports, and settings. |
| Read-only | Inspect activity, reports, registered resources, and settings; cannot change users, permissions, or connections. |
| User | Inspect their own activity and permitted models; model execution requires explicit grants. |

Permissions are enforced by the server. Hiding a console button is not the
authorization check. A console role does not create a model grant or authorize
provider spending by itself. External accounting data retains its existing
dataset and owner access checks.

## Managing accounts

Open **Users & Permissions** as an administrator to search, create, edit,
disable, delete, or reset a user's password. New accounts default to the User
role. Usernames contain 3–64 letters, digits, dots, underscores, or hyphens and
are case-insensitive. Each user has a stable internal principal ID; renaming a
username does not change recorded attribution.

- **Create user** sets a temporary password that the user must change at sign-in.
- **Edit** changes the name, username, role, or enabled/disabled state. Role,
  username, and status changes invalidate existing sessions.
- **Reset password** replaces the password, invalidates sessions, and requires
  another password change at sign-in. Passwords cannot be retrieved.
- **Model access** opens the existing exact model-grant editor.
- **Delete** revokes access, removes API credential bindings, and replaces the
  password verifier. The identity and audit/accounting history remain retained;
  deleted usernames cannot be reused.

The last enabled administrator with a console account cannot be disabled,
deleted, or demoted. This rule also applies through the older identity-management
API. Disabled users cannot sign in. Re-enabling an account does not restore its
old sessions. Updates use record revisions to reject stale edits.

Every named user can change their own password using the header account button.
Non-administrators see their own account and effective permissions on the users
page, without access to other accounts.

## Storage and sessions

Passwords are stored as salted scrypt verifiers, separately from public identity
records. They are excluded from API responses and audit entries. Browser sessions
use HttpOnly, SameSite cookies, expire after 30 minutes, and recheck the current
account state on each request. Writes require both the allowed Origin and a CSRF
token. Login attempts are limited to 20 per minute per client address.

Login rechecks account state after password verification and before creating its
session, so a completed password reset or permission change during verification
rejects that login. Account lookups run outside the session dictionary lock;
results cannot restore a session removed by logout or expiry. Expired or invalid
sessions also revoke their associated temporary execution credentials.

Service identities use API credentials and cannot sign in as named human users.
Start a new instance using the [database guide](DATABASE.md) and use the matching
browser assets from `web/`.

## Operator API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/operator/v1/login` | Named sign-in with `username` and `password`. |
| GET | `/operator/v1/session` | Own identity, role, effective permissions, and password-change requirement. |
| POST | `/operator/v1/account/password` | Change own password using `current_password` and `new_password`. |
| GET / POST | `/operator/v1/users` | Administrator list / create. |
| GET / POST / DELETE | `/operator/v1/users/{principal_id}` | Administrator read / update / delete. |
| POST | `/operator/v1/users/{principal_id}/password` | Administrator password reset. |

Create accepts `username`, `display_name`, `role`, `status`, and `password`.
Update accepts `username`, `display_name`, `role`, `status`, and
`expected_revision`. Reset accepts `password` and `expected_revision`; delete
accepts `expected_revision`. Roles are `registry_admin`, `read_only_operator`,
and `ordinary`; writable states are `active` and `suspended`. The response to a
delete uses `revoked` for the retained identity. Password-changing accounts can
only read their session, change their password, or sign out until that change
is complete.

See [development checks](DEVELOPMENT.md) for verification commands.
