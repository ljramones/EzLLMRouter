# Local profile inputs

`catalogue.json` is the reviewed catalogue seed used by the local importer and
catalogue display checks. `gateway/` holds the frozen requirements lock,
117-wheel inventory and advisory comparison input.

The catalogue uses the EzLLMRouter schema and registration fields. Gateway
wheelhouses, credentials and Docker images remain in their configured private
stores; they are not acquired by reading or editing these manifests.

Use [the local profile guide](../README.md) for preparation and
[the security policy](../../../docs/SECURITY.md) before updating dependencies.
