# myskills

Personal skill collection for AI coding runtimes.

## Skills

| Skill | Description | Trigger |
|-------|-------------|---------|
| plugin-doctor | Scan, health-check, and update plugins/skills across Claude Code, Codex, and OpenCode | `/plugin-doctor` |
| review2md | Evidence-driven document review with file-type and doc-type awareness | `/review2md` |
| function-tree | FUNCTION_TREE evidence, authorization, scope, and active gate governance | `/ft:*` |
| myweb-audit | Page-by-page frontend audit and repair orchestration for route, render, responsive, accessibility, and ArtDeco checks | `myweb-audit` |

## Install

### Claude Code

```bash
claude install https://github.com/chengjon/myskills
```

### Codex

```bash
# Option 1: Clone into Codex skills directory
git clone https://github.com/chengjon/myskills.git ~/.codex/skills/myskills

# Option 2: Symlink individual skills
ln -s /path/to/myskills/skills/plugin-doctor ~/.codex/skills/plugin-doctor
ln -s /path/to/myskills/skills/review2md ~/.codex/skills/review2md
ln -s /path/to/myskills/skills/function-tree ~/.codex/skills/function-tree
ln -s /path/to/myskills/skills/myweb-audit ~/.codex/skills/myweb-audit
```

For a project-specific user-level install while working from `quantix-rust`, use:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s /tmp/myskills/skills/function-tree "${CODEX_HOME:-$HOME/.codex}/skills/function-tree"
```

### function-tree quick loop

```bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/function-tree"
REPO="/path/to/repo"

node "$SKILL_DIR/scripts/ft-governance.cjs" init handlers-split --ref cli/handlers --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" new-node handlers-split H3.1 --title "Split trade handlers" --ref cli/handlers/trade --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" observe handlers-split H3.1 --evidence reports/baseline.md --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" authorize handlers-split H3.1 --allowed src/cli/handlers/trade_handler.rs --non-goal "No account changes" --commit-gate "cargo check passes" --closeout-gate "cargo test passes" --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" transition handlers-split H3.1 --to approved-for-implementation --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" scope-check --root "$REPO"
```

### OpenCode

Add to `opencode.json`:

```json
{
  "plugin": [
    "myskills@git+https://github.com/chengjon/myskills.git"
  ]
}
```

## Update

```bash
# Claude Code
claude update myskills

# Codex / OpenCode
cd /path/to/myskills && git pull
```

## License

MIT
