"""JARVIS local actions for Windows: Chrome search, installed-app launch, WhatsApp Desktop."""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

import jarvis_market

# Sites open in Chrome unless a matching installed Start-menu shortcut exists.
SITES = {
    "youtube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "instagram": "https://www.instagram.com/",
    "linkedin": "https://www.linkedin.com/",
    "facebook": "https://www.facebook.com/",
    "twitter": "https://x.com/",
    "x": "https://x.com/",
    "spotify": "https://open.spotify.com/",
    "discord": "https://discord.com/app",
    "telegram web": "https://web.telegram.org/",
    "whatsapp web": "https://web.whatsapp.com/",
    "gmail": "https://mail.google.com/",
    "google": "https://www.google.com/",
    "github": "https://github.com/",
    "maps": "https://maps.google.com/",
    "calendar": "https://calendar.google.com/",
    "drive": "https://drive.google.com/",
    "reddit": "https://www.reddit.com/",
    "chatgpt": "https://chatgpt.com/",
}

ALIASES = {
    "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
    "chrome": "google chrome", "google chrome browser": "google chrome",
    "insta": "instagram", "linked in": "linkedin", "twitter": "x",
    "whatsapp desktop": "whatsapp", "wa": "whatsapp",
    "calc": "calculator", "explorer": "file explorer", "files": "file explorer",
}

APP_PATHS = {
    "visual studio code": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe", "code.exe",
    ],
    "google chrome": [
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "chrome.exe",
    ],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "terminal": ["wt.exe", "powershell.exe"],
    "file explorer": ["explorer.exe"],
}


def _normalize_name(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"\.(lnk|url)$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _clean_command(query: str) -> str:
    """Strip wake words and conversational fillers without touching message text."""
    q = (query or "").strip()
    q = re.sub(r"^[\s,!.?]*(?:(?:jarvis|okay|ok|hey|alright|please|can you|could you)\b[\s,!.?]*)+", "", q, flags=re.I)
    return q.strip(" \t\r\n,!.?")


def _find_chrome_executable():
    for candidate in APP_PATHS["google chrome"]:
        path = candidate if os.path.isfile(candidate) else shutil.which(candidate)
        if path and os.path.isfile(path):
            return path
    return None


def _open_url_in_chrome(url: str) -> bool:
    chrome = _find_chrome_executable()
    if not chrome:
        print("Google Chrome executable was not found; not switching to Edge/default browser.")
        return False
    try:
        subprocess.Popen([chrome, url], shell=False)
        return True
    except OSError as exc:
        print(f"Could not open Google Chrome: {exc}")
        return False


def _start_menu_roots():
    roots = []
    for base in (os.environ.get("APPDATA"), os.environ.get("PROGRAMDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if p.is_dir():
                roots.append(p)
    return roots


_START_APPS_CACHE = None


def _windows_start_apps():
    """Read apps registered with the Windows Start menu (including Store apps)."""
    global _START_APPS_CACHE
    if _START_APPS_CACHE is not None:
        return _START_APPS_CACHE
    _START_APPS_CACHE = []
    if os.name != "nt":
        return _START_APPS_CACHE
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return _START_APPS_CACHE
    try:
        command = "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = [data]
            _START_APPS_CACHE = [
                {"name": str(item.get("Name", "")).strip(), "app_id": str(item.get("AppID", "")).strip()}
                for item in data if isinstance(item, dict) and item.get("Name") and item.get("AppID")
            ]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return _START_APPS_CACHE


def _launch_windows_start_app(app_name: str) -> bool:
    """Launch a registered Start app by name, including Microsoft Store apps."""
    wanted = _normalize_name(app_name)
    apps = _windows_start_apps()
    if not wanted or not apps:
        return False
    # Exact match first. Then allow a clear starts-with / contains match.
    exact = [a for a in apps if _normalize_name(a["name"]) == wanted]
    matches = exact or [
        a for a in apps
        if _normalize_name(a["name"]).startswith(wanted) or wanted in _normalize_name(a["name"])
    ]
    if not matches:
        return False
    matches.sort(key=lambda a: (0 if _normalize_name(a["name"]) == wanted else 1,
                                abs(len(_normalize_name(a["name"])) - len(wanted)),
                                a["name"].casefold()))
    app_id = matches[0]["app_id"]
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], shell=False)
        return True
    except OSError:
        return False


def _find_start_menu_shortcut(app_name: str):
    """Find an installed Start-menu app shortcut by exact or close name."""
    target = _normalize_name(app_name)
    if not target:
        return None
    hits = []
    try:
        for root in _start_menu_roots():
            for p in root.rglob("*.lnk"):
                label = _normalize_name(p.stem)
                if label == target:
                    return p
                # Store only plausible fuzzy matches; exact match above wins.
                if label.startswith(target) or target.startswith(label) or target in label:
                    hits.append((abs(len(label) - len(target)), len(label), p))
    except (OSError, PermissionError):
        pass
    if hits:
        hits.sort(key=lambda x: (x[0], x[1], str(x[2]).lower()))
        return hits[0][2]
    return None


def _launch_shortcut(shortcut: Path) -> bool:
    try:
        if os.name == "nt":
            os.startfile(str(shortcut))  # type: ignore[attr-defined]
        else:
            subprocess.Popen([str(shortcut)])
        return True
    except (OSError, AttributeError) as exc:
        print(f"Could not launch shortcut {shortcut}: {exc}")
        return False


def _open_whatsapp_desktop() -> str:
    """Use the registered WhatsApp Desktop URI; do not open WhatsApp Web."""
    if os.name == "nt":
        try:
            os.startfile("whatsapp://")  # type: ignore[attr-defined]
            return "Opening WhatsApp Desktop."
        except OSError as exc:
            shortcut = _find_start_menu_shortcut("WhatsApp")
            if shortcut and _launch_shortcut(shortcut):
                return "Opening WhatsApp Desktop from the Start menu."
            return f"Could not open WhatsApp Desktop. Check that it is installed and registered. {exc}"
    shortcut = _find_start_menu_shortcut("WhatsApp")
    if shortcut and _launch_shortcut(shortcut):
        return "Opening WhatsApp Desktop."
    return "WhatsApp Desktop launcher is only configured for Windows."


def _open_app(name: str) -> bool:
    canonical = ALIASES.get(_normalize_name(name), _normalize_name(name))
    # Prefer the real installed app shortcut when it exists.
    shortcut = _find_start_menu_shortcut(canonical)
    if shortcut and _launch_shortcut(shortcut):
        return True
    for candidate in APP_PATHS.get(canonical, []):
        path = candidate if os.path.isfile(candidate) else shutil.which(candidate)
        if path:
            try:
                subprocess.Popen([path], shell=False)
                return True
            except OSError:
                continue
    return False


def _open_named(name: str) -> str:
    raw_name = name.strip().strip(" .,!?")
    canonical = ALIASES.get(_normalize_name(raw_name), _normalize_name(raw_name))
    # Ignore natural-language suffixes commonly heard by speech recognition.
    canonical = re.sub(r"\s+(?:app|application|website|site)$", "", canonical).strip()
    canonical = ALIASES.get(canonical, canonical)

    if canonical == "whatsapp":
        return _open_whatsapp_desktop()

    # First launch an installed app / PWA shortcut if present (LinkedIn, Instagram, etc.).
    shortcut = _find_start_menu_shortcut(canonical)
    if shortcut and _launch_shortcut(shortcut):
        return f"Opening installed {canonical.title()} app."
    # Also search Windows' registered app list, which includes many Store apps
    # that do not expose a conventional .lnk shortcut.
    if _launch_windows_start_app(canonical):
        return f"Opening installed {canonical.title()} app."

    if canonical in SITES:
        if _open_url_in_chrome(SITES[canonical]):
            return f"Opening {canonical.title()} in Google Chrome."
        return f"Could not open {canonical.title()}: Google Chrome was not found."

    if _open_app(canonical):
        return f"Opening {canonical.title()}."

    # Try exact and close Start Menu shortcuts for any other installed Windows app.
    shortcut = _find_start_menu_shortcut(raw_name)
    if shortcut and _launch_shortcut(shortcut):
        return f"Opening installed app {shortcut.stem}."
    if _launch_windows_start_app(raw_name):
        return f"Opening installed app {raw_name}."

    return (f"I couldn't find an installed app or supported website named '{raw_name}'. "
            "Try the app name as it appears in the Windows Start menu.")


def _parse_whatsapp_message_command(query: str):
    """Parse common spoken commands, returning (contact, message) or None."""
    q = query.strip().rstrip(".!?")
    patterns = (
        r"^send\s+(?:a\s+)?whatsapp\s+message\s+to\s+(.+?)\s+saying\s+(.+)$",
        r"^send\s+(?:a\s+)?whatsapp(?:\s+message)?\s+to\s+(.+?)\s*,?\s+(?:saying|message|that says|to say|with message)\s+(.+)$",
        r"^(?:send|message|text)\s+(?:a\s+)?message\s+to\s+(.+?)\s+on\s+whatsapp\s+saying\s+(.+)$",
        r"^send\s+(.+?)\s+a\s+whatsapp\s+message\s+saying\s+(.+)$",
        r"^whatsapp\s+message\s+to\s+(.+?)\s+saying\s+(.+)$",
    )
    for pattern in patterns:
        m = re.match(pattern, q, flags=re.I)
        if m:
            contact = m.group(1).strip(" ,:;.-")
            message = m.group(2).strip()
            # Speech recognizers sometimes leave quotes around the message.
            message = message.strip('"\' ')
            if contact and message:
                return contact, message
    return None


def send_whatsapp_message(contact_name: str, message: str) -> str:
    """Invoke the mouse/keyboard WhatsApp Desktop sender without interactive prompts."""
    sender_path = Path(__file__).resolve().with_name("jarvis_whatsapp_auto_send_v5.py")
    if not sender_path.is_file():
        # Backward-compatible fallback to the current v4 sender.
        sender_path = Path(__file__).resolve().with_name("jarvis_whatsapp_auto_send_v4.py")
    if not sender_path.is_file():
        return "WhatsApp sender file is missing. Keep jarvis_whatsapp_auto_send_v5.py beside jarvis_actions.py."
    try:
        completed = subprocess.run(
            [sys.executable, str(sender_path), "--contact", contact_name, "--message", message],
            cwd=str(sender_path.parent), text=True, capture_output=True, timeout=90, check=False,
        )
    except subprocess.TimeoutExpired:
        return "WhatsApp sender timed out. Check the open chat before retrying."
    except OSError as exc:
        return f"Could not start WhatsApp sender: {exc}"
    if completed.stdout.strip():
        print(completed.stdout.rstrip())
    if completed.stderr.strip():
        print(completed.stderr.rstrip())
    if completed.returncode != 0:
        return "WhatsApp automation stopped; no successful send was confirmed. Check the terminal output."
    return f"WhatsApp send workflow completed for {contact_name}. Check the chat to confirm delivery."


def _play_music(query: str) -> str:
    item = query.strip()
    item = re.sub(r"\s+(?:on|in)\s+youtube(?:\s+music)?$", "", item, flags=re.I).strip()
    item = re.sub(r"^(?:the\s+)?(?:song|music)\s+", "", item, flags=re.I).strip()
    if not item:
        item = "popular songs"
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(item)
    if _open_url_in_chrome(url):
        return f"Searching YouTube in Google Chrome for {item}."
    return "I couldn't open Google Chrome to search YouTube."


def _list_installed_apps() -> str:
    names = set()
    for root in _start_menu_roots():
        try:
            for p in root.rglob("*.lnk"):
                label = p.stem.strip()
                if label and not label.startswith(("Uninstall", "Help")):
                    names.add(label)
        except OSError:
            continue
    if not names:
        return "I couldn't read Windows Start menu shortcuts. Open the Start menu to see installed apps."
    # Include Store/UWP applications registered with Windows as well.
    for item in _windows_start_apps():
        if item.get("name"):
            names.add(item["name"])
    shown = sorted(names, key=str.casefold)[:35]
    more = len(names) - len(shown)
    result = "Start menu apps I found: " + ", ".join(shown)
    if more > 0:
        result += f". Plus {more} more."
    return result


def get_mail_brief() -> str:
    if _open_url_in_chrome("https://mail.google.com/"):
        return "Opening Gmail in Google Chrome. Automatic inbox reading is not configured yet."
    return "Could not open Gmail because Google Chrome was not found."


def try_action(q: str):
    """Run deterministic local actions before the cloud model; return None if unhandled."""
    q = _clean_command(q)
    if not q:
        return None
    q_lower = q.lower().strip(" .,!?")

    # WhatsApp message intent must be checked before generic 'open' / web intent.
    parsed = _parse_whatsapp_message_command(q)
    if parsed:
        return send_whatsapp_message(*parsed)

    # WhatsApp Desktop (not WhatsApp Web).
    if q_lower in {"whatsapp", "open whatsapp", "open up whatsapp", "launch whatsapp", "start whatsapp", "check whatsapp", "open whatsapp desktop"}:
        return _open_whatsapp_desktop()
    if q_lower in {"open whatsapp web", "whatsapp web"}:
        return _open_named("whatsapp web")

    # Play a song even when the user doesn't say 'on YouTube'.
    music_match = re.match(r"^(?:play|put on|listen to)\s+(.+)$", q, flags=re.I)
    if music_match:
        song = music_match.group(1).strip()
        # A request to open a known app is not interpreted as a song.
        if _normalize_name(song) not in {"spotify", "youtube", "youtube music"}:
            return _play_music(song)

    # Search phrases, including 'search X on YouTube'.
    match = re.match(r"^(?:search|find)\s+(.+?)\s+(?:on|in)\s+youtube(?:\s+music)?$", q, flags=re.I)
    if match:
        return _play_music(match.group(1))
    match = re.match(r"^(?:search|google)(?:\s+for)?\s+(.+)$", q, flags=re.I)
    if match:
        text = match.group(1).strip()
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(text)
        return f"Searching Google for {text}." if _open_url_in_chrome(url) else "Could not open Google Chrome."

    if q_lower in {"list apps", "list installed apps", "what apps are installed", "what apps do i have", "show installed apps"}:
        return _list_installed_apps()

    # Market actions preserved from the original project.
    if any(word in q_lower for word in ("stock", "market", "nifty", "sensex", "crypto", "bitcoin", "buy or sell")):
        for sym, name in jarvis_market.DEFAULT_TICKERS.items():
            if name.lower() in q_lower or sym.lower().replace(".ns", "") in q_lower:
                data = jarvis_market.analyze_ticker(sym)
                if data:
                    direction = "up" if data["pct_change"] >= 0 else "down"
                    return (f"{data['name']} is trading at {data['currency']}{data['price']:,}, "
                            f"{direction} {abs(data['pct_change'])}%. Technical indicator: {data['signal']}. {data['reason']}")
        return "Market overview: " + jarvis_market.market_briefing()

    if re.search(r"\btime\b", q_lower):
        return "It is currently " + datetime.datetime.now().strftime("%I:%M %p")
    if re.search(r"\bdate\b|\btoday\b", q_lower):
        return "Today is " + datetime.datetime.now().strftime("%A, %B %d, %Y")

    # Generic 'open app/site'. Strip polite, 'app', and 'website' suffixes.
    match = re.match(r"^(?:open|launch|start|go to|visit)\s+(.+?)\s*$", q, flags=re.I)
    if match:
        name = re.sub(r"\s+(?:app|application|website|site)$", "", match.group(1).strip(), flags=re.I)
        return _open_named(name)

    # A bare known site/app name.
    if q_lower in SITES or ALIASES.get(q_lower, q_lower) in SITES:
        return _open_named(q_lower)

    if any(phrase in q_lower for phrase in ("volume up", "volume down", "louder", "quieter", "mute volume")):
        return "Windows volume automation is not configured yet. Please use the keyboard volume keys or system tray."
    return None
