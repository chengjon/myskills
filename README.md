# myskills

Personal skill collection for AI coding runtimes.

## Skills

| Skill | Description | Trigger |
|-------|-------------|---------|
| plugin-doctor | Scan, health-check, and update plugins/skills across Claude Code, Codex, and OpenCode | `/plugin-doctor` |
| review2md | Evidence-driven document review with file-type and doc-type awareness | `/review2md` |

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
