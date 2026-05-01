---
name: prompt-cache-arc-pattern
description: Multi-turn project sessions ("arcs") cache the cluster prefix for ~90% input discount; ship arc-bootstrap commands per project.
type: pattern
tags: [cache, anthropic, claude-code, arc, context-engineering, cost-optimization]
topics: [_moc-context-engineering]
kind: article
mutability: stable
status: shipped_2026-05-01
---
> **Status:** 🟢 Unmeasured (pre-commit placeholder) • 2026-05-01


# Prompt Cache Arc Pattern

## Why this exists (the 80/20)

In long-running multi-turn sessions, the same project context (project files,
docs, decision log, recent journals) is implicitly re-read every turn. Without
caching, every byte of that context is billed at full input price on every
turn — `O(N × M)` where N=turns and M=context size.

The **arc pattern** front-loads a curated cluster of files into ONE user
message at session start. That message becomes part of the cache prefix.
Every subsequent turn reads the prefix at 10% of base price (90% discount).
Cost shape collapses from `O(N × M)` to `O(M) + O(N × δ)` where δ = the small
per-turn delta that actually changes.

The pattern is for **arcs**: multi-day, multi-turn project sessions where the
same cluster matters for every question. The two arcs the original author runs are the model — but you define
your own clusters per project. Connects directly to
[[patterns/context-engineering-playbook]] (overall strategy) and
[[patterns/claude-effort-discipline]] (when to spend more compute).

## How prompt caching actually bills you

Anthropic prompt caching distinguishes three input states: **uncached**,
**cache write**, and **cache read**. Pricing for Claude Opus 4.5
(verified 2026-05-01):

| Operation | Cost / MTok | × Base | Notes |
|---|---|---|---|
| Base input (uncached) | $5.00 | 1.00× | Standard non-cached input |
| Cache write — 5m TTL | $6.25 | 1.25× | Ephemeral, 5-minute lifetime |
| Cache write — 1h TTL | $10.00 | 2.00× | Ephemeral, 1-hour lifetime |
| Cache read | $0.50 | 0.10× | **90% off** vs base |
| Output | $25.00 | — | Unchanged |

Source: `https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching`

### The arc math

Cluster of 200k tokens (≈800KB of curated project files), 10-turn arc:

| Strategy | Input cost |
|---|---|
| **No caching** | 10 turns × 200k × $5/MTok = **$10.00** |
| **5m TTL arc** (write once + 9 reads) | $1.25 (write) + 9 × $0.10 (read) = **$2.15** |
| **1h TTL arc** (write once + 9 reads) | $2.00 (write) + 9 × $0.10 (read) = **$2.90** |

Savings: ~71-78% on the cluster portion. Higher in practice because
turns 11+ keep paying $0.10 each instead of $1.00 each.

The 1h tier costs more to write but survives natural pauses (lunch, meetings).
For arcs spanning more than a few minutes, 1h is almost always the right
default — and it IS the default in Claude Code 2.1.112+ (see below).

## The arc pattern

### 1. Define the cluster

For each project, curate a list of files at `~/.claude/state/arcs/<slug>.conf`.
Aim for 8–12 paths. One path per line. Optional `T:` prefix means "truncate
this if > 50KB" (head 200 + tail 100 lines, middle elided with marker).

```
# example myproject.conf
/home/user/notes/myproject/README.md
T:/home/user/notes/myproject/architecture.md
T:/home/user/notes/myproject/large-spec-doc.md
/home/user/notes/myproject/ROADMAP.md
/home/user/notes/patterns/coding-style.md
/home/user/notes/myproject/last-session-handoff.md
```

### 2. One-shot load

`arc-bootstrap.sh <slug>` reads the conf, concatenates files with headers,
prints to stdout. The slash command `/arc-<slug>` wraps this so the dump
becomes one user message. Cluster size budget: 1.5MB hard cap (≈ 375k tokens).

### 3. Sustain the arc

The first turn writes the cache (paying 2× base on the cluster). Every
subsequent turn reads at 10%. As long as gaps between turns stay under 1h,
the cache survives. Verify in transcript: `cache_creation_input_tokens` on
turn 1, `cache_read_input_tokens` on every turn after.

### 4. Verify

Stop hook `cache-stats-extractor.py` writes one rolled-up line to
`~/.claude/state/cache-stats.jsonl` per Stop event. Run
`~/.claude/state/scripts/cache-rollup.sh` for a daily summary. Or call the
MCP tool `local_cache_stats(mode="anthropic", window="24h")`.

## Tooling shipped (2026-05-01, s23)

| Component | Path | Role |
|---|---|---|
| Stop hook | `~/.claude/enforcements/cache-stats-extractor.py` | telemetry: parses transcript, computes cost + savings, writes JSONL |
| Loader | `~/.claude/state/scripts/arc-bootstrap.sh` | reads conf, dumps cluster to stdout (binary-safe, I/O-error-safe) |
| Daily summary | `~/.claude/state/scripts/cache-rollup.sh` | windowed text rollup (24h / 7d / 30d / all) |
| Generator | `~/.claude/state/scripts/build-arc-commands.sh` | scans `project_*.md` files, generates conf + slash command stubs |
| MCP surface | `local_cache_stats(mode="anthropic")` | observability via existing local-ai-mcp tool |
| Slash commands | `~/.claude/commands/arc-<slug>.md` | invoke arc-bootstrap with project slug |
| Arc configs | `~/.claude/state/arcs/<slug>.conf` | per-project file lists (manual curation) |

## Anti-patterns

### Editing CLAUDE.md mid-arc
The system prompt (which includes CLAUDE.md content) is upstream of the
cache prefix. Any edit invalidates the entire cache. Next turn pays full
write cost again. Fix: edit CLAUDE.md between sessions, not during.

### Per-prompt RAG injection that varies
Hooks like `recall-graph-rag.py` inject context based on the prompt. If
the injection content changes per turn, that block is uncached every turn.
Mitigation already in place: `recall-graph-rag.py` deduplicates by
`session_id + matched_set` so identical injections fire once per session.
See [[patterns/discovery-theater-detection]] for the methodology lineage.

### Stripping bash comments to save tokens
The marginal saving (5-10% on a script file) is dominated by the 90%
caching discount. Net effect: rounding error. Keep code readable.

### Fragmented loading via Read tool calls
Each Read is a separate turn. Cluster split across 10 Reads = 10 cache
writes, no shared prefix. Always use one user message via
`/arc-<slug>` for the cluster.

### Mid-arc `/compact`
Compaction rewrites conversation history → new prefix → cache write
again. Only compact when crossing the 800k token mid-session regrounding
threshold or when the arc is genuinely over.

### Loading wholesale without truncation
Files >50KB without `T:` prefix dump in full. A 200KB lab notebook can
swallow 50k tokens of cache budget that would be better spent on the next
file. Use `T:` aggressively for any file > 50KB.

## When not to use it

| Scenario | Why arc is wrong |
|---|---|
| One-shot question | Session under 3 turns: write cost > read savings |
| Cross-project | Cluster wouldn't apply — load nothing, ask precisely |
| Pure exploration | If you don't yet know what files matter, exploration < cache write cost |
| Volatile codebase | If the cluster files change every few turns, cache hits will be near-zero anyway |
| Single-file bug fix | Read the file when you need it; arc overhead not worth it |

## Real-world numbers

Aggregated from 6 sessions / 1,527 assistant turns via `cache-stats-extractor.py`
(2026-05-01):

| Metric | Value |
|---|---|
| Cache hit rate | 99.9% |
| 1h tier share | 100% |
| Total actual cost | $522.96 |
| If no caching (counterfactual) | $2,044.58 |
| Saved | $1,521.62 |
| Saved % | 74.4% |

The 74.4% includes write cost on the initial cluster write per session;
the steady-state read-only portion runs at the full 90% discount.

### 1h TTL is on by default

Claude Code 2.1.112 sends `cache_control: {"type":"ephemeral","ttl":"1h"}`
automatically. All 6 measured sessions show
`cache_creation.ephemeral_1h_input_tokens > 0` and
`ephemeral_5m_input_tokens == 0`. **No env var or beta header needed.**

### About the March 2026 regression

Around early March 2026, Claude Code silently dropped TTL from 1h to 5m,
inflating costs across the user base (issue
`anthropics/claude-code#46829`, dev.to and xda-developers reporting). A fix
landed in Claude Code 2.110.8 per the r/Anthropic discussion. As of
2.1.112 the regression is no longer visible in our transcripts. The
telemetry hook will surface a re-occurrence: monitor
`tier_breakdown.1h_share_pct` in the rollup; a sudden drop = regression.

## Connections

- [[patterns/claude-effort-discipline]] — when to promote to xhigh / max effort
- [[patterns/context-engineering-playbook]] — overall context strategy; arc is the tactical layer
- [[patterns/commit-discipline]] — same enforcement family (hook + state file + pattern doc)
- [[patterns/discovery-theater-detection]] — methodology rigor; this pattern was derived after refuting the "strip comments to save tokens" claim

## References

1. Anthropic — *Prompt caching*. `https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching` (fetched 2026-05-01)
2. anthropics/claude-code#46829 — *Cache TTL silently regressed from 1h to 5m around early March 2026* `https://github.com/anthropics/claude-code/issues/46829`
3. dev.to/whoffagents — *Claude's Prompt Cache TTL Silently Dropped from 1 Hour to 5 Minutes (Here's What to Do)*
4. xda-developers — *Anthropic quietly nerfed Claude Code's 1-hour cache, and your token budget is paying the price*
5. r/Anthropic — *Claude Code 2.110.8 1h prompt caching fix* (Reddit thread)
6. Internal telemetry — `~/.claude/state/cache-stats.jsonl` rolled up via `cache-rollup.sh`


## Truncation policy — Option B (chosen 2026-05-01 by user)

After shipping the initial truncation defaults (50KB threshold, head 200 + tail 100 lines), the user opted for a quality-first default: **load all files in full, no truncation**.

Rationale:
- Quality concern outweighed cost concern. User said: *"my projects are important, quality-critical, I'm afraid I'll keep fighting the system."*
- Empirical math showed even untruncated SMC arc costs ~$9/50-turn-arc — a $3-4 premium over the truncated Option A but still ~86% savings vs no-cache.
- The 1h cache TTL means the upfront write is amortized over the entire arc; per-turn cost is ~$0.13 cached vs $1.25 uncached — the cluster size barely moves the needle on per-turn economics.

Operational changes:
- `TRUNC_THRESHOLD` bumped from 50KB → 100KB (rare files >100KB still truncate when `T:` is set; otherwise full).
- `T:` became opt-in only — no implicit truncation. User must explicitly mark a file as truncatable.
- `demo.conf`: zero `T:` prefixes; cluster ~250KB / ~64k tokens.
- `myproject.conf`: zero `T:` prefixes; cluster ~650KB / ~163k tokens including all heavy docs in full.

When to revert / use Option A:
- If an arc cluster exceeds ~300k tokens after curation (eats too much of the 1M context budget for the actual conversation).
- If a single file is >500KB (consider splitting the doc rather than truncating).
