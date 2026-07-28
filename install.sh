#!/usr/bin/env bash
# ============================================================================
#  XELIS Vault — One-Line Installer
# ============================================================================
#  Install:   curl -fsSL https://xelisvault.github.io/install | bash
#  Update:    curl -fsSL https://xelisvault.github.io/install | bash
#  Uninstall: curl -fsSL https://xelisvault.github.io/install | bash -s -- --uninstall
# ============================================================================
set -euo pipefail

# ── Colors & helpers ────────────────────────────────────────────────────────
if [[ -t 1 ]] && command -v tput &>/dev/null; then
    BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
    RED=$(tput setaf 1); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3)
    BLUE=$(tput setaf 4); MAGENTA=$(tput setaf 5); CYAN=$(tput setaf 6)
    WHITE=$(tput setaf 7); GRAY=$(tput setaf 8)
else
    BOLD=""; DIM=""; RESET=""; RED=""; GREEN=""; YELLOW=""; BLUE=""
    MAGENTA=""; CYAN=""; WHITE=""; GRAY=""
fi

BANNER="${CYAN}${BOLD}"
BANNER+=" ██████  ██      ██   ██ ██ ███████  ██████ ████████ ██  ██████  ███    ██\n"
BANNER+="██    ██ ██      ██  ██  ██ ██      ██         ██    ██ ██    ██ ████   ██\n"
BANNER+="██    ██ ██      █████   ██ █████   ██         ██    ██ ██    ██ ██ ██  ██\n"
BANNER+="██    ██ ██      ██  ██  ██ ██      ██         ██    ██ ██    ██ ██  ██ ██\n"
BANNER+=" ██████  ███████ ██   ██ ██ ███████  ██████    ██    ██  ██████  ██   ████\n"
BANNER+="${RESET}\n"
BANNER+="${DIM}              Privacy-First DeFi on XELIS BlockDAG${RESET}\n"

info()    { printf "${BLUE}i${RESET}  %s\n" "$*"; }
success() { printf "${GREEN}v${RESET}  %s\n" "$*"; }
warn()    { printf "${YELLOW}!${RESET}  %s\n" "$*"; }
error()   { printf "${RED}x${RESET}  %s\n" "$*" >&2; }
step()    { printf "\n${MAGENTA}${BOLD}> %s${RESET}\n" "$*"; }
prompt()  { printf "${CYAN}?${RESET}  %s " "$*"; }

# ── Config ──────────────────────────────────────────────────────────────────
REPO="XelisVault/xelis-vault"
REPO_URL="https://github.com/${REPO}.git"
INSTALL_DIR="${HOME}/.xelis-vault"
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${INSTALL_DIR}/venv"
CONFIG_DIR="${INSTALL_DIR}/config"
LOGS_DIR="${INSTALL_DIR}/logs"
VERSION="5.1"

FORCE=0
UNINSTALL=0
INTERACTIVE=1
SKIP_DEPS=0

# ── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --uninstall)   UNINSTALL=1; shift ;;
        --force|-f)    FORCE=1; shift ;;
        --yes|-y)      INTERACTIVE=0; shift ;;
        --skip-deps)   SKIP_DEPS=1; shift ;;
        --version)     echo "xelis-vault ${VERSION}"; exit 0 ;;
        --help|-h)
            cat <<EOF
${BOLD}XELIS Vault Installer${RESET} v${VERSION}

${BOLD}Usage:${RESET}
  curl -fsSL https://xelisvault.github.io/install | bash

${BOLD}Options:${RESET}
  --uninstall   Remove XELIS Vault from this machine
  --force, -f   Reinstall even if already installed
  --yes, -y     Skip interactive prompts (CI-friendly)
  --skip-deps   Skip system dependency installation
  --version     Print version and exit
  --help, -h    Show this help

${BOLD}Examples:${RESET}
  # Standard install (interactive)
  curl -fsSL https://xelisvault.github.io/install | bash

  # Silent install for servers / CI
  curl -fsSL https://xelisvault.github.io/install | bash -s -- -y

  # Uninstall
  curl -fsSL https://xelisvault.github.io/install | bash -s -- --uninstall

${BOLD}What it does:${RESET}
  1. Checks Python 3.10+ and git
  2. Clones the repo to ~/.xelis-vault/src
  3. Creates a venv at ~/.xelis-vault/venv
  4. Installs Python dependencies (requests, python-dotenv)
  5. Generates ~/.xelis-vault/config/config.json (with testnet defaults)
  6. Creates an 'xvault' launcher in ~/.local/bin
  7. Prints next steps to start mining

${BOLD}Privacy:${RESET}
  No telemetry. No phone-home. No wallet data leaves your machine.

${BOLD}Docs:${RESET}  https://github.com/${REPO}
${BOLD}Discord:${RESET} https://discord.gg/UHpYAWbG
EOF
            exit 0
            ;;
        *) error "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Uninstall ───────────────────────────────────────────────────────────────
if [[ $UNINSTALL -eq 1 ]]; then
    printf "\n${BANNER}\n"
    step "Uninstalling XELIS Vault"
    if [[ -d "$INSTALL_DIR" ]]; then
        info "Removing ${INSTALL_DIR}"
        rm -rf "$INSTALL_DIR"
        success "Installation directory removed"
    else
        warn "XELIS Vault is not installed at ${INSTALL_DIR}"
    fi
    if [[ -L "${BIN_DIR}/xvault" ]] || [[ -f "${BIN_DIR}/xvault" ]]; then
        rm -f "${BIN_DIR}/xvault"
        success "Launcher removed from ${BIN_DIR}"
    fi
    printf "\n${GREEN}${BOLD}XELIS Vault uninstalled.${RESET}\n\n"
    exit 0
fi

# ── Banner ──────────────────────────────────────────────────────────────────
printf "\n${BANNER}\n"
printf "${DIM}  v${VERSION} - Installer${RESET}\n\n"

# ── Pre-flight checks ───────────────────────────────────────────────────────
step "Pre-flight checks"

# Check OS
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Linux*)  PLATFORM="linux";;
    Darwin*) PLATFORM="macos";;
    *)       error "Unsupported OS: $OS (only Linux and macOS)"; exit 1;;
esac
case "$ARCH" in
    x86_64|amd64) ARCH="x64";;
    arm64|aarch64) ARCH="arm64";;
    *)             error "Unsupported architecture: $ARCH"; exit 1;;
esac
success "Platform: ${PLATFORM}-${ARCH}"

# Check Python
if ! command -v python3 &>/dev/null; then
    error "Python 3 is required but not found."
    error "Install it from https://www.python.org/downloads/ or your package manager:"
    error "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    error "  macOS:         brew install python"
    exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [[ $PY_MAJOR -lt 3 ]] || ([[ $PY_MAJOR -eq 3 ]] && [[ $PY_MINOR -lt 10 ]]); then
    error "Python 3.10+ required (found ${PY_VERSION})"
    exit 1
fi
success "Python ${PY_VERSION}"

# Check git
if ! command -v git &>/dev/null; then
    error "git is required but not found."
    error "Install it via your package manager:"
    error "  Ubuntu/Debian: sudo apt install git"
    error "  macOS:         brew install git"
    exit 1
fi
success "git $(git --version | awk '{print $3}')"

# Check requests already available (optional)
if python3 -c "import requests" 2>/dev/null; then
    success "Python 'requests' module available"
fi

# ── Existing installation ───────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/src/.git" ]] && [[ $FORCE -eq 0 ]]; then
    warn "XELIS Vault is already installed at ${INSTALL_DIR}"
    if [[ $INTERACTIVE -eq 1 ]]; then
        prompt "Update existing installation? [Y/n]"
        read -r ANSWER
        ANSWER="${ANSWER:-Y}"
    else
        ANSWER="Y"
    fi
    if [[ "$ANSWER" =~ ^[Yy]$ ]]; then
        step "Updating existing installation"
        cd "$INSTALL_DIR/src"
        info "Pulling latest changes..."
        git pull --ff-only
        success "Repository updated"
    else
        info "Skipping. Use --force to reinstall."
        exit 0
    fi
else
    # ── Fresh install ──────────────────────────────────────────────────────
    step "Installing XELIS Vault"

    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    # Clone repo
    info "Cloning ${REPO}..."
    if [[ -d "src" ]]; then
        rm -rf src
    fi
    git clone --depth 1 "$REPO_URL" src 2>&1 | sed 's/^/    /'
    success "Repository cloned to ${INSTALL_DIR}/src"

    # Create directories
    mkdir -p "$CONFIG_DIR" "$LOGS_DIR" "${INSTALL_DIR}/wallet"
    success "Directories created"
fi

cd "$INSTALL_DIR/src"

# ── Virtualenv ──────────────────────────────────────────────────────────────
step "Setting up Python environment"

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtualenv at ${VENV_DIR}"
    python3 -m venv "$VENV_DIR"
    success "Virtualenv created"
else
    info "Virtualenv already exists"
fi

# Install deps
info "Installing Python dependencies..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet requests python-dotenv
success "Dependencies installed"
deactivate 2>/dev/null || true

# ── Config file ─────────────────────────────────────────────────────────────
step "Generating configuration"

CONFIG_FILE="${CONFIG_DIR}/config.json"
if [[ ! -f "$CONFIG_FILE" ]] || [[ $FORCE -eq 1 ]]; then
    cat > "$CONFIG_FILE" <<'JSON'
{
  "version": "5.1",
  "network": "testnet",
  "rpc_url": "http://127.0.0.1:18081",
  "wallet_url": "http://127.0.0.1:18082",
  "wallet_user": "wallet",
  "wallet_pass": "testpass",
  "miner_endpoint": "",
  "miner_address": "",
  "enable_oracle": true,
  "enable_miner": true,
  "heartbeat_interval": 100,
  "price_update_interval": 100,
  "log_level": "INFO",
  "contracts": {
    "price_oracle": "764ad585c2f484e54ea9dd06a7fb8b81397ba2487d37298f27edce3747d836dd",
    "miner": "21ed1297c7ed4001a4a7c9a4bb89b10da0b0f3ad0312545a5af4a761200af207",
    "vlt_token": "7275c55d711789b1b746cd4695b04c0e393a0db74ecf72360c5544b73368cfab",
    "vlt_asset": "2de72ed3ea2d8ff30e6df57ba3a4d993dedfa8636d207d43d09e33615bfde2c6"
  }
}
JSON
    success "Config written to ${CONFIG_FILE}"
else
    info "Config already exists at ${CONFIG_FILE} (use --force to overwrite)"
fi

# ── Launcher ────────────────────────────────────────────────────────────────
step "Installing launcher"

mkdir -p "$BIN_DIR"
cat > "${BIN_DIR}/xvault" <<EOF
#!/usr/bin/env bash
# XELIS Vault launcher - auto-generated by install.sh
VAULT_DIR="${INSTALL_DIR}"
VENV="\${VAULT_DIR}/venv/bin/python"
SCRIPT="\${VAULT_DIR}/src/scripts/xelis_vault_miner.py"
exec "\${VENV}" "\${SCRIPT}" "\$@"
EOF
chmod +x "${BIN_DIR}/xvault"
success "Launcher installed: ${BIN_DIR}/xvault"

# PATH warning
if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    warn "${BIN_DIR} is not in your PATH"
    info "Add it to your shell profile:"
    SHELL_NAME=$(basename "$SHELL")
    case "$SHELL_NAME" in
        bash) info "  echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.bashrc" ;;
        zsh)  info "  echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.zshrc" ;;
        fish) info "  fish_add_path ${BIN_DIR}" ;;
        *)    info "  export PATH=\"${BIN_DIR}:\$PATH\"" ;;
    esac
fi

# ── Done ────────────────────────────────────────────────────────────────────
printf "\n"
printf "${GREEN}${BOLD}================================================================${RESET}\n"
printf "${GREEN}${BOLD}                                                                ${RESET}\n"
printf "${GREEN}${BOLD}   XELIS Vault installed successfully!                          ${RESET}\n"
printf "${GREEN}${BOLD}                                                                ${RESET}\n"
printf "${GREEN}${BOLD}================================================================${RESET}\n"
printf "\n"

printf "${BOLD}Next steps:${RESET}\n\n"

printf "  ${CYAN}1.${RESET} ${BOLD}Start mining${RESET} (one-liner):\n"
printf "     ${DIM}\$${RESET} xvault --miner\n\n"

printf "  ${CYAN}2.${RESET} ${BOLD}Start with custom endpoint${RESET}:\n"
printf "     ${DIM}\$${RESET} xvault --rpc http://127.0.0.1:18081 \\\\\n"
printf "            --wallet-url http://127.0.0.1:18082 \\\\\n"
printf "            --endpoint https://my-miner.example.com:8080 \\\\\n"
printf "            --miner\n\n"

printf "  ${CYAN}3.${RESET} ${BOLD}Interactive mode${RESET} (guided setup):\n"
printf "     ${DIM}\$${RESET} xvault -i\n\n"

printf "  ${CYAN}4.${RESET} ${BOLD}View help${RESET}:\n"
printf "     ${DIM}\$${RESET} xvault --help\n\n"

printf "${DIM}Config:${RESET}  ${CONFIG_FILE}\n"
printf "${DIM}Logs:${RESET}    ${LOGS_DIR}/miner.log\n"
printf "${DIM}Source:${RESET}  ${INSTALL_DIR}/src\n"
printf "${DIM}Docs:${RESET}    https://github.com/${REPO}\n"
printf "${DIM}Discord:${RESET} https://discord.gg/UHpYAWbG\n"
printf "\n"
printf "${MAGENTA}Happy mining!${RESET}\n\n"
