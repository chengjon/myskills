---
name: review2md
description: Evidence-driven document review with file-type and doc-type awareness, results saved as Markdown
triggers:
  - review2md
  - review to md
  - 文档审核
  - 审核文档
---

# review2md

Evidence-driven review: scan the document, cross-reference against the live codebase, and save structured results.

## Usage

```
/review2md <file-path> [--arch|--security|--completeness|--consistency|--feasibility|--code] [--detail] [--en|--zh]
```

No flag = auto-detect file type + doc type (see below).

### Language flags

| Flag | Effect |
|------|--------|
| (none) | Match the source document's primary language |
| `--en` | Force English output |
| `--zh` | Force Chinese output |

Language matching applies to all prose in the output. Structured elements (verdict keywords, severity tags, table headers) always use English for consistency.

## Phase 1: File Type Routing

Different file extensions trigger different review strategies:

| Extension | Strategy | Core checks |
|-----------|----------|-------------|
| `.md` | Route to Phase 2 (doc type detection) | — |
| `.py`, `.ts`, `.js` | Code review | Correctness, patterns, imports, error handling, test coverage |
| `.json`, `.yaml`, `.toml` | Config review | Schema validity, key consistency, value constraints |
| `.sql` | Schema/migration review | Forward/backward compat, indexing, data integrity |

For `.md` files, proceed to Phase 2. For other file types, jump directly to Phase 4 with the appropriate strategy's checklist.

## Phase 2: Document Type Detection (`.md` only)

Detect the document type from file path keywords AND content structure. Use both signals — path provides hints, content confirms.

| Doc Type | Path signals | Content signals |
|----------|-------------|-----------------|
| **plan** | `plan`, `roadmap`, `milestone`, `sprint` | Phases, timeline, milestones, task breakdown, dependencies |
| **arch** | `arch`, `design`, `adr`, `system`, `module` | Component boundaries, data flow, interfaces, coupling analysis |
| **spec** | `spec`, `prd`, `req`, `contract`, `interface` | Acceptance criteria, contracts, input/output definitions, edge cases |
| **workflow** | `workflow`, `process`, `runbook`, `procedure` | Step sequences, triggers, guards, rollback procedures |
| **proposal** | `proposal`, `rfc`, `decision`, `review`, `audit` | Alternatives, trade-off analysis, recommendation, rationale |

Default: `general` (clarity, structure, gaps, actionability).

Always print detected file type + doc type at the top of the review output.

### Auto-Perspective Selection

When no perspective flag is provided, select perspectives based on doc type:

| Doc Type | Default perspectives | Optional add-on |
|----------|---------------------|-----------------|
| plan | completeness, feasibility | consistency |
| arch | architecture, consistency | feasibility |
| spec | completeness, consistency | architecture |
| proposal | completeness, consistency, feasibility | architecture |
| workflow | completeness, feasibility | — |
| general | completeness, consistency | — |

Multiple perspectives are run as a combined checklist. Print the selected perspectives in the progress indicator at step 2/7.

## Phase 3: Cross-Reference Evidence

Before writing any finding, verify the document's claims against the live codebase. This is what separates a professional review from a text-quality check.

### Reference level tiering

Not all references carry the same depth. Classify each reference before verifying:

| Level | Pattern | Verification method |
|-------|---------|---------------------|
| **L1**: doc → code file/function | Document names a source file or symbol directly | Glob/Grep to verify existence |
| **L2**: doc → other document | Document names or cites another document | Glob to verify the cited document exists |
| **L3**: doc → other document's claim about code | Document asserts "document X says Y about code Z" | Verify both: (a) cited document exists and contains the claim, (b) the underlying code fact is still true |

L1 and L2 references are standard. L3 references appear in meta-reviews (reviews of reviews, audits of audits) and require deeper verification — always check the underlying code fact, not just the intermediate document.

### Mandatory verification steps

1. **Referenced files** — when the document names a source file (e.g., `src/auth/handler.py`, `config/presets.json`), use Glob to verify it exists. If missing, flag as HIGH.

2. **Referenced functions/classes** — when the document names a function (e.g., `resolve_task_preset(...)`, `TASK_COMMAND_DEFAULT_PROFILES`), use Grep to search the codebase. If not found, flag as HIGH.

3. **Referenced config keys/values** — when the document describes a JSON field or config entry, read the actual file and compare. If mismatched, flag as HIGH.

4. **Cross-document claims** — when the document says "X already supports Y" or "Z was done in previous work", grep for evidence. If unverifiable, flag as MED with note.

5. **Numeric claims** — when the document states a specific count (e.g., "16 references", "3 files"), verify with Grep and note the search scope (e.g., "web/backend + scripts, excluding docs"). If the count doesn't match, flag as MED with the actual count and scope used.

### Evidence gathering optimization

Prioritize evidence gathering by finding severity:

1. **P0/blocking claims first** — verify claims that affect the document's blocking or pass/fail judgment (e.g., health endpoint URLs, file existence for deletion decisions)
2. **P1/main claims second** — verify claims that affect correction recommendations
3. **P2/minor claims last** — verify claims that are advisory or stylistic

Batch同类引用的验证：当文档引用多个同类型文件（如 9 个子文档），用一次 Glob 批量验证存在性，而非逐个调用。

### Evidence citation format

Every finding must include:

```
- [ ] **[LEVEL]** <description> — <section:line>
      Evidence: <what you checked and what you found in the codebase>
```

Example:

```
- [ ] **[MED]** `resolve_task_preset(...)` mentioned in Context but absent from Implementation Surface — Context:line 17
      Evidence: grepped for `build_preset_namespace`, found in `src/cli/commands.py:87` — function exists but doc doesn't state whether it needs changes.
```

## Phase 4: Perspective-Specific Checklist

Each perspective has a mandatory scan checklist. The reviewer MUST go through every item. If an item passes, note it briefly under "Verified". If it fails, create a finding.

### N/A handling rules

Mark a checklist item as N/A only when:

- The item explicitly requires the reviewed object to be a runnable system or code (e.g., A5 Scalability, S1 Threat model), AND the doc type is `proposal`, `review`, or `general`.
- The item's question literally cannot be answered for the document type (e.g., "Are growth points identified?" for a review document).

Otherwise, **adapt** the check to the document context. For example:
- "Performance" → "Is the document's execution flow efficient and actionable?"
- "Scalability" → "Does the document account for growth in scope or complexity?"

Always add a brief note explaining why N/A was chosen.

### Architecture (`--arch`)

| # | Check | What to verify |
|---|-------|---------------|
| A1 | Component boundaries | Are module/layer responsibilities clearly defined? |
| A2 | Data flow | Is data movement between components explicit? |
| A3 | Coupling | Are dependencies between components stated and minimal? |
| A4 | Interface contracts | Are inputs/outputs between components specified? |
| A5 | Scalability | Are growth points identified? |
| A6 | Terminology consistency | Are the same terms used consistently throughout? Do they match the codebase? |
| A7 | Backward compatibility | Does the change affect existing behavior? Is migration needed? |
| A8 | Implementation surface precision | Does the doc specify exactly what files/functions to change (not just "ensure X works")? |
| A9 | Named entities verified | Do all referenced files, functions, classes, and configs exist in the codebase? |

### Security (`--security`)

| # | Check | What to verify |
|---|-------|---------------|
| S1 | Threat model | Are potential attack vectors identified? |
| S2 | Authentication/Authorization | Are auth requirements specified? |
| S3 | Data protection | Is sensitive data handling described? |
| S4 | Input validation | Are validation rules explicit? |
| S5 | Error information leakage | Do error paths expose internals? |
| S6 | Dependency risks | Are third-party dependencies assessed? |

### Completeness (`--completeness`)

| # | Check | What to verify |
|---|-------|---------------|
| C1 | Required sections | Does the doc follow the expected structure for its type? |
| C2 | Edge cases | Are boundary conditions and error scenarios covered? |
| C3 | Implicit assumptions | Are there unstated prerequisites or constraints? |
| C4 | Acceptance criteria | Can each goal be objectively verified as done? |
| C5 | Missing roles/stakeholders | Are all affected parties identified? |

### Consistency (`--consistency`)

| # | Check | What to verify |
|---|-------|---------------|
| N1 | Terminology | Are technical terms used consistently throughout? |
| N2 | Naming conventions | Do function/file/variable names follow project conventions? |
| N3 | Formatting | Is heading hierarchy, list style, and code block usage uniform? |
| N4 | Cross-references | Do internal references (section links, file paths) resolve correctly? |
| N5 | Style consistency | Is the writing style (formal/informal) uniform? |

### Feasibility (`--feasibility`)

| # | Check | What to verify |
|---|-------|---------------|
| F1 | Technical risk | Are the hardest parts identified and addressed? |
| F2 | Dependency availability | Do referenced libraries/modules actually exist and work as described? |
| F3 | Timeline realism | Are estimates grounded in comparable past work? |
| F4 | Resource constraints | Are personnel/skill requirements realistic? |
| F5 | Rollback plan | Is there a way to revert if things go wrong? |

### Code Review (`--code`, for `.py`/`.ts`/`.js` files)

| # | Check | What to verify |
|---|-------|---------------|
| R1 | Correctness | Does the code do what it claims? |
| R2 | Error handling | Are error paths covered? Do they fail safely? |
| R3 | Security | Input validation, injection risks, secret exposure |
| R4 | Patterns | Does the code follow project conventions? Use `Grep` to compare with similar patterns nearby. |
| R5 | Performance | Are there unnecessary loops, N+1 queries, memory leaks? |
| R6 | Test coverage | Are edge cases tested? Use `Glob` to find related test files. |
| R7 | Import validity | Do all imports resolve? Use `LSP` or `Grep` to verify. |

## Progress Indicators

Print a short one-line status at each phase transition. Nothing else between steps.

```
1/7 Reading <full-input-path>
2/7 Detected: <ext> / <doc-type>, perspective: <auto-selected or flag>
3/7 Classifying references: <N> L1, <M> L2, <K> L3
4/7 Cross-referencing <N> files, <M> symbols against codebase...
5/7 Running <perspective> checklist (<N> items)...
6/7 Validating <N> potential findings against source document...
7/7 Review saved → <full-output-path>
```

Rules:

- Step 1: show the full input file path as provided by the user (e.g., `docs/specs/design.md`).
- Step 7: show the full output file path with directory (e.g., `docs/specs/design-review.md`).
- Each line under 120 characters.
- Print immediately after completing each phase.
- If nothing to verify (e.g., no symbols referenced), print count as 0.
- Do NOT print findings or analysis inline — all findings go into the output file.

## Phase 5: Finding Validation

Before writing any finding to the output, verify it against the source document itself. This prevents stale or false-positive findings where the document already addresses the concern in a different section.

### Mandatory validation steps

1. **Internal resolution check** — For each potential finding, search the source document for keywords related to the concern. If the document already addresses it (even in a different section), downgrade the finding to a suggestion or drop it entirely.

2. **Scope check** — If the finding says "X is missing" but the document explicitly states X is out of scope (Non-Goals, exclusions, "not in this batch"), drop the finding.

3. **Evidence format update** — Every finding must now cite both:
   - what you checked in the **codebase** (external verification, existing rule)
   - what you checked in the **document** and why the document's own coverage is insufficient (internal verification)

### When to downgrade or drop

- Finding says "not specified" but the specification addresses it in a later section → drop the finding.
- Finding says "missing" but the document names it as a Non-Goal or batch exclusion → drop the finding.
- Finding is valid but the document partially addresses it → downgrade severity (HIGH→MED, MED→LOW) and rephrase as "partially addressed" rather than "missing".

## Phase 6: Output

Write results to same directory as `<basename>-review.md`.

### Output language

By default, the review output matches the primary language of the source document. Determine language by checking the first 50 lines:
- If majority Chinese/CJK characters → Chinese output
- Otherwise → English output

Use `--en` or `--zh` to override.

Structured elements always use English: verdict keywords (`APPROVE`, `NEEDS_REVISION`), severity tags (`[HIGH]`, `[MED]`, `[LOW]`), check IDs (`A1`, `C3`, `F5`), and column headers in tables.

### Default: Concise Checklist

```markdown
# Review: <source-filename>

**Type**: <file-ext> / <doc-type> | **Perspective**: <auto or flag> | **Date**: <YYYY-MM-DD>

## Summary
<1-2 sentence overall assessment grounded in evidence>

## Verified
- <checklist item>: <what you checked and confirmed>
- <checklist item>: <what you checked and confirmed>

## Issues

- [ ] **[HIGH]** <issue> — <location>
      Evidence: <codebase verification result>
- [ ] **[MED]** <issue> — <location>
      Evidence: <codebase verification result>
- [ ] **[LOW]** <issue> — <location>
      Evidence: <codebase verification result>

## Suggestions

- <actionable suggestion with rationale>

## Verdict
<APPROVE / APPROVE_WITH_NOTES / NEEDS_REVISION / REJECT> — <one-line reason>
```

### `--detail`: Full Structured Template

Length constraints:
- **Hard cap**: 1000 lines
- **Soft cap**: 50% of source document line count
- Use whichever is smaller. If the template would exceed the soft cap, compress: merge small tables, omit PASS rows from Evidence Verification, collapse Checklist Results to show only FAIL/N/A rows.

```markdown
# Review: <source-filename>

**Type**: <file-ext> / <doc-type> | **Perspective**: <perspective> | **Date**: <YYYY-MM-DD> | **Reviewer**: Claude

---

## Executive Summary
<2-3 sentence overview grounded in evidence from the codebase>

## Document Metadata
| Field | Value |
|-------|-------|
| Source | <file-path> |
| File Type | <extension> |
| Doc Type | <detected type> |
| Sections | <count> |
| Referenced Files | <count> found / <count> missing |
| Referenced Symbols | <count> found / <count> missing |

## Evidence Verification

### Files Referenced
| File | Exists? | Location |
|------|---------|----------|
| <path> | yes / no | <actual path or "not found"> |

### Functions/Classes Referenced
| Symbol | Found? | Location |
|--------|--------|----------|
| <name> | yes / no | <file:line> |

### Claims Verified
| Claim | Status | Evidence |
|-------|--------|----------|
| <claim from doc> | confirmed / unverified / contradicted | <what you found> |

## Checklist Results

| # | Check | Result | Notes |
|---|-------|--------|-------|
| <id> | <name> | PASS / FAIL / N/A | <detail> |

Compress: show only FAIL and N/A rows. Summarize PASS count in one line: "<N> items PASS."

## Findings

### Critical Issues
| # | Section | Issue | Impact | Evidence | Recommendation |
|---|---------|-------|--------|----------|----------------|
| 1 | <section> | <description> | <impact> | <codebase evidence> | <fix> |

### Medium Issues
| # | Section | Issue | Impact | Evidence | Recommendation |
|---|---------|-------|--------|----------|----------------|
| 1 | <section> | <description> | <impact> | <codebase evidence> | <fix> |

### Low Issues
| # | Section | Issue | Evidence | Recommendation |
|---|---------|-------|----------|----------------|
| 1 | <section> | <description> | <codebase evidence> | <fix> |

## Strengths
- <what the document does well, with evidence>

## Recommendations
<expanded suggestions with rationale and codebase references>

## Scoring

Weights vary by doc type:

| Doc Type | Weighted dimensions (2x) |
|----------|-------------------------|
| plan | Feasibility, Actionability |
| arch | Codebase Alignment, Terminology Consistency |
| spec | Completeness, Codebase Alignment |
| proposal | Actionability, Feasibility |
| workflow | Completeness, Feasibility |
| general | (all equal weight) |

| Dimension | Score (1-5) | Evidence |
|-----------|-------------|----------|
| Technical Accuracy | | <specific examples> |
| Completeness | | <specific examples> |
| Codebase Alignment | | <specific examples> |
| Actionability | | <specific examples> |
| Terminology Consistency | | <specific examples> |
| **Overall** | **<weighted avg>** | |

## Verdict
<APPROVE / APPROVE_WITH_NOTES / NEEDS_REVISION / REJECT>

<rationale grounded in evidence>
```

## Rules

1. **Evidence is mandatory** — every finding must cite both:
   - what you checked in the **codebase** (external verification)
   - where in the **source document** you looked and why the existing text doesn't address the concern (internal verification)
   No finding without both verifications.
2. **Read the full document** before reviewing — never review based on partial content.
3. **Cross-reference before flagging** — if the doc claims a function exists, grep for it before calling it an error.
4. **Complete the full checklist** — go through every item in the relevant perspective checklist. Mark items as PASS, FAIL, or N/A with a brief note.
5. **Issues reference location** — every issue must cite the specific section, heading, or line.
6. **Severity**: HIGH (blocks approval / factual error), MED (should fix / ambiguity), LOW (nice to have / style).
7. **Suggestions must be actionable** — no "improve this section." Say what to add, change, or remove.
8. **Verdict** must be one of: `APPROVE`, `APPROVE_WITH_NOTES`, `NEEDS_REVISION`, `REJECT`.
9. **Source file must exist** — if not, report error and stop.
10. **Overwrite existing reviews** without asking.
11. **No emoji** unless user explicitly requests them.
12. **Language matching** — default to source document's primary language; override with `--en`/`--zh`.
13. **Detail mode length cap** — hard cap 1000 lines, soft cap 50% of source document line count. Compress Evidence Verification and Checklist Results tables when approaching the soft cap.
14. **Numeric claims require scope** — when verifying counts ("16 references"), always state the grep scope used. Flag mismatches as MED.
