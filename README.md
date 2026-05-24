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

For a user-level Codex symlink install from a local clone:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s /tmp/myskills/skills/function-tree "${CODEX_HOME:-$HOME/.codex}/skills/function-tree"
```

### function-tree quick loop

`init` creates `.governance/` and writes or refreshes root `FUNCTION_TREE.md`. Existing `FUNCTION_TREE.md` content is backed up under `.governance/backups/` before changed output is written; unmarked existing content is also preserved in the project-notes block.

```bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/function-tree"
REPO="/path/to/repo"

node "$SKILL_DIR/scripts/ft-governance.cjs" init checkout-flow --ref checkout/payment --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" install-guard --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" new-node checkout-flow C1.1 --title "Add payment confirmation" --ref checkout/payment/confirmation --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" observe checkout-flow C1.1 --evidence reports/baseline.md --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" authorize checkout-flow C1.1 --allowed src/checkout/payment/ --non-goal "No account profile changes" --commit-gate "project build passes" --closeout-gate "project test suite passes" --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" transition checkout-flow C1.1 --to approved-for-implementation --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" scope-check --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" repair --root "$REPO"
node "$SKILL_DIR/scripts/ft-governance.cjs" doc --root "$REPO"
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
