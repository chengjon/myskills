# quantix-rust Profile

Use this profile when the repository root is `quantix-rust` or the user explicitly says the work is for `/opt/claude/quantix-rust`.

## Mandatory Local Rules

- Use context-mode MCP tools for exploration, large output, and file analysis.
- Attempt Graphiti reads before design, review handling, debugging, handoff, or documentation terminology work.
- Write compact Graphiti conclusions after design, review, debug, handoff, or documentation decisions, and verify ingest.
- Never treat Graphiti as code truth or task status truth.
- Never treat GitHub issue or PR state as the governance source of truth.

## GitNexus Gates

GitNexus is not optional in this repo when code symbols or commits are involved.

- Before editing a function, class, method, or other indexed symbol, run upstream impact analysis for the symbol.
- If impact returns HIGH or CRITICAL, warn the user before editing.
- Before committing, run detect_changes and confirm the affected symbols and flows match the governance authorization.
- For refactors and renames, use GitNexus context/impact/rename flow instead of text replacement.

## FUNCTION_TREE Relationship

- `docs/FUNCTION_TREE.md` remains the capability registry and status truth.
- The governance layer lives under `.governance/` and records process state.
- Closeout may propose or apply FUNCTION_TREE updates, but implementation gates must not silently rewrite capability status.

## Closure Stage

Once implementation is done and remaining work is validation, prioritize gate closure over cleanup. Do not expand scope into cosmetic changes unless a failing gate requires it.
