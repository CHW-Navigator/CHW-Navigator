# CHW Navigator compiler work log

## WS0 - Establish the executable baseline - 2026-08-05

**Delivered:** WS0 discovery reports and human decisions; corrected source-of-truth documentation; ADR-001; evidence semantics; a non-shrinking executable TypeScript overlap map; repaired Product baseline fixtures/contracts; a root-independent baseline verifier with structured manifest output; and GitHub issue #2 as the explicit triage lifecycle for the previously file-only Product security/reliability audit.

**Deviations:** Individual ignored environment paths were counted and classified by root rather than committed, because the common rules prohibit machine-specific scratch evidence. The old CSV `english_text` output-header assertion was explicitly superseded by canonical `text` output while retaining and testing legacy `english_text` input compatibility.

**Defects found:** Ambiguous repository roots and stale submodule/readiness claims; four Product baseline failures; two Product pytest collection warnings; one compiler official-harness skip; four Windows TypeScript symlink-security skips; a Windows Python-copy failure on stale generated oracle staging paths; unused Prompt B text; mini-manuals that do not test Prompt B; and no Product clinical-logic to canonical-IR adapter.

**Root cause:** Repository copies and prose claims were not bound to one commit/evidence manifest. The Product fixture, converter expectations, and tests were committed without an enforced combined root gate. Framework skip output was not elevated into release semantics. Product and compiler IR contracts evolved independently.

**Generalized guardrail:** `verify_repository_baseline.py` executes and recounts the compiler, Product, and disposable-copy TypeScript suites; uses Windows-native copy semantics for the oracle and converts copy failures into structured results; preserves every non-pass status; checks source lock, source-truth phrases, overlap-map invariants, work-log completeness, dirty state, and archived-evidence misuse; and fails release mode for dirty source, required skips, warnings, or other non-pass results. Focused tests assert copier return-code semantics, activator-module closure, router/activator policy selection, and legacy-input/canonical-output CSV behavior. File-only audit findings are now linked to GitHub issue #2, where each must receive an evidence-backed disposition or a focused child issue.

**Status ledger:** Combined executable baseline: 849 pass, 0 fail, 5 skipped, 0 not_run across 854 tests. Compiler: 149 pass and 1 skipped; Product: 85 pass with no warnings; TypeScript oracle: 615 pass and 4 skipped. Human WS0 decisions: pass. Exact E4/E5 checks remain not_run and E6 approval remains not_supplied.

**Evidence level earned:** E0 overall. All executable unit suites have zero failures, but one official local-data harness case and four TypeScript filesystem-security cases are skipped; mandatory non-pass results cannot earn E1 in the combined manifest.

**Blocked on:** E3 local-data harness execution requires a working `xsltproc`; four TypeScript symlink-security cases require a non-Windows required CI job or Windows-native equivalent; E4-E6 target-runtime, offline/server, clinical, governance, security, and deployment evidence remains external.
