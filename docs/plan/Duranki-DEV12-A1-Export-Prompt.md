# DEV-12/A1 — export the exact candidate for focused review

Work in `/Users/larrymitchell/Mach33/Duranki` and follow its existing instructions.

The reviewer has received `CONTRACT.md`, `RESULT.md`, `A2-A4-MAP.md`, and the separate historical DEV-05–DEV-10 capture. The historical capture independently verifies; do not repeat it. The missing item is the complete normative A1 packet, including schemas, vectors and conformance sources.

## Immutable source

Export from:

```text
commit: 0ee1d9086c2dc1f1ec00c5390020f34103d49235
manifest: docs/development/dev-12/A1-MANIFEST.sha256
expected manifest SHA-256:
b6d953660e249460e0ba975e8134448386b0a96ca22be0e41b3cbd73b5da5c73
```

Use read-only Git plumbing such as `git show <commit>:<path>`. Do not switch branches or assume the current working copy equals the candidate. Verify the commit exists and the manifest bytes match. A different current HEAD is not a reason to export different candidate bytes.

## Packet contents

Include the original A1 manifest and every path it covers, preserving repository-relative layout. Resolve the manifest's actual recorded path convention rather than guessing its base directory. Independently verify each covered payload hash against the committed bytes.

In particular, include the complete committed `docs/contracts/dev12-successor-01/` candidate: `CONTRACT.md`, `schemas.json`, `vectors.json`, `tariffs.json`, both conformance programs, and all local reference/helper/fixture files they need. Include the candidate's entry, result, review handoff, A2–A4 map, validation records and `EVIDENCE-MAP.md` from `docs/development/dev-12/` where present. Include any small local dependencies needed for the offline checks that are not already in that manifest; identify these separately as supplemental committed dependencies without changing the original manifest or pretending it covered them.

Read source only to identify dependencies and safe export scope. Do not run the checker, import product code, regenerate goldens, or change the candidate during this export. Do not resolve references over the network.

Do not recopy the full architecture history, frozen wheels, images, live databases, operational logs, credentials, cookies, signing secrets, or the separately delivered historical ZIP unless the original candidate manifest requires a specific safe source document. An unexpected secret means withhold that payload and report the exact custody issue; never silently redact while labelling a file byte-identical.

## Output and safeguards

Create one fresh collision-checked directory and portable ZIP outside the repository, under the existing owner artifact root. Keep all original repository paths beneath `repo/`, including the unmodified original A1 manifest. Write transport metadata outside `repo/`:

- A capture receipt identifying source commit, each original path, Git blob ID, SHA-256, byte length, original-manifest role or supplemental role, and verification result.
- A short README stating how to verify the original candidate manifest and which sources were exported.
- A self-excluding transport SHA-256 manifest for all exported payloads and capture metadata. Its hash is distinct from the original A1 manifest hash.

Check safe unique ZIP paths/types, CRC, exact transport-manifest coverage and payload hashes. No symlink traversal or arbitrary absolute paths. A Git blob ID is not a SHA-256 digest.

Bracket the export with HEAD/index/status checks and require no repository changes caused by it. Preserve the owner-supplied unstaged/untracked architecture remainder and existing Markdown hard line breaks. No reset, clean, stash, checkout, stage, commit, push, merge, build, Docker operation, runtime test, dependency acquisition, provider call, profile inspection or Vega work is requested or authorized here.

## Return

Return `A1_EXACT_REVIEW_PACKET_EXPORTED` only after the checks pass. Provide the actual absolute ZIP path, byte length, SHA-256, original A1 manifest hash, covered/supplemental file counts, and any absent dependency or mismatch. Do not claim reviewer acceptance or start A2–A4.

The reviewer has identified a preliminary prose conflict about defaulting an absent commission to a canonical `caller_omitted` reason. Preserve this candidate as-is for complete review; do not use this export instruction to amend it or the adopted architecture. A bounded correction can be made once the exact candidate is available for review.
