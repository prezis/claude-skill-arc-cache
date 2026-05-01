#!/usr/bin/env bash
# install.sh — wire arc-cache into a fresh ~/.claude/ install.
# Idempotent: re-running is safe.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${HOME}/.claude"
STATE_DIR="${CLAUDE_DIR}/state"

mkdir -p "${STATE_DIR}/scripts" "${STATE_DIR}/arcs" "${CLAUDE_DIR}/enforcements" "${CLAUDE_DIR}/commands"

# Copy hook + tool scripts (preserving exec bits)
install -m 0755 "${REPO_DIR}/hooks/scripts/arc-bootstrap.sh"        "${STATE_DIR}/scripts/"
install -m 0755 "${REPO_DIR}/hooks/scripts/cache-stats-extractor.py" "${CLAUDE_DIR}/enforcements/"
install -m 0755 "${REPO_DIR}/hooks/scripts/arc-auto-trigger.py"     "${CLAUDE_DIR}/enforcements/"
install -m 0755 "${REPO_DIR}/scripts/cache-rollup.sh"               "${STATE_DIR}/scripts/"
install -m 0755 "${REPO_DIR}/scripts/build-arc-commands.sh"         "${STATE_DIR}/scripts/"

# Optional: drop a starter arc config if user has none
if [ -z "$(ls -A "${STATE_DIR}/arcs" 2>/dev/null)" ]; then
    cp "${REPO_DIR}/examples/example-arc.conf" "${STATE_DIR}/arcs/example.conf.template"
    echo "Dropped starter at ${STATE_DIR}/arcs/example.conf.template"
fi

cat <<EOF

  arc-cache installed.

  Next steps:
    1. Create an arc config:
         cp ${STATE_DIR}/arcs/example.conf.template ${STATE_DIR}/arcs/<slug>.conf
         # then edit to add your project files
    2. Wire the hooks into ~/.claude/settings.json:
         python3 -c "import json,pathlib; p=pathlib.Path.home()/'.claude'/'settings.json'; d=json.loads(p.read_text()); h=d.setdefault('hooks',{}); us=h.setdefault('UserPromptSubmit',[]); us.append({'hooks':[{'type':'command','command':'python3 ${CLAUDE_DIR}/enforcements/arc-auto-trigger.py'}]}); st=h.setdefault('Stop',[]); st.append({'hooks':[{'type':'command','command':'python3 ${CLAUDE_DIR}/enforcements/cache-stats-extractor.py'}]}); p.write_text(json.dumps(d,indent=2)); print('hooks wired')"
    3. Run rollup any time:
         bash ${STATE_DIR}/scripts/cache-rollup.sh 24h

  Pattern doc: ${REPO_DIR}/skills/arc-cache/references/pattern.md

EOF
