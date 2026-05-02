# PersoWhisper

Minimal SuperWhisper-style dictation for macOS. Tap **right Command** to start
recording, tap it again to stop — the audio is transcribed locally with
[whisperx](https://github.com/m-bain/whisperX) (`large-v3`, English-only,
transcribe-only, no alignment, no diarization — tuned for latency) and pasted
into the focused text field.

## Layout

```
src/                # package — `python -m src`
├── __init__.py
├── __main__.py     # entry point
├── app.py          # PersoWhisperApp + main()
├── config.py       # all tunable constants
├── controller.py   # orchestrates record → transcribe → paste
├── hotkey.py       # right-Cmd tap detection
├── overlay.py      # floating waveform / progress panel
├── paste.py        # clipboard + osascript Cmd+V
├── recorder.py     # mic capture + RMS levels
├── state.py        # IDLE / RECORDING / TRANSCRIBING enum
├── system.py       # play / notify / accessibility-trust helpers
└── transcribe.py   # runs the whisperx CLI
run.sh              # wrapper that launches the venv
requirements.txt    # extra pip deps (pynput, sounddevice, soundfile, rumps)
whisperx-env/       # existing Python 3.12 venv with whisperx already installed
```

## One-time setup

1. **Install the extra Python deps into the existing venv:**
   ```bash
   cd /Users/borisploix/Projects/Perso/PersoWhisper
   ./whisperx-env/bin/pip install -r requirements.txt
   ```

2. **Grant macOS permissions** to whichever terminal app launches `run.sh`
   (Terminal.app, iTerm2, VS Code's integrated terminal, etc.). Open
   System Settings → Privacy & Security and enable the parent app under:
   - **Accessibility** — required to listen globally for the right-Cmd tap.
   - **Input Monitoring** — same reason; macOS sometimes asks separately.
   - **Microphone** — prompted automatically the first time you record.
   - **Automation → System Events** — required so `osascript` can send the
     synthetic Cmd+V paste. macOS prompts for this the first time the
     script tries to paste; click "OK". You can also enable it manually
     under Privacy & Security → Automation.

   After granting any of these, **fully quit and restart the terminal app**
   — macOS only re-reads the permission list on a fresh process.

   Why this design: paste is dispatched via `osascript "tell application
   \"System Events\" to keystroke \"v\" using {command down}"`. Doing it
   through System Events keeps the synth in a separate process — recent
   macOS will SIGTRAP a Python process that calls `CGEventPost` without
   the right entitlements, so we explicitly avoid that path.

## Run

```bash
./run.sh
```

## Build as a Mac app (optional)

To launch from Finder / Spotlight / Launchpad with a real icon and the bundle's
own TCC permission entries (so you don't have to re-grant Accessibility every
time you switch terminal apps):

```bash
./build_app.sh
```

This produces `dist/PersoWhisper.app/` (built with py2app in alias mode — no
copy of site-packages, the bundle uses the live `whisperx-env`) and symlinks
it into `/Applications`. The bundle's launcher is a Mach-O binary signed with
`com.borisploix.persowhisper` that embeds Python in-process; this is required
so macOS TCC actually attributes Accessibility/Microphone grants to the app
rather than to Homebrew's Python framework.

Then, in **System Settings → Privacy & Security → Accessibility**, click `+`,
add `/Applications/PersoWhisper.app`, and enable it. Microphone access is
prompted on first recording.

A `🎙` icon appears in the menu bar. While the script is running:

| Action | Effect |
|---|---|
| Tap right Cmd (idle) | Start recording. Icon → 🔴, *Tink* sound. |
| Tap right Cmd (recording) | Stop recording. Icon → ⏳, *Pop* sound. whisperx runs (~10–30 s for short clips on `large-v3`), then the transcript pastes into the focused field. *Glass* sound when done; icon back to 🎙. |
| Tap right Cmd (transcribing) | Ignored. *Funk* sound. |
| Hold right Cmd / use Cmd+something | Untouched. The hotkey only fires on a clean tap < 800 ms with no other key in between. |
| Menu bar → Quit | Clean exit. |

Stop with `Ctrl+C` in the terminal or via the menu's Quit item.

## Tweaking

The configurable knobs live as module-level constants near the top of
[`persowhisper.py`](./persowhisper.py):

- `HOTKEY` — default `keyboard.Key.cmd_r`. Switch to `Key.cmd_l`,
  `Key.alt_r`, `Key.f13`, etc.
- `WHISPERX_MODEL` — default `large-v3`. Use `medium`, `small`, etc. for
  faster transcription.
- `TAP_MAX_HOLD_MS`, `MIN_RECORDING_SEC`, `MAX_RECORDING_SEC`,
  `PASTE_RESTORE_DELAY_SEC` — timing tuning.

## Troubleshooting

- **No icon in the menu bar** — `rumps` failed; check the terminal output.
- **Tap doesn't trigger anything** — usually missing Accessibility / Input
  Monitoring permission for the parent terminal app. Re-grant and relaunch.
- **Recording starts but transcript never pastes** — check terminal stderr
  for the whisperx command and its error tail. On failure the WAV is kept
  and its path printed for replay.
- **Wrong app receives the paste** — make sure the cursor is in a text
  field before tapping right Cmd to *stop* recording; focus is captured at
  paste time, not at start time.
- **Pasting fails silently** — your previous Cmd is still being held by
  pynput from the start tap (rare). Wait a beat and try again.
