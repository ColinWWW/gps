# Development

[Back to WoWYap](../README.md)

## Run from source

Use Python 3.12 or 3.13, or uv. On Windows, `Start.cmd` creates the environment when needed. The PowerShell entry points are `run-helper.ps1` and `install.ps1`. If an executable is beside Start, it takes precedence over the Python source.

On macOS/Linux, `install.sh` prepares the environment and `run-helper.sh` launches the helper. These launchers are provided, but live integration on those platforms is not validated. Pass `--wow-dir` for nonstandard client locations.

## Tests

From the repository root, in a virtual environment:

```sh
python -m pip install ./helper lupa
python -m unittest discover -s tests -v
```

Tests use a dummy keyboard backend and mock audio. They exercise routing, modifier timing, key releases, focus cancellation, settings migration, addon sync, native Windows input layouts, and the Python-to-Lua packet round trip. They do not send real input or replace in-game testing.

## Windows packaging

The [Build Windows helper workflow](https://github.com/ColinWWW/gps/actions/workflows/windows-helper.yml) runs tests, builds with PyInstaller, and bundles the addon, launchers, sample configuration, and documentation into **WoWYap-Windows**.

A green workflow run is required before its artifact is ready. Keep the executable and dependency directories together. For changes to delivery, test inside WoW while moving and while using modifier-based routes.

## Layout

| Path | Contents |
| --- | --- |
| `addon/WoWYap/WoWYap.lua` | Settings, bindings, indicator, and macro backup |
| `addon/WoWYap/Transport.lua` | Packet validation and chat delivery |
| `helper/gamepadspeak_helper.py` | Audio, recognition, input monitoring, installation, and transport |
| `tests/` | Python and Lua regression tests |
| `docs/` | User troubleshooting and development notes |

The helper module and console entry point retain their original internal name for launcher/package compatibility. User-facing branding is WoWYap. Legacy SavedVariables and macro names remain supported for migration.

## Direct transport

Protocol v2 is `GP`, version, payload length, destination byte, UTF-8 payload, and a two-byte rolling checksum. Payloads are limited to 255 UTF-8 bytes. F11 starts a packet, F9/F10 carry bits, and F12 validates and attempts the send from a key-binding event. The addon resolves General by name at send time instead of assuming channel 1.

On Windows, the helper caches scan codes and batches each byte's 16 down/up events into one SendInput call. It checks the verified foreground window before each batch. The default byte pause is 2.5 ms; `--key-hold` enables individually held keys for clients that need them. Neither direct path manipulates movement keys or opens chat.

A 100-byte message has 267.5 ms of scheduled byte pacing at defaults. That is not end-to-end latency: transcription, OS scheduling, and game processing add time. The helper logs transcription, delivery, and total processing timings. It receives no acknowledgment from WoW.

Local model inference runs through faster-whisper/CTranslate2. `base.en` on CPU with int8 is the default. CUDA is optional and requires its libraries; it is not needed for the default setup.

## Scope of changes

Preserve the packet version unless both ends are updated together. Keep saved-binding and legacy-name compatibility in mind when renaming files or fields. Do not commit personal WoWYap.ini files, virtual environments, model downloads, or generated builds.
