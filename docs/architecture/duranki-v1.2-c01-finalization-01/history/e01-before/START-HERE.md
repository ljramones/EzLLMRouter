# Duranki v1.2 C01 + Erratum 01 — delta review package

**Status:** Document delta authored; independent delta review and owner adoption remain separate. No implementation or activation authority.

Start with [the short erratum](DURANKI-v1.2-C01-ERRATUM-01.md) and [architecture diff](deltas/ARCHITECTURE-C01-to-E01.diff). The [amended architecture](DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md) is a reading copy; the reviewed predecessor is preserved under `predecessor/`.

The core change is stable caller assertions versus signed server assessments, restored plan-key custody, and commit-outside-fence authority publication. Two new subcases plus two amended subcases address G-01/G-02. Existing T-48.g also gains the requested rounding pair. There remain 87 parent/alias IDs, now with 73 subcases and zero unqualified parent passes.

[Assurance register](DURANKI-v1.2-C01-ASSURANCE-REGISTER.md) · [Register JSON](DURANKI-v1.2-C01-ASSURANCE-REGISTER.json) · [Roadmap](DURANKI-v1.2-C01-ROADMAP.md) · [Finding/research map](DURANKI-v1.2-C01-REVIEW-AND-RESEARCH-MAP.md)

[Evidence supplement](DURANKI-v1.2-C01-EVIDENCE-SUPPLEMENT-01.md) maps available DEV-05/06/07 records; the DEV-05 source/runtime integrity check covers 76/431 payloads, not new execution. Final DEV-08–DEV-10 primary receipts and later DEV-07 records remain to be captured with [the read-only Codex prompt](DURANKI-DEV05-10-EVIDENCE-CAPTURE-PROMPT.md). N-02 is not declared closed.

[Delta index](REVIEW-DELTA-INDEX.json) · [Document validation](DURANKI-v1.2-C01-E01-DOCUMENT-VALIDATION.json) · [Reproducible document-only verifier](verify_document_delta.py) · [Package manifest](MANIFEST.sha256)

The old `ARCHITECTURE-C01-vs-SUBMITTED.diff` and predecessor validation are historical C01 artifacts, not the current erratum validation. All copied inputs remain unchanged. Current host/repository/profile state, provider billing, production key custody and Vega/Valhalla integration are unverified by this package.
