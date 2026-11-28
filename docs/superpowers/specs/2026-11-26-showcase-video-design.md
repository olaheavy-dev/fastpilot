# Showcase video: one recording route for #20 and personal-website#135 (design)

**Date:** 26 Nov 2026. **Size:** a short design. **Issues:** fastpilot#20 (demo and explainer video), personal-website#135 (Lab motion explainers), personal-website#161 (case-study page, stage 2 embeds the video).

## Why

#20 and #135 each planned a FastPilot explainer video with different tools (OpenScreen and Remotion; Playwright and Remotion). One route means one set of footage, one style, and a video that can be re-made when the app changes (Monaco upgrade #69, restyles).

## Founder's choices (26 Nov 2026)

- Route: **"Remotion for everything"** (over Foresight's HTML-card route, recommended, and captions only): Remotion makes the explainer scenes and does the edit.
- Where Remotion lives: **"personal-website tools/explainers/ (Recommended)"**: already approved there as a development-only tool (#135); FastPilot gets no new package.
- Voice: **"Cloned voice, labelled (Recommended)"**: as in Foresight, Chatterbox on the Mac, and every frame says the narration is AI-generated. The website cut stays silent, with captions.
- OpenScreen is dropped.

## The route

```text
FastPilot repo                                   personal-website repo (tools/explainers/, never shipped)
  tools/demo/script.md      narration, one ## per scene
  tools/demo/narrate.py     Chatterbox, cloned voice  -> out/audio/<scene>.wav + durations.json
  e2e walkthrough (Playwright, live site)            -> raw footage .webm + scene marks .log
        (holds each scene until its line is said)
                     \___________________________________   Remotion project (one per Lab product, FastPilot first)
                                                          ->   explainer scenes: retrieval pipeline,
                                                               runner containment (the visitor's code)
                                                               the edit: footage + scenes + voice + captions
                                                          ->   1. full demo, 3-4 min, narrated (MP4)
                                                               2. website cut, 15-30 s, silent, captioned (MP4 + WebM + poster)
FastPilot repo
  docs/assets/demo/  full demo MP4, viewer notes, README GIF (FFmpeg from the full demo)
personal-website
  #161 stage 2 embeds the website cut (self-hosted, lazy, tap to play)
```

## Goals

- One capture serves both outputs; re-recording needs no manual steps.
- Every number shown has a source (claims policy), and nothing implies a feature is live unless it is.
- The narration is labelled AI-generated on every frame; the voice recording is never committed.

## Non-goals

- No Remotion, Node or video tooling in FastPilot's images or its Python environment.
- No YouTube or third-party player (the website's CSP has `frame-src 'none'`).

## Constraints

- Agent and Playground must be on where the walkthrough records. If the founder switches them off on the live site (decision after the 48-hour check, 26 Nov), record against a local build and say so in the viewer notes.
- Each live take makes real Gemini and Voyage calls (a few cents) and creates Opik traces; the walkthrough's questions are labelled as a demo.
- Narration tools (`narrate.py`) are copied from Foresight into FastPilot `tools/demo/` with their own environment, as in Foresight (`docs/demo-video.md` there). Extract a shared tool when a third project needs it.
- Shot list and callout copy are approved by the founder before rendering (#135).

## Left to the builder (the plans)

- The scene list and script (draft from Chat → Agent → Playground, plus the two explainer scenes).
- How Remotion reads the footage and scene marks (static files, or a small manifest).
- The README GIF's length and size.

## Order

1. FastPilot: walkthrough spec, script and narration (#20). Needs tonight's Agent/Playground decision.
2. personal-website: the Remotion project and both renders (#135), founder approves the shot list first.
3. FastPilot: export the full demo, viewer notes and README GIF (#20). personal-website: embed the cut (#161 stage 2).
