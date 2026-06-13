#!/usr/bin/env bash
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
echo ""
echo " ================================================="
echo "  PSX Advisory Agent v3 — Linux/macOS Launcher"
echo "  Local AI Council + Memory Edition"
echo " ================================================="
echo ""

PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "${MAJOR:-0}" -ge 3 ] && [ "${MINOR:-0}" -ge 10 ]; then
            PYTHON="$cmd"; break
        fi
    fi
done
[ -z "$PYTHON" ] && echo "ERROR: Python 3.10+ not found." && exit 1
echo " [1/5] Python: $($PYTHON --version)"

mkdir -p data/cache
echo " [2/5] Directories ready"

[ ! -f ".env" ] && cp .env.example .env && echo " [NOTE] .env created. Run: nano .env to add keys"
echo " [3/5] Config ready"

echo " [4/5] Installing dependencies..."
$PYTHON -m pip install -r requirements.txt -q --disable-pip-version-check
echo " [4/5] Dependencies OK"

echo " [5/5] Launching..."
echo ""
echo " App: http://localhost:8501  |  Ctrl+C to stop"
echo ""
$PYTHON -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
