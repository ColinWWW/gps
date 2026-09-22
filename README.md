# WoWYap — WoW hold-to-yap

Based on [kubeden/yap](https://github.com/kubeden/yap). This version adds an **in-game settings panel**, keyboard triggers, and **hold-to-yap** for keyboard and controller input.

**Hold F8 → yap → release F8 → local Whisper transcription → WoW chat.**

The default model is `tiny.en`, with English selected automatically, running on the CPU with `int8` compute. No NVIDIA CUDA libraries are required. Use `--model base.en` for the larger English model. GPU users with the required CUDA libraries installed can opt in with `--device cuda`.

This is still a WoW addon **plus an external helper**. WoW addons cannot capture the microphone or run Whisper themselves. The helper must remain running. This source targets the original WoW Forever client (Interface 16001); other Retail/Classic versions have not been validated.

## Windows setup (double-click)

No PowerShell required for normal use.

1. Download the **WoWYap-Windows** artifact from [GitHub Actions](../../actions) (**Build Windows helper**), or use this repository checkout.
2. Close WoW. Double-click **`Start.cmd`**.
   - It copies/updates the addon into WoW automatically.
   - It starts the helper and keeps a console window open (leave it open while you play).
3. In WoW, enable **WoWYap** if prompted, then type **`/reload`**.
4. Open **`/yap`** (or Options → AddOns → WoWYap), pick your hold-to-yap key or mouse button, then speak.

If WoW is not under the default Program Files path, edit **`WoWYap.ini`** next to `Start.cmd` (a template is created on first run; see `WoWYap.ini.example`).

| Double-click | What it does |
|---|---|
| **Start.cmd** | Sync addon + run helper (daily use) |
| **Install.cmd** | Sync addon only, then exit |
| **Check.cmd** | Print mic / WoW path / settings diagnostics |

`install.ps1` / `run-helper.ps1` still work if you prefer PowerShell.

### Updating

Replace the folder with a newer Actions build (or `git pull`), then double-click **Start.cmd** again. The helper refreshes the addon in WoW; type **`/reload`** in game when it says the addon was updated.

### From source (developers)

Install [Python 3.12+](https://www.python.org/downloads/) (or [uv](https://github.com/astral-sh/uv)). Double-click **Start.cmd** — it creates a local `.venv` on first run. Optional: `run-helper.ps1 --language en`.

## In-game options

F8 is the default. Click **Change keyboard key**, then press your desired key, optionally with Ctrl, Shift, or Alt. **Selecting the key saves it and reloads the UI.** Escape cancels. The helper reads the saved setting within about two seconds. If the client refuses the automatic reload, type `/reload`.

Supported keyboard keys: F1–F8 and F15–F20 (where supported by your client; F9–F12 are reserved for delivery), A–Z, 0–9, Insert/Delete, Home/End, Page Up/Down, and arrow keys, with optional Ctrl/Shift/Alt. Use an unused key: existing game actions are not unbound. On Windows, select **Use Mouse4** or **Use Mouse5** in `/yap settings` (or run `/yap mouse4` / `/yap mouse5`). These are the physical back/forward side buttons; mouse software must not remap them to keyboard keys. Selecting one saves and reloads the UI. Existing mouse bindings still fire. Direct delivery supports held modifiers and movement keys.

For multiple chat destinations, click **Mouse4=Say, Shift+Mouse4=General, Mouse5=Guild** in `/yap settings`, or run `/yap routes mouse`. The destination is chosen when you press the button (so releasing Shift mid-recording still goes to General). Custom routes: `/yap route BUTTON4 say`, `/yap route SHIFT-BUTTON4 general`, `/yap route BUTTON5 guild`. Use `/yap general <name>` if your General channel is localized.

For a controller, click **Change controller button**, or use `/yap gamepad`. Controller buttons and trigger axes now also use hold/release instead of toggle. Direct delivery does not open chat for either keyboard, mouse, or controller triggers. The original gamepad chat-closing workaround is only used with `--delivery chat`.

Recording cues are now quieter, lower-pitched single tones with smooth fades. Use `--silent` to disable them entirely.

## Options and troubleshooting

- `/yap setup`: choose a keyboard key and reload.
- `/yap status`: inspect settings.
- `Check.cmd` or `run-helper.ps1 --check`: inspect microphone, settings path and foreground detection.
- `Start.cmd --input-device "Microphone name"`: select a microphone.
- `Start.cmd --model small --language en`: choose recognition settings.
- Edit `WoWYap.ini` or pass `--wow-dir "C:\path\to\_classic_beta_"`: point the helper at the same WoW installation as the addon.
- `Start.cmd --button F8`: temporary helper-only override; normally use the in-game setting so the indicator agrees.

Recording starts only when WoW is detected in the foreground. Leaving WoW cancels the recording or pending delivery. Failure to identify the foreground window also prevents recording. Recordings are capped at 60 seconds by default. If the talk trigger remains held for five seconds after transcription, delivery is discarded. In legacy chat mode, held modifiers also delay delivery. Empty speech, microphone and transcription failures return the helper to idle.

The addon clears its indicator after a direct send attempt. The helper cannot receive an acknowledgment from WoW: “Packet delivered” confirms only that the keystrokes were emitted. Check game chat for the actual message or an addon error. The indicator may show “Transcribing” briefly after cancelled or empty speech. The original beta's settings-macro backup is preserved; do not edit the `WoWYap` macro.

The helper records/transcribes locally. Model downloads need internet; audio is not uploaded. Transcripts appear in the helper console and are sent to WoW chat.

## Performance / language choice

**Python is the right tool for this helper.** Almost all latency is Whisper transcription (`faster-whisper` / CTranslate2), which already runs in native C++ (and optional CUDA). The Python layer only records audio, watches keys/mouse, and injects a short key packet — rewriting that glue in Rust, Go, or C# would not meaningfully speed up speak→chat. For day-to-day use, prefer the packaged **`.exe`** from Actions so you never install Python.

## Windows executable build

The **Build Windows helper** GitHub Actions workflow builds a console `.exe`, bundles the addon, and includes **Start.cmd** / **Install.cmd** / **Check.cmd**. Run it from the repository's Actions tab, then download the `WoWYap-Windows` artifact. Extract the folder anywhere and double-click **Start.cmd**. The `.exe` accepts the same helper options, including `--wow-dir`.

A successful workflow run is required before claiming a working executable. Live microphone capture, key delivery, and addon behavior must still be checked inside WoW on Windows.

## Development checks

Install helper dependencies and `lupa`, then run:

```powershell
python -m unittest discover -s tests -v
```

Tests cover key repeats, short controller holds, modifier release order, focus restrictions, error recovery, settings selection/persistence, addon sync, and the addon recording/release indicator using a stubbed WoW API. They do not replace an in-game integration test.

## Direct delivery (no chat focus)

Default `--delivery direct` sends a versioned UTF-8 packet to the addon through F9/F10 (bits), F11 (start) and F12 (send). The addon checks length and checksum, then calls the chat API from the final key binding. It never focuses an edit box, stops movement, or suppresses physical keys. Keep holding WASD. Reserved bindings are installed out of combat and remain available during combat; this beta client still requires live validation.

Both addon **and helper** must be updated. Enter WoW and run `/reload` before restarting the helper so it can read the new protocol setting. If F9–F12 or their modifier combinations have existing actions, the addon reports the conflict and disables direct delivery until those bindings are freed and the UI reloaded. Existing bindings are not deleted. Choose a talk trigger outside F9–F12. Keys are temporarily reserved while the addon is loaded.

Direct delivery uses `/yap channel` (default SAY; `sticky` also means SAY in this mode) unless a chat route was selected when you pressed the talk button. Each message is limited to 255 UTF-8 bytes; longer messages produce an error asking for a shorter sentence. Partial, corrupted, or timed-out packets are discarded. A manually focused text field prevents a send. Focus loss cancels helper delivery. This is an ordinary key-input/addon-API path, not memory access or a game-client modification.

Transport sends eight F9/F10 taps per UTF-8 byte with one pause after each byte (default `--packet-delay 0.0025`, about 2.5 ms/byte), while movement continues. If WoW reports **Direct message incomplete**, raise delay: `Start.cmd --packet-delay 0.004`. If the client drops input, the checksum rejects the message rather than posting broken text. SendChatMessage restrictions vary by client; a blocked call is reported in-game. We cannot validate the WoW Forever beta from automated tests. If it rejects direct sends, report the in-game error; the helper never silently falls back to opening chat.

`--delivery chat` explicitly restores the legacy method, which opens chat and may interrupt movement. On Windows that legacy method briefly suppresses physical key-downs during typing to prevent WASD appearing in the message.
