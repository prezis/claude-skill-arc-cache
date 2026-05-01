# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-01

### Added
- Initial release.
- `arc-bootstrap.sh`: cluster loader with binary-safe + I/O-safe reading, 1.5MB hard cap, opt-in `T:` truncation (head 200 + tail 100 lines for files > 100KB).
- `arc-auto-trigger.py`: UserPromptSubmit hook that fires on PL/EN recall verbs paired with project keywords; session dedup; bypass via `CLAUDE_FORCE_NO_ARC=1`.
- `cache-stats-extractor.py`: Stop hook parsing transcript JSONL → `~/.claude/state/cache-stats.jsonl` with per-session totals, cost in USD, savings vs uncached baseline, cache hit rate, 1h tier share.
- `cache-rollup.sh`: single-pass `jq` rollup with windowed views (`24h`, `7d`, `30d`, `all`).
- `build-arc-commands.sh`: scans `~/.claude/projects/-home-*/memory/project_*.md` and generates arc configs + slash commands.
- `SKILL.md` with frontmatter compliant with Claude Code skill schema.
- Example fixture and arc config template.
- CI workflow with shellcheck + python lint + manifest validation.
