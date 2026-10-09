#!/usr/bin/env bash
#
# One-time machine setup for Ubuntu 24.04 LTS. Idempotent: safe to re-run, and
# re-running it is the supported way to pick up a toolchain bump.
#
# Root is needed for the apt step and nothing else. Everything after that
# installs into the invoking user's home directory.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }

APT_PACKAGES=(build-essential pkg-config libssl-dev sqlite3 curl git make)

# --------------------------------------------------------------- platform ----
if [[ "$(uname -s)" != "Linux" ]]; then
  warn "this script targets Ubuntu 24.04; $(uname -s) is untested"
fi

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" != "24.04" ]]; then
    warn "targeting Ubuntu 24.04; found ${VERSION_ID:-unknown}"
  fi
fi

# ------------------------------------------------------------------- apt ----
missing=()
for pkg in "${APT_PACKAGES[@]}"; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed" || missing+=("$pkg")
done

if (( ${#missing[@]} )); then
  log "installing apt packages: ${missing[*]}"
  if [[ "$(id -u)" -eq 0 ]]; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
  elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
  else
    warn "cannot install ${missing[*]}: not root and sudo is unavailable"
    warn "install them by hand, then re-run this script"
    exit 1
  fi
else
  log "apt packages already present"
fi

# ---------------------------------------------------------------- python ----
# The core pipeline is stdlib-only on purpose (see docs/adr/0006), so a working
# python3 is the whole requirement. uv manages the optional analytics extras.
PYTHON_VERSION="$(cat .python-version)"
if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 is missing even after the apt step; cannot continue"
  exit 1
fi
log "python3 $(python3 -V 2>&1 | cut -d' ' -f2) (pinned: $PYTHON_VERSION)"
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(
        f"python {sys.version.split()[0]} is too old; the pipeline needs 3.11+ "
        "for tomllib"
    )
PY

# ------------------------------------------------------------------- uv ----
if command -v uv >/dev/null 2>&1; then
  log "uv already installed ($(uv --version))"
else
  log "installing uv"
  curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# ---------------------------------------------------------------- rust ----
# The Rust crates (ob-compute and friends) land in P1. Installing the pinned
# toolchain now means the first crate to land does not also have to teach
# everyone's machine about rustup.
if command -v rustup >/dev/null 2>&1; then
  log "rustup already installed; syncing the pinned toolchain"
  rustup show active-toolchain >/dev/null 2>&1 || rustup toolchain install --profile minimal
elif [[ "${OB_SKIP_RUST:-0}" == "1" ]]; then
  log "OB_SKIP_RUST=1; skipping the Rust toolchain"
else
  log "installing rustup (pinned by rust-toolchain.toml)"
  curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path
  export PATH="$HOME/.cargo/bin:$PATH"
fi

# --------------------------------------------------------------- verify ----
log "verifying the pipeline runs"
PYTHONPATH=python python3 -m ob sources >/dev/null
PYTHONPATH=python python3 -m ob ontology >/dev/null

cat <<'EOF'

==> bootstrap complete

    make daily      hermetic daily run + determinism gate
    make daily-full the real run against live public sources
    make test       the determinism contract, as tests
    make query      point-in-time read of the ontology

If uv or rustup were installed just now, open a new shell (or source
~/.local/bin/env and ~/.cargo/env) so they are on your PATH.
EOF
