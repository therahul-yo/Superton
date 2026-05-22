#!/usr/bin/env sh
set -eu

REPO_URL="git+https://github.com/therahul-yo/Superton.git"

if ! command -v python3 >/dev/null 2>&1; then
  echo "superton install: python3 is required" >&2
  exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 11)))')"
if [ "$PYTHON_OK" != "1" ]; then
  echo "superton install: Python 3.11+ is required; found Python $PYTHON_VERSION" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "superton install: installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "superton install: uv install finished, but uv is not on PATH" >&2
  echo "restart your shell or add ~/.local/bin to PATH, then rerun this installer" >&2
  exit 1
fi

# Install with the [tui] extra by default so `superton tui` works out of
# the box without a follow-up reinstall. Set SUPERTON_NO_TUI=1 to skip
# the extra (saves ~20 MB of Textual + linkify deps).
if [ "${SUPERTON_NO_TUI:-0}" = "1" ]; then
  echo "superton install: installing SuperTon (no TUI extra)"
  uv tool install "$REPO_URL" --force
else
  echo "superton install: installing SuperTon with TUI extra"
  uv tool install --with "textual>=0.60.0" "$REPO_URL" --force
fi

echo "superton install: done"
echo "run: superton init"
echo
echo "tip: 'superton'      starts the classic interactive shell"
echo "     'superton tui'   launches the full-screen Textual interface"
