"""jarvis_voice.py - Anu voice assistant with time-based startup greeting."""

import datetime
import re
import subprocess
import sys
import shutil
import time

import speech_recognition as sr
import jarvis_brain
from jarvis_media import handle_media_command

ASSISTANT_NAME = "Anu"
USER_NAME = "Vas"


def get_time_greeting(now=None):
    """Return a greeting based on the computer's local time."""
    hour = (now or datetime.datetime.now()).hour
    if 5 <= hour < 12:
        greeting = "Good morning"
    elif 12 <= hour < 17:
        greeting = "Good afternoon"
    elif 17 <= hour < 21:
        greeting = "Good evening"
    else:
        greeting = "Good night"
    return f"{greeting}, {USER_NAME}! I love you. I'm Anu, your AI personal assistant. How can I help you?"


def _make_tts_engine():
    """Initialize TTS and prefer an installed English female-sounding voice."""
    try:
        import pyttsx3
    except ImportError:
        print("[Voice notice] pyttsx3 is not installed; replies will be text-only.")
        return None

    try:
        # Windows normally uses SAPI5; elsewhere use the default driver.
        engine = pyttsx3.init(driverName="sapi5") if sys.platform == "win32" else pyttsx3.init()
        voices = engine.getProperty("voices") or []
        preferred_names = (
            "zira", "heera", "aria", "jenny", "hazel", "susan",
            "samantha", "eva", "female", "sonia", "natasha",
        )

        def voice_text(voice):
            bits = [getattr(voice, "name", ""), getattr(voice, "id", "")]
            langs = getattr(voice, "languages", []) or []
            bits.extend(str(x) for x in langs)
            return " ".join(bits).lower()

        selected = None
        for preferred in preferred_names:
            selected = next((v for v in voices if preferred in voice_text(v)), None)
            if selected:
                break

        # Prefer an English voice if no recognised female name was found.
        if selected is None:
            selected = next(
                (v for v in voices if any(tag in voice_text(v) for tag in ("en-us", "en-gb", "en-in", "english", "en_"))),
                voices[0] if voices else None,
            )

        if selected is not None:
            engine.setProperty("voice", selected.id)
            print(f"[Voice] Selected installed voice: {getattr(selected, 'name', selected.id)}")
            if not any(tag in voice_text(selected) for tag in preferred_names):
                print("[Voice notice] A known female voice was not detected. Add an English female voice in Windows Settings > Time & language > Speech for a female voice.")
        else:
            print("[Voice notice] No system speech voices were found; using the system default if available.")

        engine.setProperty("rate", 175)
        engine.setProperty("volume", 1.0)
        return engine
    except Exception as exc:
        print(f"[Voice notice] Text-to-speech initialization failed: {exc}")
        return None


_TTS_ENGINE = _make_tts_engine()


def speak(text):
    """Print and speak every response; use Windows System.Speech first on Windows."""
    if not text:
        return
    print(f"\n[{ASSISTANT_NAME.upper()}]: {text}\n")

    # macOS native speech path.
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["say", "-v", "Samantha", text], check=False, timeout=30)
            if result.returncode == 0:
                return
            print("[Voice notice] macOS 'say' returned a non-zero exit code; trying pyttsx3.")
        except Exception as exc:
            print(f"[Voice notice] macOS speech playback failed: {exc}")

    # On Windows, prefer System.Speech as the primary audible path. This avoids
    # treating a silent-but-nonthrowing pyttsx3/SAPI run as successful speech.
    if sys.platform == "win32":
        try:
            import base64
            encoded_text = base64.b64encode(text.encode("utf-16le")).decode("ascii")
            ps_command = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$textBytes = [System.Convert]::FromBase64String('ENCODED_TEXT')
$text = [System.Text.Encoding]::Unicode.GetString($textBytes)
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $speaker.Volume = 100
    $speaker.Rate = 0
    $voices = @($speaker.GetInstalledVoices() | Where-Object { $_.Enabled })
    $preferred = $voices | Where-Object { $_.VoiceInfo.Name -match '(?i)Zira|Heera|Aria|Jenny|Hazel|Samantha|Eva|Sonia|Natasha' } | Select-Object -First 1
    if ($preferred) { $speaker.SelectVoice($preferred.VoiceInfo.Name) }
    $speaker.Speak($text)
} finally {
    $speaker.Dispose()
}
""".replace('ENCODED_TEXT', encoded_text)
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if not powershell:
                raise FileNotFoundError("Windows PowerShell was not found")
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
            if result.returncode == 0:
                return
            error = (result.stderr or result.stdout or "Unknown PowerShell speech error").strip()
            print(f"[Voice notice] Windows System.Speech failed: {error}")
        except Exception as exc:
            print(f"[Voice notice] Windows System.Speech failed: {exc}")

    # Fallback to pyttsx3 on Windows if System.Speech failed, or on other systems.
    try:
        if _TTS_ENGINE is None:
            import pyttsx3
            fallback_engine = pyttsx3.init(driverName="sapi5") if sys.platform == "win32" else pyttsx3.init()
            fallback_engine.setProperty("volume", 1.0)
            fallback_engine.setProperty("rate", 175)
            fallback_engine.say(text)
            fallback_engine.runAndWait()
            fallback_engine.stop()
        else:
            _TTS_ENGINE.say(text)
            _TTS_ENGINE.runAndWait()
        return
    except Exception as exc:
        print(f"[Voice notice] pyttsx3 speech playback failed: {exc}")

    if sys.platform == "win32":
        print("[Voice error] Speech did not start. Check Windows output device and installed speech voices.")

def remove_wake_words(query):
    """Remove the assistant's new name and keep compatibility with 'Jarvis'."""
    cleaned = query.strip()
    # Remove only complete words, so e.g. 'annual' is not changed.
    cleaned = re.sub(r"\b(?:hey\s+)?(?:anu|jarvis)\b[,!:. ]*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.!?:;-\t").strip()


def format_command_response(query, response):
    """Make command replies acknowledge Vas/Boss without changing sent message text."""
    q = (query or "").lower().strip()
    r = (response or "").strip()

    # Never wrap a failure message in a success-style acknowledgement.
    if not r or "cloud api is cooling down" in r.lower():
        return "Sorry Vas, I couldn't run that command. Please check the command action setup."
    if r.lower().startswith(("sorry", "error", "failed", "i couldn't", "i could not", "couldn't", "could not")):
        return r

    # Prefer short, explicit acknowledgements for common app/site commands.
    if "youtube" in q and any(word in q for word in ("open", "play", "search", "song")):
        return "Yes boss, opening YouTube."
    if "whatsapp" in q and any(word in q for word in ("open", "launch", "start")) and not any(word in q for word in ("send", "message", "text")):
        return "Yes boss, opening WhatsApp."
    if "linkedin" in q and any(word in q for word in ("open", "launch", "start")):
        return "Yes boss, opening LinkedIn."
    if "instagram" in q and any(word in q for word in ("open", "launch", "start")):
        return "Yes boss, opening Instagram."
    if any(word in q for word in ("send whatsapp", "whatsapp message", "send message")):
        # Preserve the sender's success/failure status and never alter the actual message body.
        return f"Vas, {r}"

    # Avoid repetitive acknowledgements if the action router already supplied one.
    if r.lower().startswith(("yes boss", "vas,")):
        return r

    # If the action itself already provides a human-readable result, acknowledge it.
    if r.lower().startswith(("opening ", "opened ", "playing ", "searching ", "sent ", "message sent", "whatsapp")):
        return f"Yes boss, {r[0].lower() + r[1:]}"
    return f"Yes boss, {r}"


def get_pre_action_acknowledgement(query):
    """Speak an acknowledgement before WhatsApp open/check actions run."""
    q = (query or "").lower().strip()
    # Speech recognition may render WhatsApp as "what's app" or "what s app".
    q = re.sub(r"\bwhat'?s\s+app\b", "whatsapp", q)
    q = re.sub(r"\bwhat\s+s\s+app\b", "whatsapp", q)

    # Sending a message has its own flow; don't mislabel it as opening WhatsApp.
    if any(word in q for word in ("send", "message", "text", "reply")):
        return None

    if re.search(r"\b(?:open|launch|start)\s+(?:the\s+)?whatsapp\b", q) or q == "whatsapp":
        return "Yes boss, opening WhatsApp."
    if re.search(r"\bcheck\s+(?:my\s+)?whatsapp\b", q):
        return "Yes boss, checking WhatsApp."
    return None


def _is_failure_response(response):
    """Return True when an action result should be spoken even after a pre-ack."""
    r = (response or "").strip().lower()
    failure_markers = (
        "sorry", "error", "failed", "couldn't", "could not", "unable to",
        "i cannot", "not configured", "couldn't find", "could not find",
    )
    return not r or any(marker in r for marker in failure_markers)


def process_command(query):
    """Route a command and speak its acknowledgement/result consistently."""
    cleaned = remove_wake_words(query)
    if not cleaned:
        speak("Yes Vas, I'm listening.")
        return

    # Media commands already return a spoken response; keep their existing route.
    media_reply = handle_media_command(cleaned)
    if media_reply:
        speak(media_reply)
        return

    # Announce WhatsApp before invoking the existing action router, so it is audible
    # at the moment the action starts and doesn't depend on the brain's reply wording.
    pre_ack = get_pre_action_acknowledgement(cleaned)
    if pre_ack:
        speak(pre_ack)

    response = jarvis_brain.think(cleaned)
    if pre_ack:
        # Avoid repeating the same success acknowledgement. Still voice any failure.
        if _is_failure_response(response):
            speak(response)
        return

    speak(format_command_response(cleaned, response))


def _console_fallback():
    """Text-input fallback when no microphone is available."""
    speak(get_time_greeting())
    while True:
        try:
            user_input = input("You: ").strip()
            if user_input:
                process_command(user_input)
        except (KeyboardInterrupt, EOFError):
            print(f"\nShutting down {ASSISTANT_NAME}. Goodbye!")
            break


def listen_loop():
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8

    try:
        mic = sr.Microphone()
    except Exception as exc:
        print(f"Error accessing microphone: {exc}")
        print("Falling back to text console input mode.")
        _console_fallback()
        return

    with mic as source:
        print("\n" + "=" * 50)
        print("  ANU AI ASSISTANT IS ACTIVE AND LISTENING")
        print("  Say commands like:")
        print("    - 'Anu, open Chrome'")
        print("    - 'Anu, play lofi on YouTube'")
        print("    - 'Anu, open WhatsApp'")
        print("    - 'Anu, send WhatsApp message to Thanush saying hi'")
        print("    - 'Anu, check my unread emails'")
        print("    - 'Anu, stock market update'")
        print("  (The old wake word 'Jarvis' still works.)")
        print("=" * 50 + "\n")
        recognizer.adjust_for_ambient_noise(source, duration=1.0)

    # Speak the personalized greeting once when the assistant starts.
    speak(get_time_greeting())

    while True:
        try:
            with mic as source:
                print("Listening... ", end="", flush=True)
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=8)
            print("Processing... ", end="", flush=True)

            query = recognizer.recognize_google(audio).strip()
            print(f'\nYou said: "{query}"')
            process_command(query)

        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            continue
        except KeyboardInterrupt:
            print(f"\nShutting down {ASSISTANT_NAME}. Goodbye!")
            break
        except Exception as exc:
            print(f"\n[Notice]: {exc}")
            # Speak a short failure notice too; command/action failures should not be silent.
            speak("Sorry Vas, something went wrong while processing that command. Please try again.")
            time.sleep(0.5)


if __name__ == "__main__":
    listen_loop()
