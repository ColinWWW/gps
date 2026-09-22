#!/usr/bin/env python3
"""WoWYap helper for WoW Forever. Cross-platform (macOS, Windows, Linux).

Hold the trigger key/button: record the mic.
Release: stop, transcribe locally with Whisper, then pass a checked packet to
the addon using reserved function keys. Direct delivery never opens chat.

Settings (trigger button, hotkey) come from the addon's SavedVariables file,
written by `/yap setup` in game. Everything runs locally; no audio leaves the PC.
"""

from __future__ import annotations

import argparse
import configparser
import ctypes
import hashlib
import math
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# SDL must be configured before pygame is imported.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np  # noqa: E402
import pygame  # noqa: E402
import sounddevice as sd  # noqa: E402
from pygame._sdl2 import controller as sdl_controller  # noqa: E402
from pynput.keyboard import Controller as KeyboardController, Key, Listener  # noqa: E402
from pynput.mouse import Listener as MouseListener  # noqa: E402

SAMPLE_RATE = 16_000
DEFAULT_CLOSE_COMMAND = "/click InputFunctionBindingButton_PAD2 LeftButton 1"
SYSTEM = platform.system()  # "Darwin", "Windows", "Linux"
CONFIG_NAME = "WoWYap.ini"


def log(text: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


def app_root() -> Path:
    """Repo root when running from source; folder containing the .exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_addon_dir() -> Path | None:
    root = app_root()
    for candidate in (
        root / "addon" / "WoWYap",
        root / "WoWYap",
        root / "addon" / "GamepadSpeak",  # legacy package layout
        root / "GamepadSpeak",
    ):
        if (candidate / "WoWYap.toc").is_file() or (candidate / "GamepadSpeak.toc").is_file():
            return candidate
    return None


def default_wow_dir() -> Path:
    if SYSTEM == "Darwin":
        return Path("/Applications/World of Warcraft/_classic_beta_")
    if SYSTEM == "Windows":
        for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files")):
            p = Path(base) / "World of Warcraft" / "_classic_beta_"
            if p.exists():
                return p
        return Path(r"C:\Program Files (x86)\World of Warcraft\_classic_beta_")
    # Linux: Wine/Lutris/Steam prefixes vary; the user passes --wow-dir.
    return Path.home() / "Games" / "world-of-warcraft" / "drive_c" / "Program Files (x86)" / "World of Warcraft" / "_classic_beta_"


def config_path() -> Path:
    return app_root() / CONFIG_NAME


def load_user_config() -> dict[str, str]:
    """Optional WoWYap.ini next to the app (no PowerShell needed to set WoW path)."""
    path = config_path()
    if not path.is_file():
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    try:
        text = path.read_text(encoding="utf-8-sig")
        body = "\n".join(
            line for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        if body and not body.lstrip().startswith("["):
            text = "[wowyap]\n" + text
        parser.read_string(text)
    except (OSError, configparser.Error) as e:
        log(f"Could not read {path.name}: {e}")
        return {}
    section = "wowyap" if parser.has_section("wowyap") else (
        "gamepadspeak" if parser.has_section("gamepadspeak") else parser.default_section)
    return {k.lower(): v.strip() for k, v in parser.items(section) if v.strip()}


def write_config_template(wow_dir: Path) -> None:
    path = config_path()
    if path.exists():
        return
    path.write_text(
        "# Optional settings. Edit this file in Notepad — no PowerShell required.\n"
        "[wowyap]\n"
        f"wow_dir = {wow_dir}\n"
        "# model = base.en\n"
        "# tiny.en may be faster, but less accurate.\n"
        "# silent = false\n",
        encoding="utf-8",
    )
    log(f"Wrote {path.name} (edit wow_dir here if WoW is not in the default location)")


def addon_signature(folder: Path) -> dict[str, str]:
    """Compare content, including same-size edits with preserved timestamps."""
    out: dict[str, str] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            rel = path.relative_to(folder).as_posix()
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def sync_error_hint(wow_dir: Path, err: BaseException) -> str:
    msg = str(err).lower()
    if isinstance(err, PermissionError) or "access is denied" in msg or "winerror 5" in msg:
        return (
            f"Cannot write to {wow_dir / 'Interface' / 'AddOns'}. "
            "WoW is probably not installed under Program Files on this PC. "
            f"Edit {CONFIG_NAME} next to Start.cmd and set wow_dir to your real folder, e.g.\n"
            "  wow_dir = D:\\MYFAVORITEMONSTERGAME\\World of Warcraft\\_classic_beta_\n"
            "Or run once: Start.cmd --wow-dir \"D:\\...\\World of Warcraft\\_classic_beta_\""
        )
    return f"Cannot write AddOns folder ({wow_dir / 'Interface' / 'AddOns'}): {err}"


def sync_addon(wow_dir: Path, source: Path | None = None) -> str:
    """Copy the bundled addon into WoW AddOns. Returns 'installed', 'updated', or 'ok'."""
    source = source or bundled_addon_dir()
    if source is None:
        return "missing"
    addons = wow_dir / "Interface" / "AddOns"
    target = addons / "WoWYap"
    legacy = addons / "GamepadSpeak"
    try:
        addons.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(sync_error_hint(wow_dir, e)) from e
    src_sig = addon_signature(source)
    if target.is_dir() and addon_signature(target) == src_sig:
        if legacy.exists():
            shutil.rmtree(legacy)
        return "ok"
    action = "updated" if target.exists() else "installed"
    staging = addons / f".WoWYap.staging-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        shutil.copytree(source, staging)
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        if legacy.exists():
            shutil.rmtree(legacy, ignore_errors=True)
    except OSError as err:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(sync_error_hint(wow_dir, err)) from err
    return action


def resolve_wow_dir(cli_value: str | None, config: dict[str, str]) -> Path:
    if cli_value:
        return Path(cli_value)
    if config.get("wow_dir"):
        return Path(os.path.expandvars(config["wow_dir"]))
    if os.environ.get("WOW_DIR"):
        return Path(os.environ["WOW_DIR"])
    return default_wow_dir()


@dataclass(frozen=True)
class AddonSettings:
    trigger: str | None = None
    hotkey: str | None = None
    trigger_type: str | None = None
    close_command: str | None = None
    direct_protocol: str | None = None
    routes: tuple[tuple[str, int], ...] = ()
    general_channel: str | None = None


class SavedVariables:
    """Reads WoWYapDB (or legacy GamepadSpeakDB) from SavedVariables."""

    def __init__(self, wow_dir: Path):
        self.wow_dir = wow_dir
        self._mtime = None
        self.settings = AddonSettings()

    @property
    def path(self) -> Path | None:
        accounts = self.wow_dir / "WTF" / "Account"
        if not accounts.is_dir():
            return None
        names = ("WoWYap.lua", "GamepadSpeak.lua")  # new name, then legacy
        for name in names:
            candidates = [p for p in accounts.glob(f"*/SavedVariables/{name}") if p.is_file()]
            if candidates:
                return max(candidates, key=lambda p: p.stat().st_mtime_ns)
        return None

    def refresh(self) -> bool:
        """Re-read the file if it changed. Returns True when settings changed."""
        p = self.path
        if p is None:
            return False
        stat = p.stat()
        mtime = (p, stat.st_mtime_ns, stat.st_size)
        if self._mtime == mtime:
            return False
        text = p.read_text(encoding="utf-8", errors="replace")
        new = AddonSettings(
            trigger=self._value("trigger", text),
            trigger_type=self._value("triggerType", text),
            hotkey=self._value("hotkey", text),
            close_command=self._value("closeCommand", text),
            direct_protocol=self._value("directProtocol", text),
            routes=self._routes(text),
            general_channel=self._value("generalChannel", text),
        )
        self._mtime = mtime
        changed = new != self.settings
        self.settings = new
        return changed

    @staticmethod
    def _value(key: str, text: str) -> str | None:
        m = re.search(r'\["%s"\]\s*=\s*"([^"]*)"' % key, text)
        return m.group(1) if m and m.group(1) else None

    @staticmethod
    def _routes(text: str) -> tuple[tuple[str, int], ...]:
        block = re.search(r'\["routes"\]\s*=\s*\{([^}]*)\}', text)
        if block:
            pairs = re.findall(r'\["([^"]+)"\]\s*=\s*(\d+)', block.group(1))
            return tuple((k, int(v)) for k, v in pairs)
        raw = SavedVariables._value("routes", text)
        if not raw:
            return ()
        out = []
        for part in raw.split(","):
            if ":" not in part:
                continue
            binding, route = part.split(":", 1)
            if route.isdigit():
                out.append((binding.strip(), int(route)))
        return tuple(out)


# ---------------------------------------------------------------------------
# Controller (SDL game controller API, same button model WoW uses)
# ---------------------------------------------------------------------------

# SDL_GameControllerButton enum values, for constants older pygame builds don't export.
SDL_BUTTON_VALUES = {
    "CONTROLLER_BUTTON_A": 0, "CONTROLLER_BUTTON_B": 1, "CONTROLLER_BUTTON_X": 2, "CONTROLLER_BUTTON_Y": 3,
    "CONTROLLER_BUTTON_BACK": 4, "CONTROLLER_BUTTON_GUIDE": 5, "CONTROLLER_BUTTON_START": 6,
    "CONTROLLER_BUTTON_LEFTSTICK": 7, "CONTROLLER_BUTTON_RIGHTSTICK": 8,
    "CONTROLLER_BUTTON_LEFTSHOULDER": 9, "CONTROLLER_BUTTON_RIGHTSHOULDER": 10,
    "CONTROLLER_BUTTON_DPAD_UP": 11, "CONTROLLER_BUTTON_DPAD_DOWN": 12,
    "CONTROLLER_BUTTON_DPAD_LEFT": 13, "CONTROLLER_BUTTON_DPAD_RIGHT": 14,
    "CONTROLLER_BUTTON_MISC1": 15, "CONTROLLER_BUTTON_PADDLE1": 16, "CONTROLLER_BUTTON_PADDLE2": 17,
    "CONTROLLER_BUTTON_PADDLE3": 18, "CONTROLLER_BUTTON_PADDLE4": 19, "CONTROLLER_BUTTON_TOUCHPAD": 20,
    "CONTROLLER_AXIS_TRIGGERLEFT": 4, "CONTROLLER_AXIS_TRIGGERRIGHT": 5,
}


def _const(name: str) -> int | None:
    return getattr(pygame, name, SDL_BUTTON_VALUES.get(name))


# WoW PAD name -> SDL controller button constant name.
PAD_TO_SDL_BUTTON = {
    "PAD1": "CONTROLLER_BUTTON_A",
    "PAD2": "CONTROLLER_BUTTON_B",
    "PAD3": "CONTROLLER_BUTTON_X",
    "PAD4": "CONTROLLER_BUTTON_Y",
    "PAD5": "CONTROLLER_BUTTON_MISC1",
    "PADSOCIAL": "CONTROLLER_BUTTON_BACK",
    "PADSYSTEM": "CONTROLLER_BUTTON_GUIDE",
    "PADFORWARD": "CONTROLLER_BUTTON_START",
    "PADLSTICK": "CONTROLLER_BUTTON_LEFTSTICK",
    "PADRSTICK": "CONTROLLER_BUTTON_RIGHTSTICK",
    "PADLSHOULDER": "CONTROLLER_BUTTON_LEFTSHOULDER",
    "PADRSHOULDER": "CONTROLLER_BUTTON_RIGHTSHOULDER",
    "PADDUP": "CONTROLLER_BUTTON_DPAD_UP",
    "PADDDOWN": "CONTROLLER_BUTTON_DPAD_DOWN",
    "PADDLEFT": "CONTROLLER_BUTTON_DPAD_LEFT",
    "PADDRIGHT": "CONTROLLER_BUTTON_DPAD_RIGHT",
    "PADBACK": "CONTROLLER_BUTTON_TOUCHPAD",
    "PADPADDLE1": "CONTROLLER_BUTTON_PADDLE1",
    "PADPADDLE2": "CONTROLLER_BUTTON_PADDLE2",
    "PADPADDLE3": "CONTROLLER_BUTTON_PADDLE3",
    "PADPADDLE4": "CONTROLLER_BUTTON_PADDLE4",
}
PAD_TO_SDL_AXIS = {
    "PADLTRIGGER": "CONTROLLER_AXIS_TRIGGERLEFT",
    "PADRTRIGGER": "CONTROLLER_AXIS_TRIGGERRIGHT",
}
TRIGGER_AXIS_THRESHOLD = 16_000  # of 32767


class ControllerWatcher:
    """Polls SDL on the calling thread (SDL wants the main thread on macOS)."""

    def __init__(self, on_press, on_release=lambda: None):
        self.on_press = on_press
        self.on_release = on_release
        self._held = set()
        self.trigger: str | None = None
        self.raw_button: int | None = None
        self._button_const: int | None = None
        self._axis_const: int | None = None
        self._axis_active = False
        self._last_press = 0.0
        self._controllers: dict[int, object] = {}
        self._joysticks: dict[int, object] = {}

    def set_trigger(self, trigger: str | None, raw_button: int | None = None) -> None:
        self.trigger = trigger
        self._held.clear()
        self.raw_button = raw_button
        self._button_const = self._axis_const = None
        if raw_button is not None:
            log(f"Watching raw joystick button {raw_button}")
            return
        if not trigger:
            return
        if trigger in PAD_TO_SDL_AXIS:
            self._axis_const = _const(PAD_TO_SDL_AXIS[trigger])
        elif trigger in PAD_TO_SDL_BUTTON:
            self._button_const = _const(PAD_TO_SDL_BUTTON[trigger])
            if self._button_const is None:
                log(f"This SDL build has no {PAD_TO_SDL_BUTTON[trigger]}; pick another button in /yap setup")
        else:
            log(f"Unknown trigger '{trigger}'")
        if self._button_const is not None or self._axis_const is not None:
            log(f"Watching {trigger}")

    def start(self) -> None:
        pygame.init()
        sdl_controller.init()
        pygame.joystick.init()
        for i in range(sdl_controller.get_count()):
            self._open(i)
        if not self._controllers and not self._joysticks:
            log("No controller found yet; waiting for one to connect")

    def _open(self, device_index: int) -> None:
        try:
            if sdl_controller.is_controller(device_index):
                c = sdl_controller.Controller(device_index)
                self._controllers[c.as_joystick().get_instance_id()] = c
                log(f"Controller: {c.name}")
            else:
                j = pygame.joystick.Joystick(device_index)
                self._joysticks[j.get_instance_id()] = j
                log(f"Joystick (no SDL mapping, raw buttons only): {j.get_name()}")
        except pygame.error as e:
            log(f"Could not open device {device_index}: {e}")

    def _edge(self, device, pressed: bool) -> None:
        was_down = bool(self._held)
        if pressed:
            self._held.add(device)
        else:
            self._held.discard(device)
        if bool(self._held) != was_down:
            (self.on_press if self._held else self.on_release)()

    def pump(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.CONTROLLERDEVICEADDED:
                self._open(event.device_index)
            elif event.type in (pygame.CONTROLLERDEVICEREMOVED, pygame.JOYDEVICEREMOVED):
                self._controllers.pop(event.instance_id, None)
                self._joysticks.pop(event.instance_id, None)
                self._edge(event.instance_id, False)
                log("Controller disconnected")
            elif event.type == pygame.JOYDEVICEADDED and self.raw_button is not None:
                self._open(event.device_index)
            elif event.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
                if self._button_const is not None and event.button == self._button_const:
                    self._edge(event.instance_id, event.type == pygame.CONTROLLERBUTTONDOWN)
            elif event.type == pygame.CONTROLLERAXISMOTION and self._axis_const is not None:
                if event.axis == self._axis_const:
                    self._edge(event.instance_id, event.value > TRIGGER_AXIS_THRESHOLD)
            elif event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                if self.raw_button is not None and event.button == self.raw_button:
                    self._edge(event.instance_id, event.type == pygame.JOYBUTTONDOWN)

    def describe(self) -> list[str]:
        out = [f"{c.name} (mapped)" for c in self._controllers.values()]
        out += [f"{j.get_name()} (raw only)" for j in self._joysticks.values()]
        return out


# ---------------------------------------------------------------------------
# Audio + transcription
# ---------------------------------------------------------------------------

class Recorder:
    def __init__(self, device=None):
        self.device = device
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._chunks = []
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            device=self.device, blocksize=1024, callback=self._callback,
        )
        try:
            self._stream.start()
        except Exception:
            self._stream.close()
            self._stream = None
            raise

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log(f"Audio status: {status}")
        with self._lock:
            self._chunks.append(indata[:, 0].copy())

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype="float32")
            self._chunks = []
        return audio


class Transcriber:
    def __init__(self, model_name: str, language: str | None, device: str, compute_type: str):
        from faster_whisper import WhisperModel  # heavy import, keep it local

        t0 = time.monotonic()
        log(f"Loading Whisper model '{model_name}' ({device}/{compute_type})...")
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self.language = language
        log(f"Model ready in {time.monotonic() - t0:.1f}s")

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size < SAMPLE_RATE // 4:
            return ""
        segments, _info = self.model.transcribe(
            audio, language=self.language, beam_size=1, best_of=1,
            vad_filter=True, condition_on_previous_text=False,
            without_timestamps=True,
        )
        text = " ".join(s.text.strip() for s in segments)
        return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Keystroke injection
# ---------------------------------------------------------------------------

# Some keys don't exist on every platform's pynput (no Insert on macOS, for example).
_KEY_NAMES = {
    "ENTER": "enter", "SPACE": "space", "TAB": "tab", "ESCAPE": "esc",
    "BACKSPACE": "backspace", "DELETE": "delete", "INSERT": "insert",
    "HOME": "home", "END": "end", "PAGEUP": "page_up", "PAGEDOWN": "page_down",
    "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right",
    **{f"F{i}": f"f{i}" for i in range(1, 21)},
}
SPECIAL_KEYS = {name: getattr(Key, attr) for name, attr in _KEY_NAMES.items() if hasattr(Key, attr)}
MODIFIERS = {"CTRL": Key.ctrl, "SHIFT": Key.shift, "ALT": Key.alt, "META": Key.cmd, "CMD": Key.cmd}


@dataclass(frozen=True)
class Hotkey:
    key: object
    modifiers: tuple

    @classmethod
    def parse(cls, binding: str) -> "Hotkey | None":
        parts = binding.upper().split("-")
        parts = [p for p in parts if p] or ["-"]
        name = parts[-1]
        key = SPECIAL_KEYS.get(name)
        if key is None:
            if len(name) == 1:
                key = name.lower()
            else:
                return None
        mods = []
        for m in parts[:-1]:
            if m not in MODIFIERS:
                return None
            mods.append(MODIFIERS[m])
        return cls(key=key, modifiers=tuple(mods))


class KeyboardWatcher:
    """Listener callbacks only enqueue events; audio/state run on the main thread."""

    def __init__(self, on_press, on_release):
        self.on_press, self.on_release = on_press, on_release
        self.events = queue.SimpleQueue()
        self.down = set()
        self.active = False
        self.binding = set()
        self.routes: dict[str, int] = {}
        self.active_route = 0
        self.active_key = None
        self.delivery_guard = None
        self.listener = None

    @staticmethod
    def name(key):
        name = getattr(key, "name", None)
        if name:
            for prefix in ("ctrl", "shift", "alt", "cmd"):
                if name == prefix or name in (prefix + "_l", prefix + "_r"):
                    return {"cmd": "META"}.get(prefix, prefix.upper())
            return {"esc": "ESCAPE", "page_up": "PAGEUP", "page_down": "PAGEDOWN"}.get(name, name.upper())
        # Windows provides virtual keys even for Ctrl+letter control characters.
        vk = getattr(key, "vk", None)
        if vk is not None and 0x30 <= vk <= 0x5A:
            return chr(vk)
        return (getattr(key, "char", None) or "").upper()

    def set_trigger(self, binding):
        self.binding = set(binding.upper().split("-")) if binding else set()
        self.down.clear()
        self.active = False
        self.active_route = 0

    def filter_delivery_keys(self, msg, data):
        # Keep injected transcript events and physical key-up events flowing.
        # Blocking only physical key-down/repeat avoids stuck movement keys.
        if data.flags & 0x12 and getattr(data, "vkCode", None) in _VK_FKEYS.values():
            return False
        guard = self.delivery_guard
        if (guard is not None and msg in (0x0100, 0x0104)
                and not (data.flags & 0x12) and guard()):
            self.listener.suppress_event()
        return True

    def start(self):
        self.listener = Listener(
            on_press=lambda k: self.events.put((k, True)),
            on_release=lambda k: self.events.put((k, False)),
            win32_event_filter=self.filter_delivery_keys,
        )
        self.listener.start()

    def _match_route(self, names: set[str], pressed_name: str | None = None) -> int | None:
        best = None
        best_size = -1
        for binding, route in self.routes.items():
            parts = set(binding.upper().split("-"))
            if pressed_name and binding.split("-")[-1] != pressed_name:
                continue
            if parts <= names and len(parts) > best_size:
                best, best_size = route, len(parts)
        if best is not None:
            return best
        if self.binding and self.binding <= names and (not pressed_name or pressed_name in self.binding):
            return 0
        return None

    def pump(self):
        while not self.events.empty():
            key, pressed = self.events.get()
            # Track physical left/right modifiers independently.
            if pressed:
                self.down.add(key)
            else:
                self.down.discard(key)
            names = {self.name(k) for k in self.down}
            if self.active:
                active = self.active_key in names if self.active_route else bool(self.binding and self.binding <= names)
                if not active:
                    self.active = False
                    self.on_release()
                continue
            if not pressed:
                continue
            route = self._match_route(names, self.name(key))
            active = route is not None
            if active and not self.active:
                self.active = True
                self.active_route = route or 0
                self.active_key = self.name(key)
                self.on_press(self.active_route)
        if self.listener is not None and not self.listener.is_alive():
            raise RuntimeError("Keyboard listener stopped; restart the helper")

    def stop(self):
        if self.listener:
            self.listener.stop()


class MouseWatcher:
    """Map Windows side buttons to WoW BUTTON4/BUTTON5 without suppressing clicks."""
    def __init__(self, on_press, on_release):
        self.on_press, self.on_release = on_press, on_release
        self.events = queue.SimpleQueue()
        self.trigger = None
        self.routes: dict[str, int] = {}
        self.modifiers = lambda: set()
        self.active = False
        self.active_button = None
        self.active_route = 0
        self.listener = None

    def set_trigger(self, trigger):
        self.trigger = trigger
        self.active = False
        self.active_button = None
        self.active_route = 0
        while not self.events.empty():
            self.events.get()

    def _on_click(self, x, y, button, pressed):
        self.events.put((button, pressed, frozenset(self.modifiers())))

    def start(self):
        self.listener = MouseListener(on_click=self._on_click)
        self.listener.start()

    def _binding(self, button_name: str, mods=None) -> str:
        mods = self.modifiers() if mods is None else mods
        prefix = ""
        for name in ("CTRL", "SHIFT", "ALT"):
            if name in mods:
                prefix += name + "-"
        return prefix + button_name

    def pump(self):
        while not self.events.empty():
            event = self.events.get()
            button, pressed = event[:2]
            mods = event[2] if len(event) > 2 else None
            name = {"x1": "BUTTON4", "x2": "BUTTON5"}.get(getattr(button, "name", None))
            if name is None:
                continue
            if pressed and not self.active:
                binding = self._binding(name, mods)
                if binding in self.routes:
                    route = self.routes[binding]
                elif name == self.trigger:
                    route = 0
                else:
                    continue
                self.active = True
                self.active_button = name
                self.active_route = route
                self.on_press(route)
            elif not pressed and self.active and name == self.active_button:
                self.active = False
                self.active_button = None
                self.on_release()
        if self.listener is not None and not self.listener.is_alive():
            raise RuntimeError("Mouse listener stopped; restart the helper")

    def stop(self):
        if self.listener:
            self.listener.stop()


def direct_packet(text: str, route: int = 0) -> bytes:
    """Versioned, length-checked UTF-8 message with optional chat route."""
    text = " ".join(text.split())
    payload = text.encode("utf-8")
    if not payload or len(payload) > 255:
        raise ValueError("Direct messages must contain 1-255 UTF-8 bytes; try a shorter sentence")
    if any(b < 32 or b == 127 for b in payload):
        raise ValueError("Invalid control character in transcript")
    if route not in range(9):
        raise ValueError("Invalid chat route")
    body = b"GP\x02" + bytes([len(payload), route]) + payload
    checksum = 0
    for b in body:
        checksum = (checksum * 33 + b) % 65521
    return body + checksum.to_bytes(2, "big")


# Direct transport uses F9=0 and F10=1 only. (F13/F14 are often ignored by WoW clients.)
DIRECT_BIT_KEYS = (Key.f9, Key.f10)


class Injector:
    def __init__(self, char_delay: float = 0.002, packet_delay: float = 0.0025, key_hold: float = 0):
        self.kb = KeyboardController()
        self.char_delay = char_delay
        self.packet_delay = packet_delay
        self.key_hold = key_hold
        self._windows_sender = None

    def press_hotkey(self, hk: Hotkey) -> None:
        for m in hk.modifiers:
            self.kb.press(m)
            time.sleep(0.005)
        self.kb.press(hk.key)
        time.sleep(0.01)
        self.kb.release(hk.key)
        for m in reversed(hk.modifiers):
            time.sleep(0.005)
            self.kb.release(m)

    def type_text(self, text: str, allowed=lambda: True) -> None:
        for ch in text:
            if not allowed():
                raise RuntimeError("Typing cancelled: WoW lost focus")
            self.kb.press(ch)
            self.kb.release(ch)
            time.sleep(self.char_delay)

    def _enter(self) -> None:
        self.kb.press(Key.enter)
        self.kb.release(Key.enter)

    def deliver_direct(self, text: str, route: int = 0, allowed=lambda: True) -> None:
        """Send one byte-sized scan-code batch per pause, leaving WASD untouched."""
        packet = direct_packet(text, route)
        hold = getattr(self, "key_hold", 0)
        sender = None
        if SYSTEM == "Windows":
            if getattr(self, "_windows_sender", None) is None:
                self._windows_sender = WindowsKeySender()
            sender = self._windows_sender

        def emit(vks):
            if not allowed():
                raise RuntimeError("Direct delivery cancelled: WoW lost focus")
            if sender:
                sender.send(vks, hold, allowed)
            else:
                keys = {0x78: DIRECT_BIT_KEYS[0], 0x79: DIRECT_BIT_KEYS[1],
                        0x7A: Key.f11, 0x7B: Key.f12}
                for vk in vks:
                    if not allowed():
                        raise RuntimeError("Direct delivery cancelled: WoW lost focus")
                    self.kb.press(keys[vk])
                    try:
                        if hold:
                            time.sleep(hold)
                    finally:
                        self.kb.release(keys[vk])
        emit((0x7A,))
        for byte in packet:
            emit(tuple(0x78 + ((byte >> shift) & 1) for shift in range(7, -1, -1)))
            if self.packet_delay:
                time.sleep(self.packet_delay)
        emit((0x7B,))

    def deliver(self, text: str, open_key: Hotkey | None, close_key: Hotkey | None,
                close_command: str | None, allowed=lambda: True) -> None:
        if not allowed():
            return
        if open_key is not None:
            self.press_hotkey(open_key)
            time.sleep(0.12)
        self.type_text(text, allowed)
        time.sleep(0.04)
        if not allowed():
            return
        self._enter()
        if close_command:
            # The box keeps focus after a send in gamepad style. This slash
            # command clicks the addon's secure button, which lets Blizzard
            # code deactivate the box; typed + Enter keeps it fully secure.
            time.sleep(0.15)
            self.type_text(close_command, allowed)
            time.sleep(0.03)
            if not allowed():
                return
            self._enter()
        if close_key is not None and allowed():
            time.sleep(0.10)
            self.press_hotkey(close_key)


def frontmost_app_name() -> str | None:
    """Best effort per platform. None means 'unknown'."""
    try:
        if SYSTEM == "Darwin":
            try:
                from AppKit import NSWorkspace  # type: ignore
                app = NSWorkspace.sharedWorkspace().frontmostApplication()
                return app.localizedName() if app else None
            except ImportError:
                out = subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to get name of first process whose frontmost is true'],
                    capture_output=True, text=True, timeout=2,
                )
                return out.stdout.strip() or None
        if SYSTEM == "Windows":
            title, exe = windows_foreground_info()
            # Prefer window title when present; exe catches blank-title fullscreen clients.
            if title:
                return title
            return exe
        if SYSTEM == "Linux":
            out = subprocess.run(["xdotool", "getactivewindow", "getwindowname"],
                                 capture_output=True, text=True, timeout=2)
            return out.stdout.strip() or None
    except Exception:
        return None
    return None


def windows_foreground_info() -> tuple[str | None, str | None]:
    """Return (window_title, exe_basename) for the foreground window."""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or None

    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    pid = ctypes.c_uint32()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            size = ctypes.c_uint32(32768)
            path_buf = ctypes.create_unicode_buffer(size.value)
            # QueryFullProcessImageNameW
            if kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                exe = Path(path_buf.value).name
        finally:
            kernel32.CloseHandle(handle)
    return title, exe


def looks_like_wow(title: str | None, exe: str | None = None) -> bool:
    if exe:
        return exe.lower() in {"wow.exe", "wowclassic.exe", "wowt.exe", "wowb.exe", "world of warcraft.exe"}
    for value in (title,):
        if not value:
            continue
        n = value.lower()
        if "world of warcraft" in n or n in {"wow", "wow classic", "wow forever"}:
            return True
        # WoW Forever / Classic client binaries are often Wow.exe / WowClassic.exe.
        if n in {"wow.exe", "wowclassic.exe", "wowt.exe", "wowb.exe", "world of warcraft.exe"}:
            return True
    return False


def foreground_identity():
    if SYSTEM == "Windows":
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        return user32.GetForegroundWindow()
    return frontmost_app_name()


def wow_is_frontmost() -> bool | None:
    """True/False when known; None when the OS could not identify the foreground app."""
    if SYSTEM == "Windows":
        try:
            title, exe = windows_foreground_info()
        except Exception:
            return None
        if title is None and exe is None:
            return None
        return looks_like_wow(title, exe)
    name = frontmost_app_name()
    if name is None:
        return None
    return looks_like_wow(name)


# Virtual-key codes for reserved transport keys.
_VK_FKEYS = {
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


# Windows has 32-bit DWORD/LONG even in a 64-bit process. The full union is
# necessary for sizeof(INPUT) to be 40 on x64 and 28 on x86.
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("dwExtraInfo", ctypes.c_size_t)]

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32),
                ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]

class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

class _INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", ctypes.c_uint32), ("data", _INPUTUNION)]

class WindowsKeySender:
    def __init__(self, user32=None):
        self.api = user32 or ctypes.windll.user32
        self.api.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
        self.api.SendInput.restype = ctypes.c_uint
        self.api.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self.api.MapVirtualKeyW.restype = ctypes.c_uint
        self.scans = {vk: self.api.MapVirtualKeyW(vk, 0) & 0xFF for vk in _VK_FKEYS.values()}
        self.cache = {}

    def events(self, vks, up_only=False):
        events = []
        for vk in vks:
            for flags in ((0x000A,) if up_only else (0x0008, 0x000A)):
                events.append(_INPUT(type=1, ki=_KEYBDINPUT(0, self.scans[vk], flags, 0, 0)))
        return (_INPUT * len(events))(*events)

    def emit(self, events):
        sent = self.api.SendInput(len(events), events, ctypes.sizeof(_INPUT))
        if sent != len(events):
            # Best effort release of only our reserved keys after partial input.
            cleanup = self.events(tuple(self.scans), up_only=True)
            self.api.SendInput(len(cleanup), cleanup, ctypes.sizeof(_INPUT))
            raise RuntimeError(f"SendInput accepted {sent}/{len(events)} events; packet cancelled")

    def send(self, vks, hold=0, allowed=lambda: True):
        if not hold:
            if vks not in self.cache:
                self.cache[vks] = self.events(vks)
            self.emit(self.cache[vks])
            return
        # Compatibility option for clients that need a measurable key hold.
        for vk in vks:
            if not allowed():
                raise RuntimeError("Direct delivery cancelled: WoW lost focus")
            events = self.events((vk,))
            self.emit((_INPUT * 1)(events[0]))
            try:
                time.sleep(hold)
            finally:
                self.emit((_INPUT * 1)(events[1]))


# ---------------------------------------------------------------------------
# Sounds (short generated tones, no platform audio APIs needed)
# ---------------------------------------------------------------------------

def tone(freq: float, seconds: float = 0.12, volume: float = 0.055) -> np.ndarray:
    t = np.linspace(0, seconds, int(44_100 * seconds), endpoint=False)
    env = np.sin(np.linspace(0, np.pi, t.size)) ** 2
    return (volume * env * np.sin(2 * np.pi * freq * t)).astype("float32")


class Sounds:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.start_tone = tone(520)
        self.stop_tone = tone(390)
        self.error_tone = tone(330, 0.18, 0.045)

    def play(self, which: np.ndarray) -> None:
        if not self.enabled:
            return
        try:
            sd.play(which, 44_100)
        except Exception as e:  # never let a beep break the flow
            log(f"Sound failed: {e}")


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class Coordinator:
    IDLE, RECORDING, FINALIZING = "idle", "recording", "finalizing"

    def __init__(self, args):
        self.args = args
        self.saved = SavedVariables(Path(args.wow_dir))
        self.watcher = ControllerWatcher(lambda: self.on_trigger(source="controller"), lambda: self.on_release("controller"))
        self.keyboard = KeyboardWatcher(lambda route: self.on_trigger(route, "keyboard"), lambda: self.on_release("keyboard"))
        self.mouse = MouseWatcher(lambda route: self.on_trigger(route, "mouse"), lambda: self.on_release("mouse"))
        self.mouse.modifiers = self.physical_modifiers
        self.trigger_type = "keyboard"
        self.target = None
        self.chat_route = 0
        self.cancelled = threading.Event()
        self.recorder = Recorder(device=args.input_device)
        self.injector = Injector(packet_delay=args.packet_delay, key_hold=args.key_hold)
        self.sounds = Sounds(not args.silent)
        self.transcriber: Transcriber | None = None
        self.hotkey: Hotkey | None = None
        self.close_key: Hotkey | None = None
        self.state = self.IDLE
        self.record_start = 0.0
        self._lock = threading.Lock()

    def physical_modifiers(self) -> set[str]:
        if SYSTEM == "Windows":
            get = ctypes.windll.user32.GetAsyncKeyState  # type: ignore[attr-defined]
            return {name for name, vk in (("CTRL", 0x11), ("SHIFT", 0x10), ("ALT", 0x12))
                    if get(vk) & 0x8000}
        return {self.keyboard.name(k) for k in tuple(self.keyboard.down)} & {"CTRL", "SHIFT", "ALT"}

    def close_command(self) -> str | None:
        choice = self.args.close_command
        if choice.lower() == "auto" and self.trigger_type in ("keyboard", "mouse"):
            return None
        if choice.lower() == "none":
            return None
        if choice.lower() == "auto":
            return (None if self.saved.settings.close_command == "none" else
                    self.saved.settings.close_command or DEFAULT_CLOSE_COMMAND)
        return choice

    def apply_settings(self) -> None:
        trigger = self.args.button or self.saved.settings.trigger or "F8"
        routes = dict(self.saved.settings.routes) if self.args.delivery == "direct" and not self.args.button else {}
        self.trigger_type = ("gamepad" if self.args.raw_button is not None or trigger.startswith("PAD")
                             else "mouse" if trigger in ("BUTTON4", "BUTTON5")
                             else "keyboard")
        self.watcher.set_trigger(trigger if self.trigger_type == "gamepad" else None, self.args.raw_button)
        self.keyboard.set_trigger(trigger if self.trigger_type == "keyboard" else None)
        self.keyboard.routes = {k: v for k, v in routes.items()
                                if not k.endswith(("BUTTON4", "BUTTON5"))}
        self.mouse.set_trigger(trigger if self.trigger_type == "mouse" else None)
        self.mouse.routes = {k: v for k, v in routes.items()
                             if k.endswith(("BUTTON4", "BUTTON5"))}
        # How the chat box gets opened before typing. Default is the game's own
        # Enter binding (OPENCHAT), which keeps addon code out of the chat path.
        choice = self.args.open_key
        if choice.lower() == "none":
            self.hotkey = None
        elif choice.lower() == "addon":
            self.hotkey = Hotkey.parse(self.saved.settings.hotkey or "")
            if self.hotkey is None:
                log(f"Addon hotkey '{self.saved.settings.hotkey}' unavailable; using Enter instead")
                self.hotkey = Hotkey.parse("ENTER")
        else:
            self.hotkey = Hotkey.parse(choice)
            if self.hotkey is None:
                log(f"Can't parse --open-key '{choice}'; using Enter")
                self.hotkey = Hotkey.parse("ENTER")
        self.close_key = None if self.args.close_key.lower() == "none" else Hotkey.parse(self.args.close_key)
        if self.close_key is None and self.args.close_key.lower() != "none":
            log(f"Can't parse --close-key '{self.args.close_key}'; not closing chat")
        route_summary = ", ".join(f"{k}→{v}" for k, v in sorted(routes.items())) or "none"
        log(f"Settings: trigger={trigger or 'none'} open-chat={choice} "
            f"close-command={self.close_command() or 'none'} routes={route_summary}")


    def run(self) -> None:
        self.transcriber = Transcriber(self.args.model, self.args.language, self.args.device, self.args.compute_type)
        self.saved.refresh()
        if self.saved.path is None:
            log(f"Addon settings file not found under {self.saved.wow_dir / 'WTF'}. "
                "Using F8 by default. Install the addon and use /yap settings to change it.")
        self.apply_settings()
        if self.args.delivery == "direct":
            if self.saved.settings.direct_protocol != "2":
                raise RuntimeError("Direct delivery needs the updated addon: reinstall it, enter WoW, "
                                   "check /yap status, then /reload and restart the helper")
            reserved = {"F9", "F10", "F11", "F12"}
            trigger_key = (self.args.button or self.saved.settings.trigger or "F8").split("-")[-1]
            if trigger_key in reserved:
                raise RuntimeError("F9-F12 are reserved for direct delivery; choose another talk trigger")
            log(f"Direct delivery: {self.args.packet_delay * 1000:.1f}ms byte pacing, "
                f"{self.args.key_hold * 1000:.1f}ms key hold. "
                "Chat stays closed; F9-F12 reserved.")
        self.watcher.start()
        self.keyboard.start()
        if SYSTEM == "Windows":
            self.mouse.start()
        log("Ready. Hold the trigger to record; release to transcribe and send.")

        last_poll = 0.0
        while True:
            self.watcher.pump()
            self.keyboard.pump()
            self.mouse.pump()
            now = time.monotonic()
            if now - last_poll > 2.0:
                last_poll = now
                if self.saved.refresh():
                    log("Addon settings changed")
                    self.cancel_recording()
                    self.apply_settings()
            if self.state in (self.RECORDING, self.FINALIZING) and not self.args.any_app:
                # Stay with the exact game window verified at recording start.
                if foreground_identity() != self.target:
                    self.cancel_recording()
            if self.state == self.RECORDING and now - self.record_start > self.args.max_seconds:
                log("Max duration reached, stopping")
                self.end_recording()
            time.sleep(0.01)

    def on_trigger(self, route: int = 0, source: str = "keyboard") -> None:
        with self._lock:
            if self.state == self.IDLE:
                front = wow_is_frontmost()
                if not self.args.any_app and front is not True:
                    log(f"Trigger ignored: WoW is not detected in foreground ({frontmost_app_name() or 'unknown'})")
                    return
                self.target = foreground_identity()
                self.chat_route = route
                self.recording_source = source
                self.cancelled.clear()
                self.begin_recording()

    def on_release(self, source=None) -> None:
        with self._lock:
            if self.state == self.RECORDING and (source is None or source == self.recording_source):
                self.end_recording()

    def cancel_recording(self):
        self.cancelled.set()
        if self.state == self.RECORDING:
            try:
                self.recorder.stop()
            finally:
                self.state = self.IDLE
            log("Yapping cancelled (focus or settings changed)")

    def close(self):
        self.cancel_recording()
        self.keyboard.stop()
        self.mouse.stop()
        pygame.quit()

    def begin_recording(self) -> None:
        try:
            self.recorder.start()
        except Exception as e:
            log(f"Could not start audio: {e}")
            self.sounds.play(self.sounds.error_tone)
            return
        self.state = self.RECORDING
        self.record_start = time.monotonic()
        self.sounds.play(self.sounds.start_tone)
        log("Yapping...")

    def end_recording(self) -> None:
        if self.state != self.RECORDING:
            return
        self.state = self.FINALIZING
        try:
            audio = self.recorder.stop()
        except Exception as e:
            self.state = self.IDLE
            log(f"Could not stop audio: {e}")
            return
        self.sounds.play(self.sounds.stop_tone)
        log(f"Stopped after {time.monotonic() - self.record_start:.1f}s, transcribing...")
        threading.Thread(target=self._finish, args=(audio,), daemon=True).start()

    def _finish(self, audio: np.ndarray) -> None:
        t0 = time.monotonic()
        try:
            text = self.transcriber.transcribe(audio) if self.transcriber else ""
        except Exception as e:
            log(f"Transcription failed: {e}")
            text = ""
        ms = int((time.monotonic() - t0) * 1000)
        try:
            if not text:
                log(f"Nothing transcribed ({ms}ms)")
                self.sounds.play(self.sounds.error_tone)
                return
            log(f"Transcript ({ms}ms): {text}")
            front = wow_is_frontmost()
            if self.cancelled.is_set():
                log("Transcript discarded after focus/settings change")
                return
            # Require the same verified game window that began this recording.
            if not self.args.any_app and (front is not True or foreground_identity() != self.target):
                log(f"WoW is not the frontmost app ({frontmost_app_name()}); not typing")
                self.sounds.play(self.sounds.error_tone)
                return
            direct = self.args.delivery == "direct"
            if direct and self.saved.settings.direct_protocol != "2":
                raise RuntimeError("Addon direct delivery unavailable; check /yap status and /reload")
            # Direct transport uses reserved keys whose modifier variants map to
            # the same symbols, so held Shift/Ctrl during a route press is fine.
            # Legacy text injection must wait for modifiers to be released.
            deadline = time.monotonic() + 5
            while self.keyboard.active or self.mouse.active or self.watcher._held or (not direct and any(
                self.keyboard.name(k) in {"CTRL", "SHIFT", "ALT", "META"}
                for k in tuple(self.keyboard.down)
            )):
                if self.cancelled.is_set() or time.monotonic() > deadline:
                    log("Not typing while trigger/modifiers remain held")
                    return
                time.sleep(0.01)

            def delivery_allowed():
                if self.cancelled.is_set():
                    return False
                if self.args.any_app:
                    return True
                # Identity was verified once before delivery. Avoid reopening
                # the foreground process for every bit of the packet.
                return self.target is not None and foreground_identity() == self.target

            if direct:
                delivery_start = time.monotonic()
                self.injector.deliver_direct(text, self.chat_route, delivery_allowed)
                log(f"Timing: transcription={ms}ms delivery={int((time.monotonic()-delivery_start)*1000)}ms "
                    f"total={int((time.monotonic()-t0)*1000)}ms")
                log("Key packet sent. Check the destination chat for your message. "
                    "If not, check /yap status and that F9-F12 are free.")
            else:
                self.keyboard.delivery_guard = delivery_allowed
                try:
                    self.injector.deliver(text, self.hotkey, self.close_key, self.close_command(), delivery_allowed)
                finally:
                    self.keyboard.delivery_guard = None
                log("Delivery finished")
        except Exception as e:
            log(f"Could not deliver transcript: {e}")
            self.sounds.play(self.sounds.error_tone)
        finally:
            self.state = self.IDLE


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_check(args) -> None:
    saved = SavedVariables(Path(args.wow_dir))
    saved.refresh()
    print(f"Platform:       {SYSTEM} / Python {platform.python_version()} / pygame {pygame.version.ver} (SDL {'.'.join(map(str, pygame.get_sdl_version()))})")
    print(f"App root:       {app_root()}")
    print(f"Bundled addon:  {bundled_addon_dir() or 'not found'}")
    print(f"WoW dir:        {args.wow_dir} {'(ok)' if Path(args.wow_dir).exists() else '(MISSING)'}")
    print(f"Config file:    {config_path()} {'(present)' if config_path().is_file() else '(optional)'}")
    installed = Path(args.wow_dir) / "Interface" / "AddOns" / "WoWYap"
    print(f"Installed addon: {installed} {'(ok)' if installed.is_dir() else '(missing — will sync on start)'}")
    print(f"Settings file:  {saved.path or 'not found'}")
    trigger = args.button or saved.settings.trigger or "F8"
    print(f"Trigger:        {trigger or 'none'}")
    hk = saved.settings.hotkey
    print(f"Hotkey:         {hk or 'none'} -> {'parsed' if hk and Hotkey.parse(hk) else 'unparsed'}")
    print(f"Whisper model:  {args.model} ({args.device}/{args.compute_type}), language={args.language or 'auto'}")
    try:
        dev = sd.query_devices(kind="input")
        print(f"Mic:            {dev['name']}")
    except Exception as e:
        print(f"Mic:            none ({e})")
    watcher = ControllerWatcher(lambda: None)
    watcher.start()
    time.sleep(0.3)
    watcher.pump()
    names = watcher.describe()
    print(f"Controllers:    {len(names)}")
    for n in names:
        print(f"  - {n}")
    print(f"Frontmost app:  {frontmost_app_name() or 'unknown'} (WoW: {wow_is_frontmost()})")


def apply_startup(args) -> None:
    """Sync the addon into WoW and ensure a config template exists."""
    wow = Path(args.wow_dir)
    write_config_template(wow)
    if args.skip_addon_sync:
        return
    try:
        result = sync_addon(wow)
    except Exception as e:
        log(f"Addon sync failed: {e}")
        log("Fix wow_dir in WoWYap.ini (or pass --wow-dir), then restart.")
        return
    if result == "missing":
        log("No bundled addon folder found next to the helper; skipping sync.")
    elif result == "installed":
        log(f"Addon installed into {wow / 'Interface' / 'AddOns' / 'WoWYap'}")
        log("In WoW: enable WoWYap, then /reload")
    elif result == "updated":
        log("Addon updated in WoW AddOns. In game type /reload so the new version loads.")
    else:
        log("Addon already up to date in WoW AddOns")


def main() -> None:
    config = load_user_config()
    ap = argparse.ArgumentParser(
        description="WoWYap helper: hold-to-yap voice to WoW chat. "
                    "Double-click Start.cmd on Windows — no PowerShell required.")
    ap.add_argument("--wow-dir", default=None,
                    help="WoW flavor directory (the _classic_beta_ folder). "
                         "Overrides WoWYap.ini and WOW_DIR.")
    ap.add_argument("--button", help="Override the in-game trigger, e.g. F8, CTRL-F9 or PADSOCIAL")
    ap.add_argument("--raw-button", type=int, help="Use a raw joystick button index instead of an SDL mapping")
    ap.add_argument("--language", help="Speech language code, e.g. en or bg (default: auto-detect)")
    ap.add_argument("--model", default=config.get("model", "base.en"),
                    help="Whisper model: tiny.en, base.en, tiny, base, small, medium, large-v3 (default: base.en)")
    ap.add_argument("--device", default="cpu", help="Whisper device: auto, cpu, cuda (default: cpu; no CUDA libraries required)")
    ap.add_argument("--compute-type", default="int8", help="Whisper compute type (default: int8)")
    ap.add_argument("--input-device", help="Mic device name or index for sounddevice")
    ap.add_argument("--delivery", choices=("direct", "chat"), default="direct",
                    help="direct (default): addon sends without opening chat; chat: legacy text injection")
    ap.add_argument("--key-hold", type=float, default=config.get("key_hold", "0"),
                    help="Compatibility hold per transport key (default 0; try .001 for dropped input)")
    ap.add_argument("--packet-delay", type=float, default=config.get("packet_delay", "0.0025"),
                    help="Pause after each byte in direct mode (default: 0.0025s). "
                         "Raise to 0.004 if WoW reports incomplete messages; lower for speed.")
    ap.add_argument("--close-command", default="auto",
                    help="Slash command typed after sending to leave the chat box. 'auto' (default) uses the one "
                         "the addon computed (the gamepad Back button's click target), 'none' skips it, "
                         "or give a command such as '/click InputFunctionBindingButton_PAD2 LeftButton 1'")
    ap.add_argument("--close-key", default="none",
                    help="Extra key pressed after sending, e.g. ESCAPE. Default none: the box closes by itself "
                         "when chat was opened via the addon hotkey")
    ap.add_argument("--silent", action="store_true", help="No start/stop sounds")
    ap.add_argument("--open-key", default="ENTER",
                    help="Key that opens chat before typing: ENTER (the game's Open Chat, default), "
                         "'addon' (the addon's hotkey; taints the gamepad UI in WoW Forever, avoid), "
                         "any binding like CTRL-SHIFT-F12, or 'none'")
    ap.add_argument("--max-seconds", type=float, default=60, help="Auto-stop recording after this long")
    ap.add_argument("--any-app", action="store_true", help="Type even if WoW is not the frontmost app")
    ap.add_argument("--skip-addon-sync", action="store_true",
                    help="Do not copy the bundled addon into WoW on startup")
    ap.add_argument("--install-addon", action="store_true",
                    help="Sync the addon into WoW and exit (used by installers)")
    ap.add_argument("--check", action="store_true", help="Print status and exit")
    args = ap.parse_args()
    args.wow_dir = str(resolve_wow_dir(args.wow_dir, config))
    if not args.silent and config.get("silent", "").lower() in ("1", "true", "yes"):
        args.silent = True
    if args.language is None and args.model.endswith(".en"):
        args.language = "en"

    if args.input_device is not None and args.input_device.isdigit():
        args.input_device = int(args.input_device)

    if args.max_seconds <= 0:
        ap.error("--max-seconds must be positive")
    if not math.isfinite(args.packet_delay) or not 0 <= args.packet_delay <= 0.04:
        ap.error("--packet-delay must be between 0 and 0.04")
    if not math.isfinite(args.key_hold) or not 0 <= args.key_hold <= 0.004:
        ap.error("--key-hold must be between 0 and 0.004")

    if args.install_addon:
        write_config_template(Path(args.wow_dir))
        result = sync_addon(Path(args.wow_dir))
        if result == "missing":
            raise SystemExit("Bundled addon not found next to the helper")
        print(f"Addon {result}: {Path(args.wow_dir) / 'Interface' / 'AddOns' / 'WoWYap'}")
        return

    if args.check:
        apply_startup(args)
        run_check(args)
        return

    apply_startup(args)
    coordinator = Coordinator(args)
    try:
        coordinator.run()
    except KeyboardInterrupt:
        log("Bye")
    finally:
        coordinator.close()


if __name__ == "__main__":
    main()
