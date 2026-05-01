#!/usr/bin/env bash
# arc-bootstrap.sh — load curated context for an "arc" (multi-turn project session).
#
# Reads ~/.claude/state/arcs/<slug>.conf (one path per line; `T:` prefix = truncate
# large files), prints concatenated content to stdout. Intended to be wrapped by
# /arc-<slug> slash commands so the dump becomes ONE user message — the entire
# cluster gets cached as the prefix for the rest of the arc (1h TTL on Claude
# Code 2.1.112+, 90% discount on subsequent turns).
#
# Truncation: files prefixed with `T:` and >50KB get head -200 + tail -100,
# middle elided with a marker that includes the original byte count.
#
# Hard cap: 1.5MB (~375k tokens). Refuses to dump anything past the cap.
#
# Robustness (s23 v2 review fixes):
#   - explicit if/check on head/tail/cat — silent I/O failure is corruption
#   - binary-file detection via `file --mime-type` — skip non-text to avoid
#     null-byte tokenization bugs
#   - permission-denied / race-condition between stat and cat → skipped+warn

set -uo pipefail   # no -e: bash arithmetic ((var++)) trips set -e on 0->1

slug="${1:-}"
if [[ -z "$slug" ]]; then
    echo "usage: $(basename "$0") <slug>" >&2
    exit 1
fi

conf_dir="${HOME}/.claude/state/arcs"
conf_file="${conf_dir}/${slug}.conf"

if [[ ! -f "$conf_file" ]]; then
    echo "ERROR: arc config not found: ${conf_file}" >&2
    if [[ -d "$conf_dir" ]]; then
        avail=$(find "${conf_dir}" -maxdepth 1 -name '*.conf' -exec basename {} .conf \; 2>/dev/null | tr '\n' ' ')
        echo "available arcs: ${avail:-(none)}" >&2
    else
        echo "available arcs: (none — ${conf_dir} does not exist)" >&2
    fi
    exit 2
fi

human_bytes() {
    if command -v numfmt >/dev/null 2>&1; then
        numfmt --to=iec "$1" 2>/dev/null || echo "${1}B"
    else
        echo "${1}B"
    fi
}

stat_size() {
    stat -c%s "$1" 2>/dev/null || stat -f%z "$1" 2>/dev/null || echo 0
}

is_text_file() {
    # Returns 0 if file is text-like (plain text, markdown, source, etc.).
    # Skips compiled/archive/image binaries that would corrupt LLM tokenization.
    local mime
    mime=$(file -b --mime-type "$1" 2>/dev/null || echo "unknown")
    case "$mime" in
        text/*|application/json|application/xml|application/x-yaml|application/javascript|application/x-sh|application/toml)
            return 0 ;;
        *)  return 1 ;;
    esac
}

print_summary() {
    local loaded="$1" skipped="$2" total="$3" tag="${4:-}"
    echo
    echo "## arc-bootstrap summary"
    echo "Files loaded: ${loaded} (${skipped} skipped: missing/binary/io-error)"
    echo "Total bytes:  $(human_bytes "$total") (${total}B)"
    echo "Est. tokens:  $((total / 4))  (bytes/4 heuristic)"
    echo "Cache strategy: this block = one user message → cached for 1h TTL"
    echo "                → subsequent turns at 10% pricing on the cached prefix"
    if [[ -n "$tag" ]]; then
        echo "Note: ${tag}"
    fi
    return 0  # explicit: prevents `[[ -n "" ]]` returning 1 as script exit
}

CAP_BYTES=$((1500 * 1024))     # 1.5 MB hard cap
TRUNC_THRESHOLD=$((100 * 1024)) # >100KB with T: prefix → truncate (was 50KB; bumped s23v2 — most arc files load full)

loaded=0
skipped=0
total_bytes=0

while IFS= read -r line || [[ -n "$line" ]]; do
    # skip blanks and comments
    [[ -z "${line// /}" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue

    truncate=0
    path="$line"
    if [[ "$line" =~ ^T:(.+)$ ]]; then
        truncate=1
        path="${BASH_REMATCH[1]}"
    fi

    if [[ ! -f "$path" ]]; then
        echo "## arc-bootstrap: [MISSING] ${path}"
        echo
        echo "---"
        echo
        skipped=$((skipped + 1))
        continue
    fi

    if ! is_text_file "$path"; then
        echo "## arc-bootstrap: [BINARY-SKIPPED] ${path}"
        echo
        echo "---"
        echo
        skipped=$((skipped + 1))
        continue
    fi

    if [[ ! -r "$path" ]]; then
        echo "## arc-bootstrap: [UNREADABLE] ${path}"
        echo
        echo "---"
        echo
        skipped=$((skipped + 1))
        continue
    fi

    bytes=$(stat_size "$path")

    # Hard cap check BEFORE printing content
    if (( total_bytes + bytes > CAP_BYTES )); then
        print_summary "$loaded" "$skipped" "$total_bytes" \
            "ARC TOO LARGE at ${path} — split arc or shrink ${conf_file}"
        exit 1
    fi

    echo "## arc-bootstrap: $(basename "$path") ($(human_bytes "$bytes")) — ${path}"
    echo

    # I/O failures during cat/head/tail must be surfaced — silent corruption
    # is the worst possible outcome for cache-prefix integrity.
    io_ok=1
    if (( truncate == 1 && bytes > TRUNC_THRESHOLD )); then
        head -n 200 "$path" || io_ok=0
        echo
        echo "[... ARC-BOOTSTRAP TRUNCATED — middle elided, full file at ${path} (${bytes} bytes) ...]"
        echo
        tail -n 100 "$path" || io_ok=0
    else
        cat "$path" || io_ok=0
    fi

    if (( io_ok == 0 )); then
        echo
        echo "[!! IO ERROR while reading ${path} — output above may be partial !!]"
        skipped=$((skipped + 1))
        # still count as "attempted" but don't add bytes (partial)
        echo
        echo "---"
        echo
        continue
    fi

    echo
    echo "---"
    echo

    total_bytes=$((total_bytes + bytes))
    loaded=$((loaded + 1))
done < "$conf_file"

print_summary "$loaded" "$skipped" "$total_bytes"
