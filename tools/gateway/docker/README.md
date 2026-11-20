# Exploratory gateway build harness

This directory retains an exploratory build harness. Its original plans and
review records are available in Git history through `1932889`; they are not
current setup instructions or authorization to run a model.

Use the [local execution profile](../../../deploy/local/README.md),
[current input metadata](../../../deploy/local/inputs/README.md), and
[development guide](../../../docs/DEVELOPMENT.md) for the supported source layout.


Retained-input paths are configurable through `EZLLMROUTER_BUILD_INPUTS`,
`EZLLMROUTER_LITELLM_SOURCE` and `EZLLMROUTER_HANDOFF_ROOT`. Defaults use the ignored
`.artifacts/retained-inputs/` area and the current user's Downloads directory.
`EZLLMROUTER_REVIEWED_UV` selects the already reviewed executable; the original
artifact and executable hash checks still apply. This historical tool does not
replace the current local profile's frozen-input workflow.
