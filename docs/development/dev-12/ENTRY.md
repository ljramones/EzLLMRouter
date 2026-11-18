# DEV-12/A1 entry and custody

## A2–A4 implementation adoption — 26 October 2026

Larry Mitchell forwarded the bounded A2–A4 implementation instruction and thereby adopted the independently reviewed A1 candidate 04 as the exact implementation baseline. The starting checkout was `dev12/operation-contract` at commit `78886a871807a018bed1ae8f62176102307a699c`, tree `d6a75b83939452ad243663378e34eb2b2f20db9e`, with a clean index and tracked worktree. The preexisting untracked owner architecture files and export prompt remain untouched. The baseline manifest is [A1-CANDIDATE-04-MANIFEST.sha256](A1-CANDIDATE-04-MANIFEST.sha256), SHA-256 `4f97621799100254d556c70806e3f6032a55d8c4acf4d1a0c28b2e93f59409a4`; the exact A1 review ZIP is 1,316,209 bytes, SHA-256 `1f7e054112d224d6363529360492e192d2703dab7b770422b863ffeeeef5da72`. The new entry ZIP's 12 manifest payloads verified. The review closeout disposition is `PASS_READY_FOR_A2_A4_IMPLEMENTATION`. The current branch's approved origin is `git@github.com:33fg/duranki.git`. A2–A4 delivery uses the existing standalone SQLite profile and separately selected wire 0.3; no owner-profile update or commercial authorization follows from this adoption. Actual changed paths and scoped results belong in the living [RESULT.md](RESULT.md) and [REVIEW-HANDOFF.md](REVIEW-HANDOFF.md).

On 25 October 2026 Larry Mitchell instructed Codex to begin DEV-12/A1 and explicitly **adopted v1.2 Correction 01 + Erratum 01 as finalized by Review 04**, with the saved phase plan as delivery sequence. This is architecture-basis adoption now, not a claim of earlier adoption, operational acceptance, or adoption of this exact successor candidate. Historical draft/review labels in the owner package remain unchanged. PostgreSQL remains the selected production engine; standalone SQLite is retained.

The supplied locator `docs/architecutre/duranki-v1.2-c01-finalization-01/` is absent. The unique actual package is `docs/architecture/duranki-v1.2-c01-finalization-01/`; it was not renamed. The owner's prompt was read from `/Users/larrymitchell/Downloads/Duranki-DEV12-A1-Codex-Prompt.md`; the proposed in-repo `docs/plan/Duranki-DEV12-A1-Codex-Prompt.md` was absent at start and then copied byte-for-byte from Downloads (SHA-256 `6ab1bb2d7b07ca26ce5578bed7dd800bf04c62b0b9d953a2bc0fd3b659c01701`). The phase plan is at `docs/plan/Duranki-Implementation-Phase-Plan.md`. Supplied owner package and plan were untracked at entry and are not silently treated as prior Git history.

| Checked input | SHA-256 |
| --- | --- |
| phase plan | `a4a8a5d482d04262660b6f893002c0235c2ead8c7888e5aa10099e3ce35c1ac5` |
| final architecture correction | `fa0229f2e61dce103557b6f51fa63f1a521cd7261799166225a56e5b99da883c` |
| Review 04 closeout | `b2e7596efe1c6e4a023e82f3590395fae40cf639336a3d80e73435f46e337a63` |
| roadmap | `afdc60ceb649a9cf73cc0710fc8dd6713574c958d240ceaaafe88f314d2c2c07` |
| fictional tariff vectors | `d13a03a6ad22c824649dea16fd1d0ff5e26d22c5b101618670d4956f48b44697` |
| finalization manifest | all listed files verified by `shasum -a 256 -c MANIFEST.sha256` |

The checked starting branch was `dev11/cache-aware-accounting`, HEAD `d990b78ca48b8e673c0cbd0260d3e141e45c7e48`, tree `8534c4f031a1aa185d09a9711e143e7d5bdf65ed`, and index SHA-256 `9256bdf99800f8fbc168a05ac5c76efc59b2bcd2412ee8e44ea3a1257aa8f4d6`. Worktree additions at entry were only the owner package and phase plan; index was unchanged. The approved origin is `git@github.com:33fg/duranki.git` (the `33fg/duranki` internal repository). DEV-11 result and handoff were read as current evidence; prior commits were not reset targets. A dedicated `dev12/operation-contract` branch descends from that HEAD; `main` is behind this descendant.

The baseline package is preserved byte-for-byte. This A1 packet stages only explicit safe review files; owner-supplied untracked package history, ZIP, docx and other inputs remain in place unless individually named in the scoped commit. No owner profile, credentials, operational state or legacy contract was changed.
