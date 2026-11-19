# Repository Guidelines

Read the [documentation index](docs/README.md), [architecture](docs/ARCHITECTURE.md), and the guide for the affected subsystem before making changes. Documentation describes the current EzLLMRouter implementation.

## Project layout

`server/` contains the Coordinator, persistent registry, operator API, and trusted sender. `web/` contains the operator console. `clients/` contains Python, JavaScript/TypeScript, Go, Java, C#/.NET and Rust clients. `deploy/local/inputs/` holds build metadata and the catalogue seed. `tests/fixtures/contracts/` holds machine-readable schemas, examples, vectors and conformance checkers. `docs/` contains current guides; generated evidence belongs outside it, under ignored `.artifacts/` or the configured private artifact store.

Use EzLLMRouter consistently in filenames, imports, packages, environment variables,
HTTP headers, schemas and documentation. Python implementations belong directly in
`ezllmrouter_server` and `ezllmrouter_client`. Do not retain former product names or
compatibility aliases for them. Update contract producers, consumers, resource
copies, canonical hashes and signed fixtures together when changing namespaces.

Do not recreate removed project documentation trees. Keep generated runtime data,
frozen dependency stores and build artifacts outside the tracked source tree.

## Build and checks

Use the pinned Python and Node versions recorded for the relevant slice. Run focused tests for changed code and `git diff --check`. Local socket tests need host loopback permission. The persistent profile uses frozen, hash-checked wheels and pinned base images; do not silently reacquire dependencies or substitute a gateway. Docker target work may require the owner Terminal because this executor has denied Docker access. Do not turn a source-only check into a model request or a profile restart.

For documentation or JSON changes, check links, evidence labels, source identities, and referenced counts. Validate edited JSON with `python3 -m json.tool` only in an environment whose Python startup files are known safe.

## LiteLLM supply-chain rule

**Never install, build from, run, or approve `litellm==1.107.0` or its `v1.107.0` image.** The official [October 21, 2026 incident report](https://docs.litellm.ai/blog/security-incident-oct-21-2026) says its PyPI wheels and Docker images were compromised. Do not use mutable LiteLLM image tags such as `latest`, `main-latest`, or `main-stable` as release inputs. A clean GitHub source tag does not establish that a published wheel or image is clean.

The current EzLLMRouter worker input is the offline `litellm==1.105.1` ARM64 wheel, pinned in `deploy/local/inputs/gateway/requirements.gateway.lock` with SHA-256 `beb5044645144308b39560049c0f68875ad7de07e681ad0b73e2bc6c3705ba61`. The worker is built from a pinned Python image, installs with `--no-index --require-hashes`, and has no network interface at runtime. These facts address the `1.107.0` incident for this profile; they do not approve every future LiteLLM release or every other environment.

Before proposing any LiteLLM update, check the **current** upstream incident notices and release notes, GitHub security advisories, PyPI metadata and yanked status, and the exact published wheel/image provenance for the proposed version. Check affected ranges for relevant CVEs and whether EzLLMRouter uses the affected interface. Pin an explicit reviewed version and artifact hash or image digest; inspect the wheel archive for unexpected startup hooks such as `.pth` or `sitecustomize.py` before installation. Rebuild and run the relevant offline worker, isolation, final-request, and installed-client checks. Record the source, check date, selected artifact hash, test results, and any remaining uncertainty in the current validation record. A higher version number or a changed Docker tag is not a safety finding. Do not change the frozen input or production acceptance state without the applicable release authorization.

If `1.107.0` or the named startup files are suspected in an environment, **do not run Python or pip there**: startup itself may execute the payload. Inspect with shell/archive tools that do not start Python, preserve evidence, and escalate containment and credential review for that environment. The absence of `cook.pth`, `cook.py`, or `sitecustomize.py` alone does not prove an environment clean. Do not delete files or rotate credentials solely because another environment uses LiteLLM.

## Changes and evidence

Use short imperative commit subjects and selectively stage only reviewed files. Preserve exact IDs, prices, grants, historical attempts, and source/target attribution. Never add provider credentials, production prompts, customer payloads, generated local secrets, or private database contents to Git. In a review handoff, report what changed, what ran locally or in the owner target, the source commit, observed results, and open limits. Push normally to the approved internal remote when the task authorizes it; never force-push or publish evidence elsewhere without authorization.
