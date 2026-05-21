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

echo "superton install: installing SuperTon"
uv tool install "$REPO_URL" --force

echo "superton install: done"
echo "run: superton init"
