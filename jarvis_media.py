"""Anu assistant media and website commands for Windows.

Integration:
    from jarvis_media import handle_media_command, get_startup_greeting

    # Once at startup (after TTS/speak has been initialized):
    speak(get_startup_greeting())

    # For each recognized voice query, BEFORE jarvis_brain.think(query):
    media_reply = handle_media_command(query)
    if media_reply:
        print("Anu:", media_reply)
        speak(media_reply)
        continue

Requires: pip install yt-dlp
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from urllib.parse import quote_plus


# Common Chrome install locations on Windows.
def _chrome_executable() -> str | None:
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return shutil.which("chrome")


def _open_chrome(url: str) -> bool:
    """Open URL in Chrome when installed; otherwise use the default browser."""
    chrome = _chrome_executable()
    try:
        if chrome:
            subprocess.Popen([chrome, "--new-tab", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url, new=2)
        return True
    except Exception:
        try:
            webbrowser.open(url, new=2)
            return True
        except Exception:
            return False


def get_startup_greeting(now: datetime | None = None) -> str:
    """Return Anu's time-based startup greeting."""
    now = now or datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        greeting = "Good morning"
    elif 12 <= hour < 17:
        greeting = "Good afternoon"
    elif 17 <= hour < 21:
        greeting = "Good evening"
    else:
        greeting = "Hello"
    return f"{greeting}, Vas! I'm Anu, your AI personal assistant. How can I help you?"


def _open_spotify() -> bool:
    """Launch Spotify using its app URI; fall back to Spotify web player."""
    if os.name == "nt":
        try:
            os.startfile("spotify:")  # type: ignore[attr-defined]
            return True
        except Exception:
            pass
    return _open_chrome("https://open.spotify.com/")


def _spotify_press_play() -> bool:
    """Send the Windows media PLAY key (not toggle/pause) to the active media session."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        VK_MEDIA_PLAY = 0xFA
        KEYEVENTF_KEYUP = 0x0002
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_MEDIA_PLAY, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_PLAY, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def _launch_youtube_song(song_query: str) -> tuple[bool, str]:
    """Resolve first YouTube search result and open its watch page in Chrome."""
    query = song_query.strip()
    if not query:
        return False, "Please tell me the song name."

    # Prefer a direct watch URL, so YouTube can start playback on the video page.
    try:
        import yt_dlp  # type: ignore
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "noplaylist": True,
            "default_search": "ytsearch1",
            "socket_timeout": 8,
            "extractor_retries": 0,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info("ytsearch1:" + query, download=False)
        entries = (info or {}).get("entries") or []
        if entries:
            video = entries[0]
            video_id = video.get("id")
            url = video.get("url") or video.get("webpage_url")
            if video_id:
                url = "https://www.youtube.com/watch?v=" + video_id
            elif url and not str(url).startswith("http"):
                url = "https://www.youtube.com/watch?v=" + str(url)
            if url and _open_chrome(str(url)):
                title = video.get("title") or query
                return True, f"Opening {title} on YouTube. Playback can depend on your browser's autoplay settings."
    except Exception:
        # The fallback still performs the search if yt-dlp/network resolution fails.
        pass

    search_url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    if _open_chrome(search_url):
        return True, f"I opened YouTube search for {query}. Choose the first result to play it."
    return False, "I couldn't open YouTube. Please check Chrome and your internet connection."


def _clean_song_name(raw: str) -> str:
    raw = raw.strip(" .,!?:;\"'")
    raw = re.sub(r"^(?:the\s+)?", "", raw, flags=re.I)
    raw = re.sub(r"\s+(?:song|music|track|video)$", "", raw, flags=re.I)
    raw = re.sub(r"\s+(?:please|now)$", "", raw, flags=re.I)
    return raw.strip()


def handle_media_command(text: str) -> str | None:
    """Handle supported media/site commands; return None for other commands.

    Call this before the existing brain/actions flow. Returning None means the
    existing code (including WhatsApp automation) should handle the query.
    """
    original = (text or "").strip()
    q = re.sub(r"\s+", " ", original.lower()).strip()
    if not q:
        return None

    # Do not intercept WhatsApp, so the user's existing desktop/message automation remains in charge.
    if "whatsapp" in q:
        return None

    # Spotify app open / resume current playback.
    if re.search(r"\b(open|launch|start)\s+(?:the\s+)?spotify\b|\bspotify\s+(?:open|launch|start)\b", q):
        ok = _open_spotify()
        return "Yes boss, Vas. Opening Spotify." if ok else "Sorry Vas, I couldn't open Spotify. Check whether Spotify is installed."

    # Speech recognition sometimes splits "play song" into two utterances,
    # leaving just "song". Treat that short follow-up as a request to resume Spotify.
    bare_song_commands = {
        "song", "the song", "a song", "music", "some music", "play", "play song",
        "play the song", "play a song", "play music", "current song", "the current song",
        "play current song", "play the current song", "resume", "resume song",
        "continue song", "start song", "start music", "playback",
    }
    generic_play = bool(
        q in bare_song_commands
        or re.fullmatch(
            r"(?:please )?(?:play|resume|continue|start) (?:(?:the|a) )?(?:song|music|playback|current song|some music)(?: please)?",
            q,
        )
        or re.fullmatch(r"(?:please )?(?:resume|continue|start) spotify(?: please)?", q)
        or re.fullmatch(r"(?:please )?play on spotify(?: please)?", q)
        or re.fullmatch(r"(?:please )?play (?:a song|some music|(?:the )?current song|(?:the )?song)(?: on spotify)?(?: please)?", q)
    )
    # A song title is treated as a YouTube request unless user explicitly says Spotify.
    spotify_named = bool(re.search(r"\b(on|in)\s+spotify\b|\bspotify\b.*\b(play|search)\b", q))
    youtube_named = bool(re.search(r"\b(youtube|you tube)\b", q))

    if generic_play and not youtube_named:
        opened = _open_spotify()
        time.sleep(1.0)
        played = _spotify_press_play()
        if played:
            return "Yes boss, Vas. I sent the Play command to your media player to resume the current song in Spotify."
        if opened:
            return "Yes boss, Vas. Spotify is open. I couldn't send the Windows Play command, so press Play in Spotify to start the song."
        return "Sorry Vas, I couldn't open Spotify or send the Play command. Please check Spotify installation."

    # Explicit Spotify track search. Spotify may ask the user to select/play a result.
    if spotify_named and re.search(r"\b(play|search|find)\b", q):
        match = re.search(r"\b(?:play|search|find)\s+(.+?)(?:\s+(?:on|in)\s+spotify)?$", original, flags=re.I)
        raw_song = match.group(1).strip() if match else ""
        raw_song = re.sub(r"\s+(?:on|in)\s+spotify$", "", raw_song, flags=re.I).strip(" .,!?:;\"'")
        generic_spotify_song = re.sub(r"\s+please$", "", raw_song, flags=re.I).strip().lower()
        if generic_spotify_song in {"song", "music", "a song", "some music", "the song", "current song", "the current song", "playback", "the playback"}:
            opened = _open_spotify()
            time.sleep(1.0)
            played = _spotify_press_play()
            if played:
                return "Yes boss, Vas. I sent the Play command to resume the current song in Spotify."
            if opened:
                return "Yes boss, Vas. Spotify is open. Please press Play in Spotify to start the current song."
            return "Sorry Vas, I couldn't open Spotify. Please check whether it is installed."
        song = _clean_song_name(raw_song)
        if song:
            try:
                os.startfile("spotify:search:" + quote_plus(song))  # type: ignore[attr-defined]
                return f"Yes boss, Vas. Searching Spotify for {song}; select the track to play it."
            except Exception:
                url = "https://open.spotify.com/search/" + quote_plus(song)
                if _open_chrome(url):
                    return f"Yes boss, Vas. I opened Spotify search for {song}."
                return "Sorry Vas, I couldn't open Spotify search."

    # Named YouTube song: e.g., "play Devara song", "play Naatu Naatu on YouTube".
    is_generic_web_search = bool(re.match(r"^(?:search for|google|search)\b", q))
    if re.search(r"\b(play|search|find)\b", q) and (
        youtube_named or (not generic_play and not is_generic_web_search)
    ):
        match = re.search(r"\b(?:play|search|find)\s+(.+)$", original, flags=re.I)
        if match:
            song = match.group(1)
            song = re.sub(r"\s+(?:on|in)\s+(?:you\s*tube|youtube)$", "", song, flags=re.I)
            song = _clean_song_name(song)
            # Avoid treating generic commands as a song title.
            if song.lower() not in {"song", "music", "a song", "some music", "the song", "youtube", "you tube"}:
                ok, message = _launch_youtube_song(song)
                prefix = "Yes boss, Vas. "
                return prefix + message if ok else message

    # Opening common sites. WhatsApp is deliberately left to existing actions.
    sites = {
        "linkedin": "https://www.linkedin.com/",
        "instagram": "https://www.instagram.com/",
        "youtube": "https://www.youtube.com/",
        "google": "https://www.google.com/",
        "gmail": "https://mail.google.com/",
        "github": "https://github.com/",
        "facebook": "https://www.facebook.com/",
        "spotify": "https://open.spotify.com/",
    }
    m = re.search(r"\b(?:open|launch|visit|go to)\s+(?:the\s+)?([a-z0-9 ]+)$", q)
    if m:
        site_name = m.group(1).strip()
        site_name = re.sub(r"\s+(?:website|site|app)$", "", site_name).strip()
        if site_name in sites:
            display_names = {"linkedin": "LinkedIn", "youtube": "YouTube", "gmail": "Gmail", "github": "GitHub", "instagram": "Instagram", "facebook": "Facebook", "google": "Google", "spotify": "Spotify"}
            display_name = display_names.get(site_name, site_name.title())
            if site_name == "spotify":
                ok = _open_spotify()
            else:
                ok = _open_chrome(sites[site_name])
            return f"Yes boss, Vas. Opening {display_name}." if ok else f"Sorry Vas, I couldn't open {display_name}."

    # Web searches should use Chrome where available.
    m = re.search(r"^(?:search for|google|search)\s+(.+)$", original, flags=re.I)
    if m:
        search_terms = m.group(1).strip()
        if _open_chrome("https://www.google.com/search?q=" + quote_plus(search_terms)):
            return f"Yes boss, Vas. Searching Google for {search_terms}."
        return "Sorry Vas, I couldn't open Google search."

    return None
