# DEC-13 Experimental Source Candidate Selection

**Decision:** `DEC13_EXPERIMENTAL_SOURCE_SELECTED_EXECUTION_GATED`  
**Owner instruction:** LM-01, 17 October 2026  
**Scope:** one bounded WP-B experiment candidate; no execution authority

## Selected source

LM-01 selects **LiteLLM v1.105.1**, commit `d665dc1a6315847fcad6cc2c1264ceb47c06abce`, for the proposed non-streaming OpenAI-compatible chat-path experiment. The proposed enforcement hypothesis is the out-of-tree request-context and HTTPX transport guard described in [Entry 02](wp-b-entry-02/DURANKI-DEC13-GATEWAY-CANDIDATE-02.md). Selection fixes source inputs for further preparation; it does not qualify the gateway or select an executable dependency set or target.

| Selected evidence | SHA-256 |
|---|---|
| [Source transfer bundle](review-evidence-02/SOURCE-INPUTS.zip) | `440c58e944b1c7eb4fdddce631d432911798610f5fb5e072a276e24c15127e65` |
| [PyPI source distribution](review-evidence-02/litellm-1.105.1.tar.gz) | `f1a274db0b2bcc78c34ed34c06df2c1dcd0dc038469193684927f6bb2cab2d97` |
| [Commit source archive](review-evidence-02/litellm-source-d665dc1a6315847fcad6cc2c1264ceb47c06abce.tar.gz) | `c8891f518f909a3470ec7fd2722cc31b545375319d5f236bdeffa0538b17fd05` |
| [Original source manifest](review-evidence-02/MANIFEST.json) | `9c3b65e3beb2f124f1a8ab7db5888d51312393b25b3854754595535ef4ed79c0` |
| [Repository evidence manifest](review-evidence-02/REVIEW-EVIDENCE-MANIFEST.json) | `5a94e3e462b0fa48f89821b5da28351094264df15fe0bf877d050ad2572b4e75` |

## Review and controlling receipts

- *DURANKI-WP-B-SOURCE-CONFIRMATION-REVIEW-03.md*, supplied at `/Users/larrymitchell/Downloads/`, SHA-256 `025dad753835241e22c193f65f9a920966b7cefed7b544ededfbbc987f1fb253`; companion validation SHA-256 `9cba6d6cb7e5612a4fcd2e2a2522c9fd2bde2dabc0e5a9a7fe8aa1a7b2a89eaf`.
- *Entry 02 Independent Review 02* is cited by Source Confirmation Review 03. Its original file was not supplied with this instruction or located locally; no independent hash is asserted here.
- Preserved Entry 02 receipts: [candidate 02](wp-b-entry-02/DURANKI-DEC13-GATEWAY-CANDIDATE-02.md) `11c4e71e029f7bc4db5d1a12f9f9913b9d085af36e38571e6f8af75c651e1d16`; [proof specification 02](wp-b-entry-02/DURANKI-WP-B-PROOF-SPEC-02.md) `262b26521e7e6d9dd845d82455352d85c1d965b9011a9ce4fd11cca30e7ba8e1`; [entry return 02](wp-b-entry-02/DURANKI-WP-B-ENTRY-RETURN-02.json) `4362791f2e4d5d1a8f601541538b4a9fdeac90058015d1be33763aa10ffd9f6c`.
- [WP-A/A2 adoption](../contracts/WP-A-A2-ADOPTION-01.md) and [accepted foundation](../foundation/WP-FND-ACCEPTANCE-01.md) remain unchanged. Earlier `PROPOSED` and `NOT_RUN` labels retain their historical meaning.

## Execution gates and limits

Source correspondence and static inspection support a *testable* session-injection hypothesis. They do not prove final-dispatch control. Before WP-B/B1 execution, establish an available permitted target; approve and receipt its exact Python, Rust, Maturin, proxy-extra and transitive dependency/build inputs; inspect the selected OpenAI SDK, HTTPX and lower transport sources; resolve artifact-specific trust, license/enterprise, advisory and security conditions; and separately issue the bounded experiment. The proposed macOS ARM64 VM and control route require factual availability and permission checks. An alternative target needs a new owner choice.

The eventual independent receiver proof must cover all nine Entry 02 groups, including guard-to-write cancellation/revocation, total elapsed timeout and bounded supervision, signed retry allowance, concurrent context isolation and same-receiver bypass detection. For B-08, global and request-specific `drop_params` must remain disabled and a synthetic 422 must not cause an unauthorized altered retry. The separate HTTP handler's new-client resend remains excluded or independently guarded. Static source review is not runtime, signature, gateway, security or operational PASS.

This record grants no dependency/runtime approval, security exception, signing-key trust acceptance, installation, VM operation, provider call or Vega connection. **WP-B/B1 and WP-C remain NOT ISSUED.**
