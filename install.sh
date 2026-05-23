#!/usr/bin/env sh
set -eu

REPO_URL="git+https://github.com/therahul-yo/Superton.git"
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "superton install: unknown option: $arg" >&2
      echo "usage: install.sh [--dry-run]" >&2
      exit 2
      ;;
  esac
done

ORANGE="$(printf '\033[38;2;255;176;46m')"
YELLOW="$(printf '\033[38;2;255;217;61m')"
RED="$(printf '\033[38;2;240;71;31m')"
MUTED="$(printf '\033[2m')"
RESET="$(printf '\033[0m')"

info() { printf '%s→%s %s\n' "$ORANGE" "$RESET" "$1"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
fail() { printf '%s✗%s %s\n' "$RED" "$RESET" "$1" >&2; }

need_uv="no"
if ! command -v uv >/dev/null 2>&1; then
  need_uv="yes"
fi

with_tui="yes"
if [ "${SUPERTON_NO_TUI:-0}" = "1" ]; then
  with_tui="no"
fi

existing="none"
if command -v superton >/dev/null 2>&1; then
  existing="$(superton --version 2>/dev/null || printf 'installed')"
fi

info "SuperTon installer preflight"
printf '  %swill install uv:%s %s\n' "$MUTED" "$RESET" "$need_uv"
printf '  %swill install TUI extra:%s %s\n' "$MUTED" "$RESET" "$with_tui"
printf '  %sexisting SuperTon:%s %s\n' "$MUTED" "$RESET" "$existing"

if [ "$DRY_RUN" = "1" ]; then
  info "dry run complete; no changes made"
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required"
  exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 11)))')"
if [ "$PYTHON_OK" != "1" ]; then
  fail "Python 3.11+ is required; found Python $PYTHON_VERSION"
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  info "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  fail "uv install finished, but uv is not on PATH"
  warn "restart your shell or add ~/.local/bin to PATH, then rerun this installer"
  exit 1
fi

# Install with the [tui] extra by default so `superton tui` works out of
# the box without a follow-up reinstall. Set SUPERTON_NO_TUI=1 to skip
# the extra (saves ~20 MB of Textual + linkify deps).
if [ "${SUPERTON_NO_TUI:-0}" = "1" ]; then
  info "installing SuperTon (no TUI extra)"
  uv tool install "$REPO_URL" --force
else
  info "installing SuperTon with TUI extra"
  uv tool install --with "textual>=0.60.0" "$REPO_URL" --force
fi

info "done"
printf 'run: superton init\n'
echo
printf 'tip: %ssuperton%s      starts the classic interactive shell\n' "$ORANGE" "$RESET"
printf '     %ssuperton tui%s  launches the full-screen Textual interface\n' "$ORANGE" "$RESET"
