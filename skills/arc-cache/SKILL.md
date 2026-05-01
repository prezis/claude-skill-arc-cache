---
name: arc-cache
description: |
  Multi-turn project session ("arc") bootstrap for Claude Code. Loads a curated cluster of project files as ONE user message at session start so the entire cluster becomes part of Anthropic's prompt-cache prefix (1-hour TTL on Claude Code 2.1.112+) — subsequent turns read it back at 10% of base input price (~90% discount). Includes Stop-hook telemetry, daily rollup, and a UserPromptSubmit hook that auto-fires on natural-language recall ("wracamy do <project>", "remind me about <project>", "what's the goal of <project>"). Use this skill whenever the user works on a multi-day, multi-turn project ("arc") and wants to cut input costs without losing context quality, or asks how to make Claude Code remember/resume a project session, or mentions "prompt cache", "arc bootstrap", "context cache", "cache hit rate", "cache prefix", or asks why subsequent turns of a long session feel cheap. Trigger even when the user does not explicitly say "arc" — keywords like "resume project", "load my project context", "jak ja sobie pomogę z X" should still invoke this.
allowed-tools: Read, Bash, Glob, Grep
---

# arc-cache — Project arc bootstrap with prompt-cache discipline

## What this is

Anthropic's prompt cache gives you a 90% discount on input tokens that match a previously-cached prefix. Claude Code 2.1.112+ writes to a 1-hour TTL automatically. The `arc-cache` skill lets a user define **arcs** — bundles of files that matter for a specific project — and load them as one user message at session start. That single message becomes a stable cache prefix; every subsequent turn of the session reads it back at 10% of normal input price.

For a 50-turn project session on a 162k-token cluster (a real measured arc):
- Without caching: ~$406 in input charges
- With arc-cache (1-hour TTL, write once + 49 reads): ~$9
- Savings: ~98% on the cluster portion

## When to use this skill

Use whenever:
- The user starts a multi-turn, multi-day project session and you want to ground Claude in the right files cheaply.
- The user asks how to "remember", "resume", "continue", or "wracamy do" a project.
- The user mentions prompt caching, cache hit rate, context window optimization, or asks why their costs spike on long sessions.
- You see a user phrase that names a known project alongside a recall verb.

Do NOT use for:
- One-shot questions or 1–2 turn sessions (the cache write fee won't amortize).
- Cross-project sessions where no single cluster applies.
- Single-file edits or pure exploration.

## Two levels of operation

### Level 1: Slash commands (explicit user invocation)
The user types `/arc-<slug>` (e.g. `/arc-<your-slug>` (e.g. `/arc-myproject`)) and the bootstrap runs immediately. Configs live at `~/.claude/state/arcs/<slug>.conf`.

### Level 2: Natural-language trigger (UserPromptSubmit hook)
A hook in `hooks/scripts/arc-auto-trigger.py` watches the first prompt of every new session for `(recall verb) + (project keyword)`. If both match, it auto-invokes the bootstrap. The user never has to remember the slash command.

Recall verbs (PL+EN): wracamy, kontynuuj, przypomnij, gdzie skończyliśmy, jaki jest cel, remind me, what's this project, where did we leave off, pick up where, resume.

Project keywords come from arc-config slugs plus a configurable bilingual alias map (e.g. `silnik X → X`, `<polish-form> → <slug>`).

## Files in this skill

- `hooks/scripts/arc-bootstrap.sh` — reads `~/.claude/state/arcs/<slug>.conf`, prints concatenated content with truncation guards (binary-file detection, I/O-error handling, 1.5MB hard cap).
- `hooks/scripts/arc-auto-trigger.py` — UserPromptSubmit hook for natural-language triggering.
- `hooks/scripts/cache-stats-extractor.py` — Stop hook that parses the session transcript and writes per-session cache telemetry to `~/.claude/state/cache-stats.jsonl`.
- `scripts/cache-rollup.sh` — text rollup of cache stats (24h / 7d / 30d / all).
- `scripts/build-arc-commands.sh` — auto-generates per-project arc configs from `~/.claude/projects/-home-*/memory/project_*.md`.
- `commands/arc-example.md.template` — copy and rename per project.
- `references/pattern.md` — full pattern doc with math, anti-patterns, real-world numbers.

## How to use this skill in a session

If the user wants to start using arc-cache:

1. Check whether they have any `~/.claude/state/arcs/*.conf` files. If not, walk them through writing one.
2. Confirm the slash command is invokable: `/arc-<slug>`.
3. Show them the rollup: `bash scripts/cache-rollup.sh 24h` to see savings.
4. Point them at `references/pattern.md` for the deeper pattern.

If the user asks "is caching working", run the rollup and read the `cache_hit_pct` and `1h_share_pct` from `~/.claude/state/cache-stats.jsonl`. Both should be near 100% on a healthy install.

If the user reports the cluster is too big, edit their arc config to add `T:` prefixes or remove low-value files.

## Anti-patterns to flag immediately

If the user is doing any of these, point them at the relevant section of `references/pattern.md`:
- Editing `~/CLAUDE.md` mid-arc — invalidates entire cache prefix.
- Mid-arc `/compact` — rewrites cache, pay the write cost again.
- Loading project files via repeated Read tool calls — fragments the cache.
- Running with > 1.5MB cluster — exceeds the safety cap and arc-bootstrap refuses.

## What "good" looks like

A healthy arc-cache install produces telemetry like:
- Cache hit rate ≥ 95%
- 1h tier share = 100% (Claude Code 2.1.112+ default)
- Saved % ≥ 70% across multi-turn sessions
- 0 skipped lines in `cache-stats.jsonl` (skipped lines indicate transcript corruption)

If the numbers drift, check `references/pattern.md` § "About the March 2026 regression" — there's a known regression class to watch for.


## Inspirations and prior art

This skill is independent code but stands on prior conventions:

- **Plugin/skill structure**: modeled on `agenticnotetaking/arscontexta` + official `claude-plugins-official/*`.
- **CI shape**: modeled on `ouroboros/ouroboros`.
- **Session-dedup + bilingual alias pattern in `arc-auto-trigger.py`**: ported from `recall-graph-rag.py` (local hook in original author's setup).
- **Adjacent space**: `flightlesstux/prompt-caching` (SDK-direct app caching), `amattn/session-kit` `/warmup` (compaction-survival), `AerionDyseti/memory-bootstrap` (semantic-memory continuity), `thedotmack/claude-mem` (capture-then-compress). These are NOT duplicates of arc-cache — see `references/PRIOR_ART.md` (or repo root `PRIOR_ART.md`) for the differentiation table.

Use whichever fits your problem. If your need is "pre-cache curated project context for repeat sessions", arc-cache is the right tool. If your need is something else, one of the prior-art projects might fit better.
