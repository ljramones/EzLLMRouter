# Local profile inputs

`catalogue.json` is the reviewed catalogue seed used by the local importer and
catalogue display checks. `gateway/` holds the frozen requirements lock,
117-wheel inventory and advisory comparison input.

`requirements.runtime.lock` selects the trusted service's 11 dependencies from
that same reviewed lock, preserving their exact versions and hashes. It excludes
LiteLLM and its provider/proxy dependency tree. The current Python client wheel
is built and verified separately. No worker input is replaced by this subset.

The catalogue uses the EzLLMRouter schema and registration fields. Gateway
wheelhouses, credentials and Docker images remain in their configured private
stores; they are not acquired by reading or editing these manifests.

Use [the local profile guide](../README.md) for preparation and
[the security policy](../../../docs/SECURITY.md) before updating dependencies.
