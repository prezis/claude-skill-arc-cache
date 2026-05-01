<div align="center">

# claude-skill-arc-cache

**Multi-turn project session bootstrap for Claude Code.**
**Load curated file clusters as one user message → cache prefix → ~90% input discount on the rest of the arc.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-2.1.112%2B-orange)](https://docs.anthropic.com/en/docs/claude-code)
[![Status](https://img.shields.io/badge/status-shipped-green)](CHANGELOG.md)

</div>

---

## TL;DR

Anthropic's prompt cache gives a **90% discount** on input tokens that match a previously-cached prefix. Claude Code 2.1.112+ writes to a 1-hour TTL automatically. This skill packages that into a reusable workflow:

| What you do | What happens |
|---|---|
| Open a fresh Claude Code session | nothing yet |
| Type any natural recall phrase ("resume myproject", "remind me about the project", "where did we leave off") OR `/arc-<slug>` | hook detects intent → loads curated cluster as one user message |
| That message becomes the **cache prefix** | every subsequent turn reads it back at **10% pricing** |

**Measured results**, 35 production sessions / 2,942 assistant turns:
- **$3,286 saved (74.8%)** vs uncached counterfactual ([`examples/rollup-all-sample.txt`](examples/rollup-all-sample.txt))
- **99.9% cache hit rate**, 100% on the 1-hour tier ([same file](examples/rollup-all-sample.txt))
- Top arc session: **$725 saved on 579 turns**

Every number above is reproducible by running [`scripts/cache-rollup.sh`](scripts/cache-rollup.sh) against your own telemetry.

---

## How it works

```
┌─────────────────────────────────────────────────────────────┐
│  Fresh Claude Code session (new session_id)                 │
└─────────────────────────────────────────────────────────────┘
                         │
                         │  user: "resume myproject"
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  arc-auto-trigger.py  (UserPromptSubmit hook)               │
│  Detects: recall verb + project keyword                     │
│  Source: hooks/scripts/arc-auto-trigger.py                  │
└─────────────────────────────────────────────────────────────┘
                         │
                         │  match → slug=myproject
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  arc-bootstrap.sh myproject                                       │
│  Reads ~/.claude/state/arcs/myproject.conf, prints cluster        │
│  Binary-safe + I/O-safe + 1.5MB hard cap                    │
│  Source: hooks/scripts/arc-bootstrap.sh                     │
└─────────────────────────────────────────────────────────────┘
                         │
                         │  ~163KB / ~40k tokens cluster
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Injected as ONE user message                               │
│  Anthropic API caches prefix (1h TTL, +25% write surcharge) │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Turns 2..N: cache HIT on the prefix                        │
│  Pricing: 10% of base for the cached portion                │
│                                                             │
│  Stop hook (cache-stats-extractor.py) writes per-session    │
│  telemetry to ~/.claude/state/cache-stats.jsonl             │
│  Source: hooks/scripts/cache-stats-extractor.py             │
└─────────────────────────────────────────────────────────────┘
```

## Install

### Option A — as a Claude Code plugin

```bash
git clone https://github.com/prezis/claude-skill-arc-cache ~/.claude/plugins/local/claude-skill-arc-cache
```
Restart Claude Code. The skill, slash commands, and hooks register automatically per [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) and [`hooks/hooks.json`](hooks/hooks.json).

### Option B — as standalone scripts

```bash
git clone https://github.com/prezis/claude-skill-arc-cache
cd claude-skill-arc-cache
./install.sh
```
Copies hook scripts into `~/.claude/enforcements/` and tools into `~/.claude/state/scripts/`. Source: [`install.sh`](install.sh).

## Usage

### 1. Define your first arc

Create a config at `~/.claude/state/arcs/<your-project>.conf`:

```
# one absolute path per line; T: prefix = truncate file > 100KB
/path/to/your/project/README.md
/path/to/your/project/docs/architecture.md
/path/to/your/recent/session/notes.md
T:/path/to/your/very/large/spec.md
```

Template: [`examples/example-arc.conf`](examples/example-arc.conf).

### 2. Bootstrap an arc

Three equivalent ways to trigger:

| Method | Example | Mechanism |
|---|---|---|
| **Slash command** | `/arc-myproject` | Claude Code resolves the skill's command/markdown |
| **Natural language** | `"wracamy do myproject"`, `"remind me about myproject"`, `"what's the goal of myproject"` | UserPromptSubmit hook ([`hooks/scripts/arc-auto-trigger.py`](hooks/scripts/arc-auto-trigger.py)) |
| **Direct script** | `bash ~/.claude/state/scripts/arc-bootstrap.sh myproject` | For testing or non-Claude contexts |

Sample auto-trigger output: [`examples/auto-trigger-sample-output.json`](examples/auto-trigger-sample-output.json).

### 3. Verify caching is working

```bash
bash ~/.claude/state/scripts/cache-rollup.sh 24h
```

Expected output ([reference sample](examples/rollup-all-sample.txt)):
```
Cache rollup — last 24h
Sessions:        N
Cache health:
  hit rate:      99.9% (target: > 80%)
  1h tier share: 100% (target: > 90% in Claude Code 2.1.112+)
Cost (USD):
  saved:         $XXX.XX (XX.X%)
```

### 4. Inspect raw telemetry

`~/.claude/state/cache-stats.jsonl` accumulates one line per Stop event. Schema sample: [`examples/cache-stats-line-sample.json`](examples/cache-stats-line-sample.json).

## Trade-offs (when NOT to use)

| Scenario | Why arc isn't right |
|---|---|
| One-shot question | Session under 3 turns: cache write fee > read savings |
| Cross-project sessions | No single cluster applies |
| Pure exploration | Files-needed unknown; cache write wasted |
| Volatile codebase | Cluster goes stale after 2 turns |
| Single-file edits | Read on demand is cheaper |

## Architecture

```
claude-skill-arc-cache/
├── .claude-plugin/
│   └── plugin.json              # plugin manifest
├── skills/arc-cache/
│   ├── SKILL.md                 # skill definition + frontmatter
│   └── references/
│       └── pattern.md           # full pattern doc with math + anti-patterns
├── commands/
│   └── arc-example.md.template  # template for /arc-<slug> commands
├── hooks/
│   ├── hooks.json               # hook registration
│   └── scripts/
│       ├── arc-bootstrap.sh         # cluster loader (5.4KB)
│       ├── arc-auto-trigger.py      # UserPromptSubmit detector (10KB)
│       └── cache-stats-extractor.py # Stop hook telemetry (12.7KB)
├── scripts/
│   ├── cache-rollup.sh          # daily summary
│   └── build-arc-commands.sh    # per-project generator
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   └── test_*.py
├── examples/
│   ├── example-arc.conf
│   ├── rollup-all-sample.txt          # real telemetry output
│   ├── arc-bootstrap-demo-head.txt   # example bootstrap output (head)
│   ├── arc-bootstrap-demo-summary.txt# example bootstrap summary
│   ├── cache-stats-line-sample.json   # cache-stats.jsonl schema
│   └── auto-trigger-sample-output.json
├── install.sh
├── LICENSE
├── CHANGELOG.md
└── README.md
```

## Anti-patterns (each one busts the cache)

- **Editing `~/CLAUDE.md` mid-arc** — system-prompt change invalidates the prefix. Edit between sessions.
- **Mid-arc `/compact`** — rewrites conversation history → new prefix → another write fee.
- **Loading via repeated `Read` tool calls instead of one-shot** — fragmented prefix, no shared cache.
- **Per-prompt RAG injection that varies** — varying tokens means no cache match.

Full discussion + math: [`skills/arc-cache/references/pattern.md`](skills/arc-cache/references/pattern.md).

## Telemetry observability — what `cache-rollup.sh` reports

Each session, the Stop hook reads the transcript JSONL and computes:

| Field | Source | Where surfaced |
|---|---|---|
| `assistant_turns` | Count of `type==assistant` records with `message.usage` | rollup line 4 |
| `tokens.uncached_input` | sum of `input_tokens` | rollup tokens block |
| `tokens.cache_read` | sum of `cache_read_input_tokens` | rollup tokens block |
| `tokens.cache_write_1h` | sum of `cache_creation.ephemeral_1h_input_tokens` | rollup tokens block |
| `cost_usd.actual` | computed against Opus 4.5 pricing | rollup cost block |
| `cost_usd.saved` | uncached_baseline − actual | rollup cost block |
| `tier_breakdown.cache_hit_pct` | cache_read / (uncached + cache_read) | rollup health block |
| `tier_breakdown.1h_share_pct` | cache_write_1h / total_writes | rollup health block |

Pricing source: [Anthropic prompt-caching docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching), fetched 2026-05-01. Constants live at [`hooks/scripts/cache-stats-extractor.py`](hooks/scripts/cache-stats-extractor.py) lines `OPUS_4_5_*`.

## What this depends on

- **Claude Code 2.1.112+** — earlier versions (specifically March 2026 builds) had a regression where 1h TTL silently downgraded to 5m (issue [`anthropics/claude-code#46829`](https://github.com/anthropics/claude-code/issues/46829)). The Stop hook surfaces a `1h_share_pct` drop if the regression returns.
- **`jq`** for `cache-rollup.sh`
- **`file`** (mime-detection) for `arc-bootstrap.sh` binary guard
- **Python 3.8+** standard library only — no third-party deps
- **bash 4+**

## Honest limitations

- **Truncation gap on `T:`-prefixed files > 100KB.** Configurable; default is `head 200 + tail 100`. Mitigation: omit `T:` prefix to load files in full (we use this default — see [`examples/example-arc.conf`](examples/example-arc.conf)).
- **Cluster cap of 1.5MB** — if your arc legitimately needs more, split into sub-arcs.
- **Cache miss on first turn of every session** — the write fee is unavoidable; amortizes after ~1 turn at 1h TTL.
- **Pricing hardcoded for Opus 4.5.** Different models = different math; constants are easy to edit at the top of [`cache-stats-extractor.py`](hooks/scripts/cache-stats-extractor.py).

## References

- [Anthropic — Prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) (pricing source)
- [Anthropic — Effort](https://docs.anthropic.com/en/docs/build-with-claude/effort) (related: when to spend more compute)
- [LLMLingua](https://arxiv.org/abs/2310.05736) (academic prior on prompt compression — different approach, similar goal)

## Prior art and acknowledgements

This skill stands on others' work. We **did not fork or copy code** from any of these — we built independently and document the inspirations honestly.

- **Anthropic** — prompt caching mechanism, pricing, docs (`docs.anthropic.com`)
- **`agenticnotetaking/arscontexta`** — plugin structure conventions
- **`ouroboros/ouroboros`** — CI workflow pattern
- **`flightlesstux/prompt-caching`** (107★) — adjacent project, different audience (SDK app builders, not Claude Code users)
- **`amattn/session-kit`** — `/warmup` skill addresses related compaction-survival problem with different mechanism
- **`AerionDyseti/memory-bootstrap`** — semantic-memory bootstrap, complementary
- **Local `recall-graph-rag.py`** — session dedup pattern + bilingual aliases ported from this hook
- **LLMLingua** (arXiv 2310.05736) — academic prior on prompt compression (we considered and rejected)

Full attribution + differentiation table: [PRIOR_ART.md](PRIOR_ART.md)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome. Please match the existing code review discipline: every change should be runnable + the README claim it satisfies stays anchored to a real file/line.
