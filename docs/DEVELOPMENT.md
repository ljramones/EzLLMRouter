# Development and verification

Run commands from the repository root: the directory containing `pyproject.toml`,
`uv.lock` and `.nvmrc`.

```sh
nvm use
uv sync --locked --all-groups --python 3.12.15
uv run --locked python -m tools.check
uv run --locked python -m tools.check --http-only
```

The first check runs Ruff, formatting, mypy, JavaScript syntax checks and the
maintained offline regressions. Offline tests reject network connections and
listener binds; local IPC pairs support framing checks. The second check runs
HTTP and TLS fixtures against localhost and requires permission to bind sockets.
These commands use temporary stores and controlled fixtures, with no model calls.

Go and Java clients are independent packages with no external runtime dependencies.
Use the Go version in `clients/go/.go-version` and JDK 17+:

```sh
bash tests/client_languages/check.sh
bash tests/client_languages/check.sh --http
```

The first command runs Go formatting, vet and race checks, then compiles a Java
17 JAR with all compiler warnings treated as errors and tests that packaged JAR.
Both languages run the shared contract cases in `tests/client_languages/cases.json`.
The Python suite checks those cases against the existing Python client and verifies
that embedded schemas match their adopted sources. The second command uses a
disposable localhost fixture to test the native transports. It requires loopback
permission and sends no model requests. Native checks run in a separate CI job.

Additional client checks need TypeScript 5.9.3, a .NET 10 SDK and the Rust
toolchain declared in `clients/rust/rust-toolchain.toml`:

```sh
bash tests/client_languages/check_typescript.sh
bash clients/dotnet/build.sh test
bash tests/client_languages/check_rust.sh
```

TypeScript consumer fixtures compile against the packed npm package in CommonJS
and NodeNext modes. `--package-only` checks exports and declaration syntax but
omits the compiler type check. .NET tests consume the locally packed NuGet
package without external package sources. Rust runs the shared contract cases,
Clippy correctness checks and Cargo package verification. Rust dependency
acquisition is separate from the service's frozen gateway inputs.

After building the native packages, run their explicit HTTP fixtures with
`python3 -I -S tests/client_languages/http_fixture.py --client dotnet` or
`--client rust`. CI has separate jobs for .NET, Rust and TypeScript. A missing
SDK, incompatible compiler or denied localhost bind must be reported as an
unverified check rather than a passing result.

## Browser journeys

The Playwright suite exercises the real operator HTTP application, browser assets
and SQLite store in Chromium, Firefox and WebKit. Each test starts a disposable
service with synthetic accounts, catalogue data, execution metadata and external
accounting observations. Local server discovery uses a fixed loopback HTTP
metadata fixture. Cloud model discovery uses a deterministic adapter injected at
the external provider boundary, with real encrypted credential storage and
policy updates. The harness rejects external connections and model execution.

After installing the root locked Python environment, run:

```sh
cd tests/playwright
npm ci --ignore-scripts
npx playwright install chromium firefox webkit
npm run typecheck
npm test
```

Use `npm run test:chromium` for a focused local run or `npm run test:headed` to
watch a Chromium session. `npm run test:list` lists cases without replacing the
last HTML or JSON report. `EZLLMROUTER_TEST_PYTHON` can select an existing locked
Python executable; otherwise the harness uses the repository's `.venv`.
Browser runs require permission to bind localhost and start browser processes.

The suite covers first sign-in, password changes, accounts, role boundaries,
navigation, stale and failed requests, provider credential setup, local connector
discovery and model selection, catalogue CRUD, activity, accounting corrections
and report downloads. Service controls use a private stdin protocol; no test
control endpoints are added to the application. Existing service instances,
credentials, model servers and deployment volumes are not test inputs.

CI runs all three browser projects separately. Failed runs retain screenshots,
traces, a JSON result file and an HTML report under ignored
`.artifacts/playwright/`. Fixtures use synthetic credentials because traces can
include entered values and HTTP bodies.
Run `npm run report` to inspect the local HTML report.

## Test and build inputs

| Location | Purpose |
| --- | --- |
| `tests/fixtures/contracts/` | Schemas, examples, vectors and standalone conformance checks. |
| `deploy/local/inputs/catalogue.json` | Model catalogue seed used by import and display checks. |
| `deploy/local/inputs/gateway/` | Frozen gateway lock, wheel inventory and advisory metadata. |
| `server/` and client package resources | Runtime copies of supported schemas. |

Data fixtures retain their exact IDs, rates, protocol fields and hashes. Moving
a fixture does not change its contract. Keep runtime schema copies consistent
with their source fixtures when making an authorized contract change.

Generated run evidence belongs in ignored `.artifacts/` or a configured private
artifact store. Keep databases, credentials, keyrings, build archives and run
logs out of the documentation tree and Git. Use fresh namespaces for controlled
test runs; never overwrite a retained run.

## Validation boundaries

Passing local checks does not establish Docker deployment, provider execution
or production readiness. The optional execution profile requires verified frozen
inputs and its own deployment checks. Preparing documentation or building a
package does not authorize a model call, spending or an instance restart.
