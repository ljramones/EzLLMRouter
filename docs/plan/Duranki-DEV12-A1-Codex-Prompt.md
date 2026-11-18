# Duranki DEV-12/A1 — successor contract and executable conformance

**Owner:** Larry Mitchell / LM-01  
**Instruction:** First working assignment under the saved implementation phase plan. Operative when supplied by the owner to Codex.  
**Completion point:** A source-grounded, executable contract candidate ready for focused independent review. This is not another architecture review and does not authorize A2–A4 product changes before that contract is reviewed and adopted.

## 1. Start from the saved plan and finalized architecture

Work in `/Users/larrymitchell/Mach33/Duranki`, after confirming the physical repository root and reading its applicable `AGENTS.md` instructions.

The owner saved the delivery plan at:

`docs/plan/Duranki-Implementation-Phase-Plan.md`

The owner reports the finalized architecture package at:

`docs/architecutre/duranki-v1.2-c01-finalization-01/`

Use that spelling as a locator, not as an instruction to rename anything. Resolve the actual package directory from the checkout. If the literal directory is absent, inspect the immediate documentation layout for the uniquely matching finalization package; identify it by content and hashes. Do not silently select an older architecture, create another architecture tree, or perform a directory cleanup. Record the paths actually used.

Read the finalized architecture, Review 04 closeout, roadmap, assurance register, fictional tariff vectors, and relevant existing adopted WP-A/A2 contract, schema and golden-vector files. Read only the historical material needed to establish the affected semantics; do not restart the entire review history.

These full SHA-256 values identify the supplied design inputs:

| Input | SHA-256 |
|---|---|
| `Duranki-Implementation-Phase-Plan.md` | `a4a8a5d482d04262660b6f893002c0235c2ead8c7888e5aa10099e3ce35c1ac5` |
| `DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md` | `fa0229f2e61dce103557b6f51fa63f1a521cd7261799166225a56e5b99da883c` |
| `DURANKI-v1.2-C01-REVIEW04-CLOSEOUT-01.md` | `b2e7596efe1c6e4a023e82f3590395fae40cf639336a3d80e73435f46e337a63` |
| `DURANKI-v1.2-C01-ROADMAP.md` | `afdc60ceb649a9cf73cc0710fc8dd6713574c958d240ceaaafe88f314d2c2c07` |

Check the governing files against these identities and the finalization manifest. Distinguish a file mismatch from a harmless directory-name difference. Report a substantive mismatch precisely and do not implement against an unidentified baseline. The current architecture and Review 04 closeout govern any stale wording in preserved predecessor records or companion summaries: caller assertions are canonical, server assessments are not; standalone SQLite keeps its qualified gate ordering.

**Owner direction upon issuance of this prompt:** I adopt v1.2 Correction 01 + Erratum 01, Review 04 finalization 01, as the architecture basis for this implementation program, and the saved phase plan as its delivery sequence. Record this instruction and the checked identities in a small additive entry record. Do not rewrite historical `draft`, `not adopted`, `not run` or review labels inside the preserved package. PostgreSQL remains the selected production engine; this does not authorize replacing standalone SQLite. Exact successor contracts remain candidates until their focused review and owner adoption.

## 2. Establish the actual starting point

Record current branch, HEAD, tree, index/worktree status and the approved remote without exposing embedded credentials. Inspect relevant current source and existing DEV-11 records before interpreting an empty assurance cell as missing code. Older commit IDs are evidence locators, not reset targets. Identify later legitimate changes and preserve them.

Trace the surfaces this contract will affect: strict wire parsing and capability negotiation; canonical work and WorkKey lookup; clients; trusted admission and signing; final guard/sender and authority revisions; registry permission and administrative idempotency; SQLite records/migrations; usage/price evaluation and reporting. Include the frozen adapter preparation seams needed by the two future retrieval operations. Use inspected files and line ranges, not assumed current APIs or advertised library support.

Do not alter product source to make the proposed contract fit. Select concrete, bounded contract decisions consistent with the architecture; do not return a list of ordinary naming choices for the owner to resolve. Escalate only a specific material contradiction, unavailable essential source or unavoidable scope change. Continue unaffected A1 work where possible.

## 3. Produce the exact successor contract

Deliver actual machine-readable schemas, canonical examples and executable offline checks, not just recommendations to create them. Use a new, bounded contract directory such as `docs/contracts/dev12-successor-01/`, following an existing equivalent convention where appropriate. Keep original contract files unchanged.

### 3.1 Versioning, request/result shapes and compatibility

Choose explicit candidate wire, capability-profile, operation-contract, projection and schema identifiers. Define protocol selection, version mismatch, capability reporting and the supported typed request/result union. The initial new operations are bounded synthetic embedding and reranking. Unsupported operations reject; a catalogue entry does not enable execution.

Preserve strict legacy wire `0.2`, `duranki-work-v0.2`, existing golden bytes/digests, installed-client behavior, and caller-owned tool cycles. Do not relabel all old work as plain text. Define cross-version submit/status/recovery behavior so changing a protocol label cannot create a second send for the same logical work. Keep operation type/version, administrative command ID, submission/attempt ID and execution generation distinct.

Specify unknown-field behavior, null versus omission, resolved defaults, identifier/length/depth/item bounds, numeric domains, Unicode handling, ordering, response validation and error meanings. Request binding and provider-result representation are separate domains: vector coordinates and ranking scores need an explicit finite-number/precision contract, not accidental rejection or rounding by the legacy work serializer.

### 3.2 Canonical work, signed admission and execution context

Preserve the complete authenticated WorkKey namespace: principal, task, step, step revision and execution generation. Define operation-domain-separated canonical bytes and digests unambiguously. The service remains authoritative for authentication, trusted context and canonicalization; a caller-supplied digest does not grant authority.

Put the common metadata envelope into this successor now, not a later integration version. The binding rules are fixed:

| Data | Required treatment |
|---|---|
| Caller commission reference, ordered delegation assertions, caller-declared reasons and contractually stable trusted identity | Canonical work, including an explicit rule for omission/defaults |
| Server-assessed commission status, verification/coverage and server-assigned absence reasons | Immutable signed admission snapshot linked to the work digest; excluded from deduplication identity |
| Activation epoch/context and applicable reason | Signed execution context; not a new WorkKey or permission to replay |
| Later verification, trace/timing and diagnostic observations | Linked evidence; no rewriting of original work or admission snapshots |

Define valid metadata combinations, event applicability, trusted identity binding, limits and lineage. Include direct-human, delegated-agent and autonomous-service fixtures without invented people or verified intermediate links. Standalone asserted commissions remain record-only; absent integration authority is not simulated as production verification. Absence reasons never waive authority required by a profile. Keep metadata absence, assertion/verification evidence and provider usage evidence as separate axes.

An unchanged WorkKey and unchanged caller assertions must recover the existing submission despite improved or unavailable server assessments. That recovery adds no attempt, reservation or send and still obeys current access/retention controls. Changed caller assertions conflict. A newly required commission cannot be bypassed through old-work recovery.

### 3.3 Signing, final preparation and authority lifecycle

Specify the signed-plan and admission-snapshot linkage, exact candidate preparation inputs, final bytes/transport-control checks, key ID/version and relevant authority dependencies. Preserve the isolated worker and exclusive trusted sender; do not introduce a network-capable retrieval adapter outside that boundary.

Retain the DEV-07 single-process SQLite ordering: under the existing first-write gate, commit authority/audit/revisions, publish the matching sender view, release the gate, then acknowledge. Do not impose the replicated-profile ordering on DEV-12. Existing no-repeat ownership, would-block freshness checks and post-send uncertainty remain requirements.

Distinguish routine signing-key rotation from revocation. Old, non-revoked versions may verify already-issued unexpired plans; revoked versions must block unsent work at final dispatch and first write, including after a lower wait. Key eligibility is an authority dependency, not simply the active minting-key selector. Replacement signing cannot authorize replay. Specify the offline vectors and later composed discriminators; synthetic key tests do not qualify managed production custody.

### 3.4 Retrieval semantics and native accounting

For embeddings, bind ordered batches, document/query role, model/configuration, vector-space profile and corpus/index version references. Define output count, order, dimensions, finite values and treatment of malformed or partial results. Equal dimensions alone do not prove compatibility. Index writes remain caller/corpus-owner effects, not gateway side effects.

For reranking, bind the query, ordered candidate identities/content, bounded result selection and applicable settings. Define ID/index correspondence, ordering/tie rules and rejection of duplicates, omissions or out-of-domain results under the selected contract. No silent truncation, semantic substitution or unrecorded fallback.

Define lossless native usage components and price/usage references, preserving missing, null, explicit zero and invalid evidence and distinguishing reported from derived or estimated quantities. Result delivery and financial completeness remain independent. Successful output does not force settled cost; failure does not imply zero cost.

Reuse the supplied fictional Tariffs A and B and their complete admitted domain. Preserve minimum/unit ceilings, whole-request tier boundaries, per-attempt half-even settlement, upward exposure rounding and separate-versus-batched request treatment. Check maximum exposure independently across every admitted cardinality. Do not invent commercial rates, infer missing usage from fixture expectations, or weaken DEV-11's positive-raw-rounded-to-zero safeguard.

Propose the concrete additive SQLite storage and migration design, including stable assertion envelopes, signed assessments, activation context and append-only verification evidence. Usage components belong to attempt **and usage revision**; replacements are applied once, not added as new charges. Preserve old rows, digests, prices and evidence without fabricated backfill. Describe the future PostgreSQL mapping without implementing or deploying it here.

Define the future composed example: corpus ingestion once, query embedding separately, reranking separately, and direct/inclusive views reconciled to unique attempts. Propose the minimal existing UI projection changes needed for operation, native usage, uncertainty and exposure. Do not build a new UI or vector store in A1.

## 4. Execute offline conformance work now

Use the repository's existing pinned/local tools. New schema and vector validators and isolated contract-reference implementations are allowed. Run only pure, offline contract/data checks: no service startup, provider receiver, socket experiment, Docker, database migration or dependency acquisition in A1. Do not import application entrypoints with runtime side effects. Resolve schemas locally with remote retrieval disabled.

Produce independently checked expected canonical bytes/digests and tariff amounts. Do not generate expectations by invoking the product function that will later be tested and then call agreement independent. Provide Python/CommonJS cross-checks where the inspected local toolchain supports them; otherwise record the exact unexecuted check without silently using an unapproved runtime.

The corpus must cover valid direct/delegated/autonomous requests; object-key equivalence and ordered-content sensitivity; operation/version separation; raw duplicate-key and unsafe-number rejection; metadata combinations and size bounds; server-status changes that do not alter work identity; changed caller assertions that do; tampering with signed assessment linkage; rotated versus revoked key semantics; embedding/index incompatibility; malformed retrieval results; and the native-unit tariff/evidence boundaries.

Separate shape validation, semantic/canonical calculations, synthetic cryptographic checks and planned runtime assertions in the result. Offline vectors cannot demonstrate actual revocation races, no-send behavior or retained exposure across a service crash.

Prepare a focused A2–A4 implementation map naming inspected file surfaces, actual additive migrations, client packaging impact, disposable test needs and exact applicable assurance subcases. Reuse existing IDs and evidence. Map the roadmap's DEV-12 test set, including applicable shared-envelope cases and the finalized key/deduplication subcases. Do not mark broad architecture parents passed or add a second assurance numbering system.

## 5. Recover historical evidence as a separate read-only substep

Use the finalization package's `DURANKI-DEV05-10-EVIDENCE-CAPTURE-PROMPT.md` and `EVIDENCE-CAPTURE-PATHS.json`. Capture the 22 anchored paths from the named immutable commit, verify Git object identities and separately compute SHA-256 values. Keep newer records separately attributed.

Bracket this capture with its own HEAD/index/status observations and perform no A1 edits or Git writes inside that bracket. Its outputs belong in a fresh collision-checked external artifact directory. Do not conflate the capture's no-change assertion with legitimate A1 writes before or afterward.

Map only retrieved evidence to specific requirement scopes in a separate working supplement; leave the hash-identified architecture package and its original register unchanged. Unavailable records remain an evidence gap, not a reason to rerun historical experiments, claim missing implementation or block unrelated contract work. Do not access live SQLite, credentials, environment dumps or operational endpoints.

## 6. Deliverables and repository custody

Produce one compact A1 handoff with:

| Deliverable | Content |
|---|---|
| Additive entry record | This owner instruction, actual paths, checked baseline hashes and current source identity; no invented earlier adoption |
| Exact contract candidate | Complete semantics, identifiers, compatibility and additive migration specification |
| Schemas and vector corpus | Machine-readable bounded schemas, canonical bytes/digests, expected positives/negatives and native-unit examples |
| Offline conformance checks | Reproducible commands/programs, actual tool identities, results and explicit limits |
| A2–A4 implementation map | Source-grounded changed surfaces, sequence, applicable subcases and proposed controlled target scope |
| Evidence capture and mapping | External bundle locator and scoped supplement; missing records explicit |
| Living result and review handoff | One `docs/development/dev-12/RESULT.md` and `REVIEW-HANDOFF.md`, or reuse their existing equivalents without overwriting another assignment |

Use a self-excluding SHA-256 manifest for the small review packet. Reference the existing architecture package instead of copying its entire history into a new archive. Keep safe reviewable contract material in Git; keep bulky exports and forbidden content out. Record custody of any owner-supplied untracked inputs rather than bulk-staging them.

This owner instruction authorizes a dedicated feature branch such as `dev12/operation-contract`, scoped commits of A1 deliverables and a normal non-force push to the existing approved internal `33fg/duranki` origin. Verify its identity without displaying secrets. Inspect branch ancestry; do not assume `main` contains the latest DEV-11 work. If unrelated staged/working changes prevent a clean scope, use an appropriate isolated worktree or leave the publication blocked with the precise reason. Never reset, clean, stash, amend someone else's commit, force-push, merge main or change the remote. Do not trigger a coupled deployment or paid CI workflow to publish this work. Remote-access failure does not prevent producing local deliverables.

No production service/client/UI behavior changes, owner-profile update, PostgreSQL migration, new dependency acquisition, real key/model/rate selection, provider/discovery request, paid test, external cache, live retry/fallback, audio/media/realtime implementation, or Vega/Proto/Valhalla modification is authorized by this A1 instruction. Read-only inspection of affected source is authorized; code changes are limited to isolated conformance tooling and candidate contract material.

## 7. Completion and return

Complete all available A1 work in this assignment; resolve ordinary schema/vector/checker bugs rather than returning an unfinished outline. Do not reopen settled architecture or ask the owner to choose routine field names. If a genuine blocker remains, deliver the completed unaffected material and the exact blocking issue.

Return `READY_FOR_FOCUSED_CONTRACT_REVIEW` only when the candidate is complete and its stated offline checks pass; otherwise return a precise partial/blocker disposition. Include the contract/packet path and SHA-256, commit and verified remote standing when available, actual changed paths, executed checks, preserved legacy evidence, captured-record counts, remaining gaps and a brief A2 entry summary.

**Stop at this A1 review boundary.** The focused independent contract review and owner adoption apply to the exact candidate bytes; author self-checks are not that review. A2–A4 product implementation follows their acceptance under the next bounded instruction. Do not seek another full architecture approval, start WP-SPEND-IMPORT early, or treat successful contract checks as permission to activate paid work.
