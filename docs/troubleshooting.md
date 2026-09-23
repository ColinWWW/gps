# Troubleshooting

[Back to WoWYap](../README.md)

## The helper cannot find WoW

Edit `wow_dir` in `WoWYap.ini` beside `Start.cmd`. Point it to the client folder containing `Interface` and `WTF`, not just the parent World of Warcraft folder.

```ini
[wowyap]
wow_dir = D:\Games\World of Warcraft\_classic_beta_
model = base.en
```

Restart `Start.cmd`. Run `Check.cmd` to check which path and SavedVariables file it is using.

## First launch says the addon needs updating

Start installs the addon before trying to read its settings. In WoW, enable WoWYap, run `/yap status`, then `/reload`. Restart the helper if it exited. Status should show direct delivery is ready.

Both the helper and addon must come from the same build. A packaged executable needs its accompanying dependency folders.

## A key does not work or a message goes to the wrong chat

- Check `/yap status` and the helper's startup binding list.
- Run `/reload` after changing a route so the helper reads the saved settings.
- For mouse buttons, use physical Mouse4/Mouse5; mouse software must not remap them to another key.
- Press Shift/Ctrl/Alt before pressing the talk button to select a modified route.
- Leave F9–F12 and their modifier combinations free. Startup messages identify conflicts.
- Confirm you have access to the destination: General must be joined, and Guild requires guild membership.

Keyboard capture accepts letters, digits, navigation keys, and function keys supported by the client. F9–F12 are reserved; extra function keys above F12 may not be recognized by WoW.

`/gps` remains a compatibility alias for `/yap`. Do not delete the `WoWYap` settings macro: it backs up settings for this beta client. Existing `GPSpeak` backups can be read during migration.

## Recognition is inaccurate or slow

`base.en` is the default. `tiny.en` may transcribe faster with lower accuracy. Set `model` in WoWYap.ini and restart; the first use of a new model downloads it.

Choose a microphone with `Start.cmd --input-device "Microphone name"`. The helper prints separate transcription and delivery timings. Include one `Timing:` line when reporting slowness; it tells us which stage needs attention.

## Direct message incomplete or checksum failed

The addon discards a damaged packet rather than posting garbled text. Try slower input:

```bat
Start.cmd --key-hold 0.001 --packet-delay 0.004
```

To keep those settings, add these lines under `[wowyap]` in WoWYap.ini:

```ini
key_hold = 0.001
packet_delay = 0.004
```

The faster defaults are `key_hold = 0` and `packet_delay = 0.0025`.

Keep messages under 255 UTF-8 bytes; shorter sentences are easiest to send. If a client blocks the chat API, copy the in-game error. Direct mode does not automatically fall back to opening chat.

## Recording or delivery stops

WoWYap requires the same verified WoW window to stay focused. Switching applications cancels recording or pending delivery. A focused text field in WoW prevents a direct send. Recordings are capped at 60 seconds; holding the trigger for five seconds after transcription also cancels delivery.

The indicator can briefly show Transcribing after empty speech or a cancelled recording. It hides when direct delivery begins. There is no Receiving banner or duplicate Sent echo. Check the destination chat for the actual message; the helper's packet log is not a delivery acknowledgment.

## Optional settings

| Option | Effect |
| --- | --- |
| `--silent` | Disable recording sounds |
| `--button F8` | Temporarily override the talk key and ignore saved chat routes |
| `--check` | Show diagnostics |
| `--delivery chat` | Use legacy typing; opens chat and can interrupt movement |
| `--skip-addon-sync` | Leave addon installation to you |

## Reporting a problem

Include the build/commit, WoW client version, relevant `/yap status` output, the last helper log lines, and steps to reproduce. For latency, include the `Timing:` line. State whether you are running from source or using the Windows executable.
