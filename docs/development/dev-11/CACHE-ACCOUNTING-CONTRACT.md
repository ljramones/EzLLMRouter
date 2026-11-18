# DEV-11 cache-aware Responses text contract

**Version:** `openai.responses.implicit-cache.v1` with usage semantics
`openai.responses.text.cache.v2`. This is an executable contract format, not an
approved commercial model or a claim about current commercial prices. The
owner profile has no selected DEV-11 model, rate, key or allowance.

## Eligibility and request domain

A provider price publication is immutable and names one exact requested and
returned API model, a reviewed source URL and observation date. The registry
requires four exact USD rates per million tokens: ordinary input, cached read,
30-minute cache write and total output. The contract asserts implicit/default
30-minute caching, no 12-hour writes, one price tier without modifiers, a
provider-enforced input context ceiling, a maximum output-token setting and
support for the selected recipe's `temperature: 0`. The existing recipe is
`store:false`, non-streaming system/user text with no tools, cache control,
fallback or retry. The operator must verify these facts for the exact model;
the UI does not infer them from a catalogue label. Explicit TTL/key controls,
long-context rate bands and other paid features are outside this version.

The provider-enforced context ceiling is the input bound: an accepted request
cannot contain more billable input tokens than that model limit, regardless of
UTF-8 byte length, tokenizer ratio or framing. The admitted output limit must
be at most the contract's maximum. The contract is eligible only if its
reviewed single-tier conditions cover the entire admitted domain. If a model
can bill beyond this context limit or apply another rate condition, this
contract must not be published or activated. The local 4,096-byte text cap is
retained as a handling limit; it is not used as a token-count proof.

Before sending, Coordinator policy and the atomic personal campaign both use
the same `exposure_bound` function:

`ceil_nano(input_ceiling × max(ordinary, read, 30m_write) / 1,000,000 + output_limit × output_rate / 1,000,000)`

The input categories are disjoint, so charging all possible input tokens at
the highest applicable rate bounds any mix, including a cold write. The
bound is reserved before the trusted sender and is not a predicted cost or an
account-wide invoice ceiling. Price/model/grant/key revision changes are
checked again before first transmission. Historical two-rate provider prices
stay stored but cannot activate a new paid personal campaign.

## Usage observation and settlement

The frozen worker serializes its parsed response with `exclude_unset=True`;
the trusted sender copies only allowlisted usage fields that were present.
The ledger retains bounded counters and their `absent`, `null`, `known` or
`invalid` states, plus the raw usage digest, contract/price versions and
calculated amount. It does not retain an unrestricted provider response,
prompt or secret for accounting. The public client wire remains v0.2;
additional accounting metadata is available through the authenticated
operator projection under the existing retention/access rules.

For a complete cache-bearing observation, `input_tokens`, `output_tokens`,
`total_tokens`, cached reads, aggregate writes and both lifetime write counts
must be explicit nonnegative integers. `total_tokens` equals input plus
output; reads plus writes cannot exceed input; 30-minute writes equal the
aggregate and 12-hour writes must be zero. Unexpected usage-detail keys,
contradictory totals, an unapproved returned model or quantities beyond the
reviewed ceiling leave the cost **unknown** and preserve exposure. Reasoning
tokens are a subset of output. If that diagnostic split is absent or null,
the full output total is still chargeable at the one output rate; an invalid
or larger-than-total reasoning count is a discrepancy.

For valid disjoint input counters:

`ordinary = input_total − cached_read − cache_write_30m`

`cost = round_half_even_nano((ordinary × ordinary_rate + cached_read × read_rate + cache_write_30m × write_rate + output_total × output_rate) / 1,000,000)`

The aggregate write count is a consistency check, not another charge;
reasoning is not added again to output. A positive raw amount that rounds to
zero stays unknown. Missing required write evidence never becomes ordinary
input or a free write. The internal cost is calculated, not invoice-reconciled.
Existing campaign behavior preserves unknown exposure across restart and
pauses further sends. A calculated amount above its reservation is retained
as `over_bound`, displayed in incurred cost and pauses the campaign. The
existing explicit reconciliation applies the latest linked usage revision's
delta once; it does not replay provider work or rewrite predecessor rows.

## Evidence and limits

The [25 October assessment](../../research/2026-10-25-cache-accounting-assessment.md)
separates provider documentation, frozen-version behavior and controlled
observations. The OpenAI [prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching)
was rechecked on 25 October 2026 for disjoint cache counters, lifetime
details and model-dependent price multipliers. The frozen worker is still
LiteLLM 1.105.1 and OpenAI SDK 2.54.0 from the hash-checked gateway lock.
The controlled receiver uses fictional rates and usage; it proves route and
arithmetic behavior, not real provider acceptance, cache residency, physical
KV reuse, latency savings or invoice accuracy.
