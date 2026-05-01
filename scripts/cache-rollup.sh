#!/usr/bin/env bash
# cache-rollup.sh — summarize ~/.claude/state/cache-stats.jsonl
#
# Usage: cache-rollup.sh [WINDOW]
#   WINDOW: 24h (default), 7d, 30d, all, Nh, Nd
#
# Reads JSONL written by cache-stats-extractor.py (Stop hook).
# Aggregates: tokens, cost, savings, hit-rate, 1h-tier share, top sessions.
# Recomputes health metrics from totals (not averaged across sessions).

set -euo pipefail

INPUT_FILE="${HOME}/.claude/state/cache-stats.jsonl"
WINDOW="${1:-24h}"

# Parse window -> cutoff timestamp
case "$WINDOW" in
    all)        cutoff=0; label="all time" ;;
    *d)         secs=$(( ${WINDOW%d} * 86400 )); cutoff=$(( $(date +%s) - secs )); label="last $WINDOW" ;;
    *h)         secs=$(( ${WINDOW%h} * 3600 ));  cutoff=$(( $(date +%s) - secs )); label="last $WINDOW" ;;
    *)          echo "usage: $(basename "$0") [Nh|Nd|all]" >&2; exit 2 ;;
esac

if [[ ! -s "$INPUT_FILE" ]]; then
    echo "no data yet — needs at least one Stop event"
    echo "(input: $INPUT_FILE)"
    exit 0
fi

# Single jq pass: filter, aggregate, format. Recompute health from totals.
jq -rs --argjson cutoff "$cutoff" --arg label "$label" '
    map(select(.ts >= $cutoff)) as $all
    | ($all | map(select(.replay != true))) as $rows
    | ($rows | map(select(.warning == null))) as $valid
    | ($rows | map(select(.warning != null))) as $warns
    | ($all | map(select(.replay == true)) | length) as $replay_count
    | ($valid | map(.tokens.uncached_input) | add // 0) as $uncached
    | ($valid | map(.tokens.cache_read)     | add // 0) as $cread
    | ($valid | map(.tokens.cache_write_5m) | add // 0) as $w5m
    | ($valid | map(.tokens.cache_write_1h) | add // 0) as $w1h
    | ($valid | map(.tokens.output)         | add // 0) as $out
    | ($valid | map(.cost_usd.actual)            | add // 0) as $c_actual
    | ($valid | map(.cost_usd.uncached_baseline) | add // 0) as $c_base
    | ($valid | map(.cost_usd.saved)             | add // 0) as $c_saved
    | ($valid | map(.assistant_turns)            | add // 0) as $turns
    | ($valid | map(.skipped_lines)              | add // 0) as $skipped
    | ($valid | map(select(.skipped_lines > 0)) | length) as $skipped_sess
    | ($cread + $uncached) as $input_total
    | (if $input_total > 0 then ($cread / $input_total * 100) else 0 end) as $hit_rate
    | ($w1h + $w5m) as $write_total
    | (if $write_total > 0 then ($w1h / $write_total * 100) else 0 end) as $tier_1h
    | (if $c_base > 0 then ($c_saved / $c_base * 100) else 0 end) as $saved_pct
    | (
        "Cache rollup — \($label)",
        "----------------------------------------",
        "Sessions:        \($rows | length) (\($warns | length) with warnings, \($replay_count) replays excluded)",
        "Assistant turns: \($turns)",
        "Skipped lines:   \($skipped) across \($skipped_sess) sessions (any > 0 means look at it)",
        "",
        "Tokens (M = millions):",
        "  uncached:     \($uncached / 1000000 * 100 | floor / 100) M",
        "  cache read:   \($cread / 1000000 * 100 | floor / 100) M",
        "  cache write:  \(($w1h + $w5m) / 1000000 * 100 | floor / 100) M (1h: \($w1h / 1000000 * 100 | floor / 100) M / 5m: \($w5m / 1000000 * 100 | floor / 100) M)",
        "  output:       \($out / 1000000 * 100 | floor / 100) M",
        "",
        "Cost (USD):",
        "  actual:        $\($c_actual * 100 | floor / 100)",
        "  if no caching: $\($c_base * 100 | floor / 100)",
        "  saved:         $\($c_saved * 100 | floor / 100) (\($saved_pct * 10 | floor / 10)%)",
        "",
        "Cache health:",
        "  hit rate:      \($hit_rate * 10 | floor / 10)% (target: > 80%)",
        "  1h tier share: \($tier_1h * 10 | floor / 10)% (target: > 90% in Claude Code 2.1.112+)",
        "",
        "Top 5 sessions by saved $:",
        ($valid | sort_by(-(.cost_usd.saved // 0)) | .[0:5][] |
            "  \(.session_id[0:8])  saved=$\(.cost_usd.saved * 100 | floor / 100)  turns=\(.assistant_turns)  hit=\(.tier_breakdown.cache_hit_pct)%  1h=\(.tier_breakdown["1h_share_pct"])%")
    )
' "$INPUT_FILE"
