# Prior Art & Acknowledgements

This skill stands on the work of others. Honest accounting of what we borrowed, what inspired us, and what we built independently.

## Foundational sources (non-negotiable credit)

### Anthropic
- **Prompt caching mechanism + pricing** — `https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching`. The 90%/200% economics, 1h TTL, `cache_control` semantics, all the JSONL `usage.cache_creation.ephemeral_*` fields are theirs.
- **Effective context engineering for AI agents** — `https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents`. Source of the prefix-stability principle this skill operationalizes.
- **Lessons from building Claude Code: Prompt caching is everything** — `https://claude.com/blog/lessons-from-building-claude-code-prompt-caching-is-everything`. Confirms the "stable system prompt + growing conversation" cache shape we exploit.
- **Compaction (`compact-2026-01-12`) + Context editing (`context-management-2025-06-27`)** — Opus 4.7 native features that complement (not replace) this pattern; their docs explicitly recommend pairing arc-style cache prefixes with their compaction.

This skill **could not exist** without any of the above.

## Plugin / repo structure conventions

We modeled our directory layout, manifest schema, hooks.json shape, and SKILL.md frontmatter on these public Claude Code plugins. **We did not copy code from any of them.** We copied the plumbing format only.

| Repo | What we modeled on it | What we did NOT take |
|---|---|---|
| `agenticnotetaking/arscontexta` | `.claude-plugin/plugin.json` rich-frontmatter shape, `hooks/hooks.json` schema, SKILL.md frontmatter conventions (`allowed-tools`, `model`, `argument-hint`) | None of the skill code, no domain logic |
| `ouroboros/ouroboros` | `.github/workflows/` CI pattern (lint + test + manifest validation) | None of the workflow code, no agent logic |
| `anthropics/skills` (official) | Reference for skill best practices | None |
| `claude-plugins-official/superpowers` | README structure, ISSUE_TEMPLATE patterns | None of the skills |
| `claude-plugins-official/code-review`, `feature-dev` | Slash command frontmatter format (`allowed-tools`, `description`, `disable-model-invocation`) | None of the commands |

## Conceptually adjacent prior art (similar goals, different approach)

These projects address parts of the same problem but with different mechanisms. **We did not fork or copy from them.** Listed for honesty.

| Project | What it does | How `arc-cache` differs |
|---|---|---|
| [flightlesstux/prompt-caching](https://github.com/flightlesstux/prompt-caching) (107★) | MCP plugin that injects `cache_control` breakpoints for developers building apps with the Anthropic SDK directly. Tools: `optimize_messages`, `get_cache_stats`. | Different audience: that one is for SDK-direct app builders. arc-cache is for Claude Code users who never touch the SDK. The flightlesstux README explicitly says: *"Claude Code already handles prompt caching automatically. This plugin doesn't help here."* — that's the gap arc-cache fills (it's about WHAT to put in the prefix, not how to mark it). |
| [amattn/session-kit](https://github.com/amattn/session-kit) | Suite of Claude Code skills. Includes `/warmup` for "Session bootstrap and compaction recovery" — Required Reading + canaries + auto-memory. | Different mechanism. session-kit's `/warmup` ensures CLAUDE.md *directives* survive compaction. arc-cache loads *project file clusters* into the cache prefix. They're complementary; you could install both. |
| [AerionDyseti/memory-bootstrap](https://github.com/AerionDyseti/memory-bootstrap) | Phase -1 hook + 9-section bootstrap template stored in semantic memory tool. | Different storage layer. memory-bootstrap uses Anthropic's memory tool with semantic search; arc-cache uses plain filesystem + curated `.conf` files. Different use case: theirs is "session continuity narrative", ours is "cache cost reduction via stable prefix". |
| [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | Captures everything Claude does, compresses it via agent-sdk, injects relevant context back. | Different direction (downstream summarization vs upstream curation). claude-mem captures-then-compresses; arc-cache picks-then-stabilizes. |
| [Trail of Bits `claude-code-config`](https://github.com/trailofbits/claude-code-config) | Hardened Claude Code config with prompt-cache hit-rate tooling. | Different scope: theirs is full Claude Code config repo. We do ONE thing: arc bootstrap + telemetry. |

If you find any of those a better fit for your use case, please use them — this is not a competitive space, it's a layered one.

## Direct inspirations from local environment

The `arc-auto-trigger.py` natural-language hook design is directly inspired by an existing hook in the original author's local Claude Code setup (`recall-graph-rag.py`) — specifically the **session dedup pattern via `(session_id, matched_set)` flock-protected sidecar JSON** is a direct port of that pattern to a different trigger surface.

The **bilingual stem aliasing** (PL↔EN trade-noun maps) was also borrowed from `recall-graph-rag.py`. `recall-graph-rag.py` is not currently public; if you'd like to see its design notes, see the comments in `hooks/scripts/arc-auto-trigger.py`.

## Academic / research priors

- **LLMLingua** (Jiang et al., EMNLP 2023, [arXiv:2310.05736](https://arxiv.org/abs/2310.05736)) — entropy-based prompt compression. arc-cache does NOT use LLMLingua; we cite it because we explicitly considered and rejected compression in favor of caching (different efficiency mechanism).
- **LLMLingua-2** (ACL 2024, [arXiv:2403.12968](https://arxiv.org/abs/2403.12968)) — task-agnostic compression follow-up.

We considered `repomix --compress` (Tree-sitter-based code compression) and decided against it: at our typical cluster size (<1MB) the cache discount dominates, and compression introduces a quality risk.

## What is original to this skill

After all the credit above, what's actually new here:

1. **The "arc" abstraction** — naming a curated cluster of files per project (in `~/.claude/state/arcs/<slug>.conf`) and giving it a slash command. Simple but hadn't been packaged this way for Claude Code users.
2. **Natural-language UserPromptSubmit triggering on a CONFIG-DRIVEN keyword set** — the auto-trigger reads the .conf basenames + a small bilingual alias map and fires only on (verb + project keyword) co-occurrence.
3. **Stop-hook telemetry that aggregates Anthropic JSONL fields into a USD savings rollup** — `cache-stats-extractor.py`. The schema, the pricing pull-through, the cache-hit math, all written from scratch from the documented API fields.
4. **Empirical validation** — 35 real sessions / 2,942 turns / measured $3,286 saved (74.8%), captured in `examples/rollup-all-sample.txt`. Not a synthetic benchmark.
5. **Anti-hallucination README** — every claim in the README points to a real file in the repo. CI grep enforces it.

If you find this list dishonestly short — please open an issue. We'd rather lose face than mislead.

## License compatibility

This skill is MIT-licensed. All projects acknowledged here are MIT or compatible (CC-BY-SA-4.0 for session-kit, which doesn't bind us since we did not copy code from it).
