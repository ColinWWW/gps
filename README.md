# WoWYap

**Hold a button. Speak. Release to send to WoW chat.**

WoWYap pairs a WoW addon with a local speech-recognition helper. Direct delivery keeps the chat box closed so you can keep moving while your message sends.

- Configure keyboard, mouse, or controller triggers in game.
- Assign different buttons to Say, General, Guild, and other chats.
- Transcribe locally with Whisper; audio is not uploaded.
- Start on Windows by double-clicking `Start.cmd`.

Targets **WoW Forever, Interface 16001**. Other WoW clients have not been validated.

## Download and start

1. Open [Windows builds](https://github.com/ColinWWW/gps/actions/workflows/windows-helper.yml), select a successful run for the latest `main` commit, and download **WoWYap-Windows** under Artifacts. GitHub may require sign-in.
2. Extract the whole archive. Keep `WoWYap.exe`, its dependency folders, and `addon` together.
3. If WoW is in a custom location, copy [WoWYap.ini.example](WoWYap.ini.example) to `WoWYap.ini` and set `wow_dir` to your client folder, such as `D:\Games\World of Warcraft\_classic_beta_`.
4. Double-click **Start.cmd**. It installs or updates the addon and launches the helper. The first model download takes extra time.
5. Open WoW, enable **WoWYap**, and run `/reload`. If the helper exited while waiting for the initial setup, run **Start.cmd** again. Wait for **Ready** before speaking.

Keep the helper running while you play. Open **`/yap`** for settings; **F8** is the initial talk key. Hold your chosen button to record, then release it to send.

| Launcher | Purpose |
| --- | --- |
| `Start.cmd` | Install/update the addon and run the helper; use this normally |
| `Install.cmd` | Install/update the addon only; not required before Start |
| `Check.cmd` | Show microphone, settings, and WoW-path diagnostics |

## Chat bindings

In `/yap settings`, choose **Mouse4=Say, Shift+Mouse4=General, Mouse5=Guild**, or run `/yap routes mouse`.

| Hold | Destination with the mouse preset |
| --- | --- |
| Mouse4 | Say |
| Shift + Mouse4 | General |
| Mouse5 | Guild |

Hold the modifier before pressing the mouse button. The destination stays fixed for that recording, even if you release Shift first.

For a custom binding, use `/yap route SHIFT-BUTTON5 party`, then `/reload`. Supported destinations are `say`, `general`, `guild`, `party`, `raid`, `yell`, `officer`, and `instance`. Use `clear` as the destination to remove a binding.

**Keep F9–F12 and their modifier combinations unbound**; WoWYap reserves them for delivery. Existing game actions on your talk buttons still fire. General must be joined; `/yap general <name>` selects its localized channel name.

## Recognition model

The default is **`base.en`**, running in English on the CPU with `int8` compute. No CUDA installation is needed.

**`tiny.en` may be faster, but less accurate.** To choose a model, set it under `[wowyap]` in `WoWYap.ini` and restart the helper:

```ini
[wowyap]
model = base.en
```

An existing explicit `model` setting overrides the default. To try the faster option, change that line to `model = tiny.en`. Lines starting with `#` are comments.

## Update

Stop the helper, extract the latest successful Windows build into a new folder, and copy your **WoWYap.ini** into it. Run **Start.cmd**, then `/reload` in WoW. The saved in-game bindings stay in WoW's settings.

For a source checkout, see the [development guide](docs/development.md). Avoid mixing a source update with an older executable: `Start.cmd` launches the executable when one is present.

## Help and project information

- [Troubleshooting and settings](docs/troubleshooting.md)
- [Development, tests, and transport](docs/development.md)
- [Changelog](CHANGELOG.md)
- [Report a bug](https://github.com/ColinWWW/gps/issues)

Based on [kubeden/gps](https://github.com/kubeden/gps). Speech recognition uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [Whisper](https://github.com/openai/whisper).
