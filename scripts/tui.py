#!/usr/bin/env python3
"""
============================================================================
 XELIS Vault — Interactive Terminal Menu (shared library)
============================================================================
Arrow-key navigation, Enter to select, no typing numbers.
Works on Linux, macOS, and Windows.
============================================================================
"""
import os
import sys

# ── ANSI Colors ─────────────────────────────────────────────────────────────
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    BG_CYAN = "\033[46m"

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def hide_cursor():
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

def show_cursor():
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()

# ── Cross-platform key reader ───────────────────────────────────────────────
def _read_key_unix():
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(2)
            if ch2 == "[A": return "UP"
            if ch2 == "[B": return "DOWN"
            if ch2 == "[C": return "RIGHT"
            if ch2 == "[D": return "LEFT"
            return "ESC"
        if ch == "\r" or ch == "\n": return "ENTER"
        if ch == "\x03": return "CTRL_C"
        if ch == "\x04": return "CTRL_D"
        if ch == "q": return "Q"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def _read_key_windows():
    import msvcrt
    ch = msvcrt.getch()
    if ch == b"\xe0" or ch == b"\x00":
        ch2 = msvcrt.getch()
        if ch2 == b"H": return "UP"
        if ch2 == b"P": return "DOWN"
        if ch2 == b"M": return "RIGHT"
        if ch2 == b"K": return "LEFT"
        return "SPECIAL"
    if ch == b"\r": return "ENTER"
    if ch == b"\x03": return "CTRL_C"
    if ch == b"q": return "Q"
    try:
        return ch.decode("ascii", errors="ignore")
    except:
        return "UNKNOWN"

def read_key():
    if os.name == "nt":
        return _read_key_windows()
    return _read_key_unix()

# ── Interactive Menu ────────────────────────────────────────────────────────
def menu(title, options, subtitle=""):
    if not options:
        return None
    normalized = []
    for opt in options:
        if isinstance(opt, tuple):
            normalized.append(opt)
        else:
            normalized.append((str(opt), opt))
    selected = 0
    total = len(normalized)
    hide_cursor()
    try:
        while True:
            clear()
            print(f"{C.CYAN}{C.BOLD}{title}{C.RESET}")
            if subtitle:
                print(f"{C.DIM}{subtitle}{C.RESET}")
            print(f"{C.GRAY}{'─' * 60}{C.RESET}")
            print()
            for i, (label, _) in enumerate(normalized):
                if i == selected:
                    print(f"  {C.BG_CYAN}{C.BOLD} > {label} {C.RESET}")
                else:
                    print(f"  {C.DIM}   {label}{C.RESET}")
            print()
            print(f"{C.GRAY}{'─' * 60}{C.RESET}")
            print(f"{C.DIM}  Up/Down Navigate   Enter Select   q Back{C.RESET}")
            key = read_key()
            if key == "UP":
                selected = (selected - 1) % total
            elif key == "DOWN":
                selected = (selected + 1) % total
            elif key == "ENTER":
                return normalized[selected][1]
            elif key in ("Q", "ESC", "CTRL_C", "CTRL_D"):
                return None
    finally:
        show_cursor()

def text_input(prompt_text, default="", password=False):
    clear()
    print(f"{C.CYAN}{C.BOLD}XELIS Vault{C.RESET}")
    print(f"{C.GRAY}{'─' * 60}{C.RESET}")
    print()
    hint = f" {C.DIM}[{default}]{C.RESET}" if default else ""
    print(f"  {C.BOLD}{prompt_text}{C.RESET}{hint}")
    print()
    try:
        if password:
            import getpass
            value = getpass.getpass(f"  {C.DIM}> {C.RESET}")
        else:
            value = input(f"  {C.CYAN}> {C.RESET}")
        return value.strip() if value.strip() else default
    except (EOFError, KeyboardInterrupt):
        return default

def confirm(prompt_text, default_yes=True):
    selected = 0 if default_yes else 1
    hide_cursor()
    try:
        while True:
            clear()
            print(f"{C.CYAN}{C.BOLD}XELIS Vault{C.RESET}")
            print(f"{C.GRAY}{'─' * 60}{C.RESET}")
            print()
            print(f"  {C.BOLD}{prompt_text}{C.RESET}")
            print()
            labels = ["Yes", "No"]
            for i, label in enumerate(labels):
                if i == selected:
                    print(f"  {C.BG_CYAN}{C.BOLD} > {label} {C.RESET}")
                else:
                    print(f"  {C.DIM}   {label}{C.RESET}")
            print()
            print(f"{C.DIM}  Left/Right Select   Enter Confirm{C.RESET}")
            key = read_key()
            if key in ("UP", "LEFT"):
                selected = (selected - 1) % 2
            elif key in ("DOWN", "RIGHT"):
                selected = (selected + 1) % 2
            elif key == "ENTER":
                return selected == 0
            elif key in ("Q", "ESC", "CTRL_C"):
                return False
    finally:
        show_cursor()

def info_box(title, lines, color=C.CYAN):
    clear()
    width = 62
    print(f"{color}{C.BOLD}+{'─' * (width - 2)}+{C.RESET}")
    print(f"{color}{C.BOLD}| {title:<{width - 4}} {C.RESET}{color}{C.BOLD}|{C.RESET}")
    print(f"{color}{C.BOLD}+{'─' * (width - 2)}+{C.RESET}")
    for line in lines:
        print(f"{color}|{C.RESET} {line:<{width - 3}} {color}|{C.RESET}")
    print(f"{color}{C.BOLD}+{'─' * (width - 2)}+{C.RESET}")
    print()
    print(f"{C.DIM}  Press Enter to continue...{C.RESET}")
    read_key()

def progress_bar(current, maximum, width=30):
    if maximum == 0:
        return f"[{'?' * width}]"
    pct = min(current / maximum, 1.0)
    filled = int(pct * width)
    color = C.GREEN if pct > 0.5 else C.YELLOW if pct > 0.25 else C.RED
    return f"[{color}{'#' * filled}{'.' * (width - filled)}{C.RESET}]"

BANNER = f"""{C.CYAN}{C.BOLD}
 ██████  ██      ██   ██ ██ ███████  ██████ ████████ ██  ██████  ███    ██
██    ██ ██      ██  ██  ██ ██      ██         ██    ██ ██    ██ ████   ██
██    ██ ██      █████   ██ █████   ██         ██    ██ ██    ██ ██ ██  ██
██    ██ ██      ██  ██  ██ ██      ██         ██    ██ ██    ██ ██  ██ ██
 ██████  ███████ ██   ██ ██ ███████  ██████    ██    ██  ██████  ██   ████
{C.RESET}{C.DIM}              Privacy-First DeFi on XELIS BlockDAG{C.RESET}"""
