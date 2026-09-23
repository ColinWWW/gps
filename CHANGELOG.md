# Changelog

## Unreleased

- Reorganize setup, troubleshooting, and development documentation.
- Use `/yap` consistently in help text while keeping `/gps` as an alias.
- Keep generated build files out of version control.

## 0.5.2

- Default to `base.en`; document `tiny.en` as a potentially faster, less accurate option.
- Hide the Receiving indicator and remove the duplicate Sent transcript from chat.

## 0.5.1

- Batch Windows input by byte and remove default per-bit holds.
- Add separate transcription and delivery timing logs and compatibility pacing.
- Fix modifier snapshots, recording ownership, and keyboard triggers alongside mouse routes.
- Fix Windows handle declarations, focus checks, settings migration, and addon content comparisons.
- Validate reserved route keys and report settings that exceed the macro backup limit.
- Correct Windows launcher exit handling.

## 0.5.0

- Rename the project to WoWYap and display Yapping while recording.
- Add direct delivery with per-chat routes and double-click Windows launchers.
- Carry forward hold-to-talk, configurable triggers, softer recording cues, and local recognition from the GamepadSpeak fork.
