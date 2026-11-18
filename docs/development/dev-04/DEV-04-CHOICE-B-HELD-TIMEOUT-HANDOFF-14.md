# DEV-04 Choice B held-timeout correction — Run-11 handoff

## Historical result preserved

Run-10's source packet SHA-256 is `cd9657157768ed00511033d454b6d3ac712734146e717f72f8f0bcc3f9274d65`; runtime packet SHA-256 is `28866c6d5ca0110900c90f50a0ebfecd1cc6ae84aa6991830f9e132d6eb487e8`. The supplied independent review verified 57 source and 315 runtime payloads. The held request reached the receiver, had an actual 1.0-second timeout in all four final-request timeout extensions, then truthfully became `outcome_unknown`. The queued attempt was rejected after the real selected pool wait, with no accepted local socket bytes or receiver arrival. The 5,202 ms late-send window was quiet. The original freshness verifier, work and run exits are all `1`; the corrected verifier still rejects that unchanged evidence.

## Corrected source and checks

The private proxy recipe now binds `timeout` to each signed attempt's budget and advances its text/tool recipe references to v4. Ordinary one-second work remains one second; held and queued thirty-second work requests thirty seconds. The expected private bytes, size and digest are recomputed. The status actor exports existing public terminal fields. The freshness verifier keeps the held `completed / present` requirement and checks the queued public `FDC_REJECTED / failed_before_dispatch` result, matching attempt identity, zero accepted bytes and no receiver arrival. It allows only `ContractError` or `GuardRejected` internally. Final trusted receipts must show 30.0 seconds for the held and queued attempts and 1.0 second for the three ordinary positives. The receiver's existing control-event log is captured and checked for entered, release and response-release order.

Fifteen local targeted regressions passed, including a real Coordinator freshness callback against an owned socketpair and synthetic verifier corruption controls. Ten frozen-version owned-sender and eleven existing Choice B tests passed. Python and shell syntax checks passed. These local tests exercise the inspected LiteLLM timeout resolver, but **actual LiteLLM/SDK propagation remains unobserved until Run-11**. The sender socket gate, worker isolation, frozen dependencies, installed clients and public contract are unchanged.

The final preflight packet `DEV-04-SOURCE-source-preflight-20261020-14-timeout-final.zip` has 59 source files and 117 frozen wheels, SHA-256 `22ea6f05bba75b94fc65b76ae2e5d61993c08838301e06bdf0329b26780afb3d`. Its source members match their manifest; the worker context still contains only the two worker Python sources. This excluded ZIP is absent from Git; local copies in the DEV-06 and DEV-09 artifact custody directories matched that hash on 25 October 2026. Off-machine custody was not established. The [local validation record](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-04/DEV-04-CHOICE-B-HELD-TIMEOUT-LOCAL-VALIDATION-14.json) lists the checks.

## One owner Terminal invocation

```sh
cd /Users/larrymitchell/Mach33/Duranki && ./tests/gateway_integration/run.sh run-20261020-11 choice_b
```

The runner rejects an existing run directory or packet, stages from the unchanged frozen inputs, builds through the existing Docker workflow, captures each step's output and exit, and performs scoped cleanup. Preserve the new run directory and packets for independent review, including any failed step. The target verdict requires the held positive to complete after controlled release, the queued request to remain untransmitted, the per-attempt final receipts to carry the expected actual SDK timeouts, and the receiver control log to show release chronology. A source or helper test alone is insufficient.

## Limits

The observed first-byte fact is a positive local `socket.send` return, not a physical network timestamp or remote provider receipt. Revocation is effective at the trusted local owner. Production TLS, remote authority propagation, complete task drain and whole-gateway acceptance remain open. The original 90-minute setup and eight-hour engineering caps remain cumulative; this iteration does not restart either.
