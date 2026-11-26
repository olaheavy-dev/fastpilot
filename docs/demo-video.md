# Demo video: narration, recording and hand-over

FastPilot's showcase video (#20) is made in two parts, by one route ([design](superpowers/specs/2026-11-26-showcase-video-design.md)):

- **Part A, here in FastPilot (`tools/demo/`):** the narration in a cloned voice, a Playwright recording of the live site held to that narration, and `manifest.json`, which ties the two together.
- **Part B, in personal-website (`tools/explainers/`, Remotion):** the two explainer scenes (the retrieval pipeline, and how the runner contains a visitor's code) and the edit. It renders the full narrated demo (3 to 4 minutes) and a 15 to 30 second silent cut for the website ([plan](superpowers/plans/2026-11-26-showcase-video-remotion.md)).

The method comes from Foresight's demo (its `docs/demo-video.md`), which made a 4:37 video this way on 25 Oct 2026.

## The rules

- **Never commit a voice recording or the narration's WAV files.** A short sample is enough for anyone to clone the voice. `tools/demo/voice/`, `tools/demo/out/` and every `.wav` under `tools/demo/` are git-ignored. Only the finished, labelled MP4 is committed (step 5).
- **Every frame of the final video says the narration is AI-generated.** `manifest.json` carries `"narration": "ai-generated"`, and part B draws the label.
- **Every number in the narration has a source.** `script.md` cites it in a `<!-- source: … -->` comment, which is never read aloud.
- **Agent runs are limited to 5 per visitor a day** (reset at midnight UTC), and each take uses one. If the Agent scene stops with "You've used today's 5 Agent runs" in its failure screenshot, record after midnight UTC.
- **Each live take costs a few cents** (two Chat questions with the semantic cache switched off, one Agent run, one Playground run) and leaves Opik traces. The question and the Agent task start with "Demo:", so the traces are easy to spot.
- If Agent or Playground are switched off on the live site, record against a local build (`--url`), and say so in the viewer notes.

## One-time setup (macOS, Apple Silicon)

```bash
brew install ffmpeg
uv venv -p 3.11 tools/demo/.venv
uv pip install -p tools/demo/.venv -r tools/demo/requirements.txt
tools/demo/.venv/bin/python -m playwright install chromium
```

The demo environment is separate from the app's `.venv`. The first narration run downloads the Chatterbox model (1 to 2 GB) from Hugging Face. Chatterbox (Resemble AI, MIT licence) runs on the Mac: neither your recording nor the text leaves the machine, and every output carries Resemble's inaudible watermark.

## 1. Record your voice (once)

Find your microphone's number, then record 20 seconds (here `:2`, the MacBook Pro microphone). The terminal needs microphone access (System Settings → Privacy & Security → Microphone).

```bash
ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | sed -n '/audio devices/,$p'
mkdir -p tools/demo/voice
ffmpeg -y -hide_banner -loglevel error -f avfoundation -i ":2" -t 20 -ac 1 -ar 24000 tools/demo/voice/raw.wav
```

Read any natural paragraph, in the tone you want the narration to have, in a quiet room with the microphone 20 to 30 cm away. Then check the level (a `mean_volume` near −30 dB is good; −91 dB means silence) and clean it up:

```bash
ffmpeg -hide_banner -i tools/demo/voice/raw.wav -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
ffmpeg -y -hide_banner -loglevel error -i tools/demo/voice/raw.wav \
  -af "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,highpass=f=80,loudnorm=I=-18:TP=-2" \
  -ar 24000 -ac 1 tools/demo/voice/reference.wav
```

## 2. Render the narration (before recording)

Edit `tools/demo/script.md` first (the founder approves its wording). Each `## <scene> (footage)` or `(explainer)` section is one beat.

```bash
tools/demo/.venv/bin/python -m tools.demo.narrate --voice tools/demo/voice/reference.wav
tools/demo/.venv/bin/python -m tools.demo.narrate --voice tools/demo/voice/reference.wav --only 02-ask   # one scene again
afplay tools/demo/out/audio/01-open.wav
```

It writes one WAV per scene and `tools/demo/out/audio/durations.json`: each line's length and a hash of its words. If you change a line later, the walkthrough and the manifest name that scene until you render it again with `--only`.

## 3. Record the walkthrough

```bash
tools/demo/.venv/bin/python -m tools.demo.walkthrough            # the live site
tools/demo/.venv/bin/python -m tools.demo.walkthrough --headed   # watch it
```

It refuses to record if `durations.json` is missing a scene or any line changed since it was rendered, and if the script's footage scenes and the recorder's page actions don't match. The voice starts with each scene. Each footage scene waits until the page shows it is done (the answer's "Sources" section, the Agent's "Send to Playground" button, the run's `exit 0` line) and logs that time as `done`, then holds for whatever is left of its line. A wait longer than the line is not held further; part B can speed it up from the `done` time, labelled on screen. Explainer scenes get only a mark: part B draws them. If a scene fails, a full-page screenshot is saved next to the recording. Each take gets its own file names (date and time), so a failed second take never overwrites a good first one.

## 4. Build the manifest

```bash
tools/demo/.venv/bin/python -m tools.demo.manifest \
  --log tools/demo/out/video/walkthrough-<date>-<time>.log --video tools/demo/out/video/walkthrough-<date>-<time>.webm
```

It stops with the scene named if the log and the script disagree, or a line changed since it was rendered. The URL the take recorded (live site or a local build) comes from the log, so a local build is named in the manifest. Hand `tools/demo/out/manifest.json`, the `.webm` and `tools/demo/out/audio/*.wav` to part B (copied into personal-website's git-ignored `tools/explainers/public/footage/fastpilot/`).

## 5. After part B: the files in this repository

Part B's full render goes to `docs/assets/demo/fastpilot-demo.mp4`, with viewer notes in `docs/assets/demo/README.md` (scene guide with times, what's real, what's AI-generated, sources). The README's GIF is cut from it, 8 seconds, kept under 5 MB:

```bash
ffmpeg -ss <start> -t 8 -i docs/assets/demo/fastpilot-demo.mp4 \
  -vf "fps=12,scale=960:-1:flags=lanczos" docs/assets/demo/fastpilot-demo.gif
```
