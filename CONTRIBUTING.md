# Contributing

Thanks for your interest. Two rules above all:

## 1. No hallucinated claims

Every numerical, behavioral, or architectural claim added to README.md, CHANGELOG.md, or skills/arc-cache/references/ MUST be anchored to one of:

- A specific file/line in the repo
- A test in `tests/` that asserts the property
- Captured real output in `examples/`

If you can't anchor a claim, drop the claim. The CI workflow `readme-claims` job greps the README for local-file references and fails if any are missing.

## 2. Hooks must be safe to fail

Stop hooks and UserPromptSubmit hooks fire on every session boundary / prompt. A crashing hook degrades the user experience. All exceptions must be caught and logged to `~/.claude/state/<hook-name>-errors.jsonl`. Return code 0 unless the user has explicitly asked for hard failure.

## Local development

```bash
git clone https://github.com/prezis/claude-skill-arc-cache
cd claude-skill-arc-cache
./install.sh                         # wires hooks into ~/.claude/
bash scripts/cache-rollup.sh 24h     # smoke test
```

## Run CI checks locally before pushing

```bash
shellcheck hooks/scripts/*.sh scripts/*.sh install.sh
ruff check hooks/scripts/
python3 -c "import json; json.loads(open('.claude-plugin/plugin.json').read())"
```

## Commit style

Conventional commits — `feat:`, `fix:`, `docs:`, `test:`, `ci:`. PRs squash-merge.
