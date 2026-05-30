# Measurement Commands Reference

Per-language commands for each tech debt dimension. Commands should be run in parallel when independent.

## D1: Code Quality

### TypeScript / Vue

```bash
# D1.1: Type errors
cd web/frontend && ./node_modules/.bin/vue-tsc --noEmit 2>&1 | tail -1
# Or for non-Vue TS:
cd <dir> && npx tsc --noEmit 2>&1 | tail -5

# D1.2: Lint issues (with severity breakdown)
cd web/frontend && npx eslint 'src/**/*.{ts,vue}' --format json 2>/dev/null | jq '[.[] | .messages | length] | add'
# Or summary:
cd web/frontend && npx eslint 'src/**/*.{ts,vue}' 2>&1 | tail -5

# D1.3: Type suppressions
grep -rn '@ts-ignore\|@ts-expect-error\|@ts-nocheck' web/frontend/src/ | wc -l

# D1.4: Large files (>500 lines Vue/TS)
find web/frontend/src -name '*.vue' -o -name '*.ts' | while read f; do
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 500 ]; then echo "$lines $f"; fi
done | sort -rn
```

### Python

```bash
# D1.1: Type errors
mypy src/ web/backend/app/ 2>&1 | tail -5

# D1.2: Lint issues (ruff)
ruff check src/ web/backend/app/ 2>&1
# Auto-fixable count:
ruff check src/ web/backend/app/ --fix --dry-run 2>&1 | grep -c 'would fix'

# D1.3: Type suppressions
grep -rn '# type: ignore' src/ web/backend/app/ | wc -l

# D1.4: Large files (>800 lines Python default, project configurable)
find src/ web/backend/ -name '*.py' | while read f; do
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 800 ]; then echo "$lines $f"; fi
done | sort -rn

# D1.5: Static analysis (bandit)
bandit -r src/ -f json 2>/dev/null | jq '.results | length'
```

## D2: Architecture

```bash
# D2.1: Circular dependencies (Python)
python -c "
import importlib, pkgutil, sys
# Simple import cycle detection - use pydeps for full analysis
" 2>&1
# Or use: pydeps src/ --max-bacon=3 --no-output --show-cycles

# D2.1: Circular dependencies (TypeScript)
npx madge --circular web/frontend/src/
```

## D3: Testing

### Python (pytest)

```bash
# D3.1: Skip/xfail count
grep -rn '@pytest.mark.skip\|@pytest.mark.xfail' tests/ | wc -l

# D3.2: Placeholder assertions (pass-only test bodies)
grep -rn 'pass$' tests/ | grep -v '__pycache__' | grep -v 'conftest' | wc -l

# D3.3: Coverage (if configured)
pytest --co -q 2>/dev/null | tail -1  # test count
pytest --cov=src --cov-report=term-missing 2>&1 | tail -5  # coverage
```

### TypeScript (vitest/jest)

```bash
# D3.1: Skip count
grep -rn 'test.skip\|it.skip\|describe.skip\|test.todo\|it.todo' web/frontend/src/ web/frontend/tests/ | wc -l

# D3.3: Coverage
cd web/frontend && npx vitest run --coverage 2>&1 | tail -10
```

## D4: Documentation

```bash
# D4.1: API documentation coverage (Python/FastAPI)
# Count endpoints with missing docstrings
grep -rn '@router\.\|@app\.' web/backend/app/api/ | wc -l  # total endpoints
grep -rn '"""' web/backend/app/api/ | wc -l  # documented

# D4.2: README freshness
find . -name 'README.md' -exec stat --format='%Y %n' {} \; | sort -n

# D4.3: ADR coverage
find docs/ architecture/ -name '*.md' -path '*adr*' -o -path '*decision*' | wc -l
```

## D5: Dependencies

```bash
# D5.1: Outdated dependencies (Python)
pip list --outdated 2>/dev/null | wc -l

# D5.1: Outdated dependencies (Node)
cd web/frontend && npm outdated 2>/dev/null | wc -l

# D5.2: Vulnerable dependencies (Python)
pip audit 2>/dev/null | grep -c 'vulnerability\|CVE' || echo "0"
# Or: safety check 2>/dev/null

# D5.2: Vulnerable dependencies (Node)
cd web/frontend && npm audit --json 2>/dev/null | jq '.metadata.vulnerabilities.total // 0'
```

## D6: Process & Security

```bash
# D6.1: SAST issues
bandit -r src/ -f custom 2>/dev/null | grep -c 'ISSUE' || echo "0"
# Or: ruff check src/ --select S  (security rules)

# D6.2: Secrets in code
grep -rn 'password\s*=\s*["\']' src/ web/ --include='*.py' --include='*.ts' --include='*.vue' | grep -v '.env\|config\|example\|test' | wc -l
# Or use: gitleaks detect --no-git 2>/dev/null

# D6.3: TODO/FIXME/HACK/XXX count
grep -rn 'TODO\|FIXME\|HACK\|XXX' src/ web/backend/ | wc -l
# Detailed breakdown:
grep -rn 'TODO\|FIXME\|HACK\|XXX' src/ web/backend/ | sed 's/.*\(TODO\|FIXME\|HACK\|XXX\).*/\1/' | sort | uniq -c | sort -rn
```

## Aggregation Commands

```bash
# Hot files: files with most issues (combine lint + suppressions + size)
# Example for Python:
ruff check src/ web/backend/app/ --output-format=json 2>/dev/null | \
  python3 -c "
import json, sys, collections
data = json.load(sys.stdin)
file_counts = collections.Counter(r.get('filename','') for r in data)
for f, c in file_counts.most_common(10):
    print(f'{c:>4}  {f}')
"
```
