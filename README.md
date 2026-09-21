# GamepadSpeak — WoW hold-to-talk

Based on [kubeden/gps](https://github.com/kubeden/gps). This version adds an **in-game settings panel**, keyboard triggers, and **hold-to-talk** for keyboard and controller input.

**Hold F8 → speak → release F8 → local Whisper transcription → WoW chat.**

This is still a WoW addon **plus an external helper**. WoW addons cannot capture the microphone or run Whisper themselves. The helper must remain running. This source targets the original WoW Forever client (Interface 16001); other Retail/Classic versions have not been validated.

## Windows setup

1. Install Python 3.12 or 3.13 if you are running from source.
2. Close WoW, extract this repository, and run `install.ps1` in PowerShell. If necessary, set `$env:WOW_DIR` to your WoW `_classic_beta_` directory first.
3. Enable GamepadSpeak in WoW and run `/gps` (or `/gps settings`). The panel is also under **Options → AddOns → GamepadSpeak** where supported.
4. F8 is the default. Click **Change keyboard key**, then press your desired key, optionally with Ctrl, Shift, or Alt. **Selecting the key saves it and reloads the UI.** Escape cancels. The helper reads the saved setting within about two seconds. If the client refuses the automatic reload, type `/reload`.
5. Run `run-helper.ps1`. On first launch it downloads the selected Whisper model; wait for **Ready** before speaking.
6. With WoW focused, hold your trigger while speaking, then release. The helper opens chat, types the result and sends it with Enter.

Supported keyboard keys: F1–F20, A–Z, 0–9, Insert/Delete, Home/End, Page Up/Down, and arrow keys, with optional Ctrl/Shift/Alt. Use an unused key: existing game actions are not unbound. On Windows, select **Use Mouse4** or **Use Mouse5** in `/gps settings` (or run `/gps mouse4` / `/gps mouse5`). These are the physical back/forward side buttons; mouse software must not remap them to keyboard keys. Selecting one saves and reloads the UI. Existing mouse bindings still fire. Release modifiers too before delivery.

For a controller, click **Change controller button**, or use `/gps gamepad`. Controller buttons and trigger axes now also use hold/release instead of toggle. The original gamepad chat-closing workaround remains enabled for controller triggers; keyboard triggers use normal Enter-to-send.

Recording cues are now quieter, lower-pitched single tones with smooth fades. Use `--silent` to disable them entirely.

## Options and troubleshooting

- `/gps setup`: choose a keyboard key and reload.
- `/gps status`: inspect settings.
- `run-helper.ps1 --check`: inspect microphone, settings path and foreground detection.
- `run-helper.ps1 --input-device "Microphone name"`: select a microphone.
- `run-helper.ps1 --model small --language en`: choose recognition settings.
- `run-helper.ps1 --wow-dir "C:\path\to\_classic_beta_"`: point the helper at the same WoW installation as the addon.
- `run-helper.ps1 --button F9`: temporary helper-only override; normally use the in-game setting so the indicator agrees.

Recording starts only when WoW is detected in the foreground. Leaving WoW cancels the recording or pending delivery. Failure to identify the foreground window also prevents recording. Recordings are capped at 60 seconds by default. If the trigger/modifiers remain held for five seconds after transcription, delivery is discarded. Empty speech, microphone and transcription failures return the helper to idle.

The addon indicator is approximate: it cannot receive success/failure acknowledgments from the external helper. It may show “Transcribing” briefly after cancelled or empty speech. The original beta's settings-macro backup is preserved; do not edit the `GPSpeak` macro.

The helper records/transcribes locally. Model downloads need internet; audio is not uploaded. Transcripts appear in the helper console and are sent to WoW chat.

## Windows executable build

The **Build Windows helper** GitHub Actions workflow builds a console `.exe` and its dependency folder. Run it from the repository's Actions tab, then download the `GamepadSpeak-Windows` artifact. Keep the executable with all files in its folder; copy `addon/GamepadSpeak` into WoW's `Interface/AddOns` directory. The `.exe` accepts the same helper options, including `--wow-dir`.

A successful workflow run is required before claiming a working executable. Live microphone capture, key delivery, and addon behavior must still be checked inside WoW on Windows.

## Development checks

Install helper dependencies and `lupa`, then run:

```powershell
python -m unittest discover -s tests -v
```

Tests cover key repeats, short controller holds, modifier release order, focus restrictions, error recovery, settings selection/persistence, and the addon recording/release indicator using a stubbed WoW API. They do not replace an in-game integration test.
