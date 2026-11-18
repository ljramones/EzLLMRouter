# Integration Readiness local release result

**Disposition:** `READY_FOR_VEGA_PLATFORM_INTEGRATION` for contract v1 and the local accounting service/client release. This is not Vega instrumentation, provider testing or production qualification. DEV-12 `CT02-02b` stays `OPEN` and technical qualification stays `PARTIAL`.

**Source:** `dev12/operation-contract`; start `f97612944639761d153c77b161c7730e32c71705`; tested product source `545acab617145ded973cd59c45775d9d9eed08ba` (tree `a54c2d21a91ca0b46e09742cbff9566b6c23a3a4`). The plan, contract and implementation commits are listed in [progress](../../plan/DURANKI-INTEGRATION-PROGRESS.md).

## Exact private release

Root: `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-readiness-20261027-01/final-release/`. All archives are version 0.1.0; API contract version 1. No hosted registry was used.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `duranki-integration-service-0.1.0.zip` | 820768 | `7d5c31cbd7d394447076639f7b327b868e4c8e533566c9324881d18fe78d5209` |
| `packages/mach33_duranki_server-0.1.0-py3-none-any.whl` | 136977 | `7c1a379961d599511e6c02d28fb675da6e9cd3c1a03e3270f4d566948f8eb2a0` |
| `packages/mach33_duranki_client-0.1.0-py3-none-any.whl` | 27880 | `8753d65387d52840006911d9379ae1d1eee535ff02c46ab8d2a8557e1d8df3ae` |
| `packages/mach33-duranki-client-0.1.0.tgz` | 21760 | `65512c34f548a19e66e4dfba786dcc01d4836038588970c26b2898b1399f3833` |

The self-excluding `MANIFEST.sha256` has SHA-256 `bb3e3486c7d4c975ce8f6315321f28c8d65f459445a2366ba28adef1847e3e04`; `shasum -a 256 -c MANIFEST.sha256` passed for every release payload. The ZIP contains the service wheel, both client archives, frozen Python dependency wheels, web assets, hash lock and [installation instructions](RELEASE.md). A separate clean extraction installed the service, Python hash-locked set and Node 24 tarball offline.

## Executed checks

| Check | Command or method | Observed result |
| --- | --- | --- |
| Contract | `/opt/homebrew/bin/python3.12 -I -S -B docs/contracts/integration-readiness-v1/check.py` | Exit 0; 11 positive, 6 negative, example USD 0.050000000 |
| Authenticated HTTP | `/opt/homebrew/bin/python3.12 -I -S -B -m unittest discover -s tests/operator_console -p test_integration_accounting.py -v` | Exit 0; 5 focused loopback tests |
| Build | `uv 0.13.5 build --wheel --offline` under Python 3.12.15; Node 24.22.1 `npm pack --offline --ignore-scripts` | Exit 0; archives above |
| Installed clients | `combined_release.py <isolated-final-run> seed`; `verify` after ordinary restart and separate backup restoration | Exit 0 each; Python/Node, receipts and amounts retained |
| Exact final-wheel ingestion | `package_smoke.py <isolated-final-run/package-smoke/secrets>` using the clean-installed service and Python client | Exit 0; one new non-model event, identical duplicate/recovered receipt, zero charge |
| Operator | `operator_smoke.py <isolated-final-run>` | Exit 0; login/CSRF, register/disable, report, controlled-route denial |
| Browser | `browser_smoke.cjs` against headless Chrome and packaged loopback service | Exit 0; 1440×900 and 860×900, 15 local GETs + 1 local login POST; no external page request |
| Upgrade | `upgrade_check.py seed` under immutable 0.0.0 starting wheel, then `verify` under clean-installed 0.1.0 | Exit 0; old synthetic principal retained, integration schema added, SQLite integrity `ok` |
| Manifest | `shasum -a 256 -c MANIFEST.sha256` | Exit 0; every release file matched |
| Source hygiene | `git diff --check`; focused JSON syntax, JS syntax and Python syntax | Exit 0 |

The installed demonstration calculates USD 0.030000000 for one attempt plus corrected USD 0.025000000 for another = **known USD 0.055000000**. The third included attempt has unknown cost, so this is a known subtotal. JSON and CSV select the same three attempts and reconcile to that subtotal. One attempt before activation is excluded. A duplicate event did not increase cost; a distinct model retry has its own attempt ID. After disabling an account, eligibility denied new use while late accounting for earlier work was accepted. The restored DB contains 16 external events, four start records including the excluded attempt, and zero rows in `submissions`, `dev12_submissions` or `dev12_send_ownership`.

Private screenshots: `final-run/browser-evidence/integration-desktop.png` SHA-256 `417a4a8a754146970dd618ba9396e773f01fdb44d7e2bad0f8ef191503bea2fc`; `integration-narrow.png` SHA-256 `b02d82d4eac8f109139f56e222a62e9fe92e4272d161be1a74154f1ceebaea66`. They contain synthetic records only. All disposable services and Chrome were stopped. No owner profile, operational DB, grant, real provider or sender campaign was changed.

**Limits:** The release is loopback SQLite with a 16 MiB JSON response bound and no report pagination. Its synthetic activation does not start a real Vega cohort. The platform still needs durable export, backlog/loss visibility, eligibility enforcement and execution-path instrumentation. PostgreSQL, cross-service authentication, deployment scale and invoice reconciliation are unqualified. The local artifacts have no claimed off-machine backup or registry publication.
