# Showcase video, part B: Remotion scenes and edit (personal-website) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Executes in:** `olaheavy-dev/personal-website`, on a branch from `origin/main` (in a worktree: the founder's checkout may be on another branch). Follow that repo's `AGENTS.md`, `make check` and decisions. This plan is kept in FastPilot next to the design; personal-website#135 links to it.

**Goal:** One Remotion project in `tools/explainers/` that turns part A's footage, narration and manifest into (1) the full FastPilot demo, 3 to 4 minutes, narrated, and (2) a 15 to 30 second silent, captioned website cut, both in the site's visual system.

**Architecture:** A separate pnpm workspace package `tools/explainers` (development only, never imported by `src/` or built by Next.js). It reads `manifest.json` (part A, Task 3) and the site's `src/styles/tokens.css`, draws the two explainer scenes as Remotion compositions, and renders `FastPilotDemo` and `FastPilotCut` with `@remotion/cli`.

**Tech Stack:** Remotion (React, TypeScript), Vitest (the repo's test runner), FFmpeg (bundled with Remotion's renderer).

**Spec:** FastPilot `docs/superpowers/specs/2026-11-26-showcase-video-design.md`; personal-website#135 (owner approved Remotion as a development-only tool, 27 Oct 2026).

## Global Constraints

- **Decision 0014: no em dash, en dash or spaced hyphen between words** in anything public: captions, copy, comments, commits, PR text. Write "3 to 4 minutes", not a dash range. `scripts/check-dashes.mjs` runs in `make check`.
- Remotion is development only: listed in decision 0012's pre-approved list and `docs/references/third-party.md` as such (owner-merge PR, Task 1). Nothing under `tools/explainers/` ships to visitors or enters the Next.js build.
- Licence: Remotion is free for individuals including commercial use; a company licence is needed only for for-profit organisations with more than 3 employees (checked 27 Oct 2026, #135). The owner uses it as an individual.
- Colours and fonts come from `src/styles/tokens.css` (lilac `#CDB8FF` and teal `#1FA59A` are fills with ink text on top, never text on paper). Display font Bricolage, body Geist, labels Geist Mono.
- The full demo shows "Narration is AI-generated" on every frame. The website cut is silent with captions.
- Claims policy (decision 0005): every number on screen has a source; the shot list and callout copy are approved by the owner before the final render.
- Output for the site: MP4 (H.264) and WebM plus a poster, self-hosted (CSP `media-src 'self'`, `frame-src 'none'`), inside `pnpm budget`.

## Review Focus

1. **A manifest from an older recording** (`version` other than 1, a scene missing its audio file): rendering must stop with the scene named. Pinned in Task 2 (`loadManifest` tests).
2. **A caption line too long for the frame at 1080p and in the 9:16 crop:** captions must wrap and split, never overflow. Pinned in Task 2 (`captionChunks` tests).
3. **Narration longer than its footage window** (a re-recorded scene): the edit must freeze the last frame, not cut the voice. Pinned in Task 4 (`sceneTimeline` test).
4. **Dark-mode tokens picked by mistake:** the video uses the light palette only. Pinned in Task 2 (`readTokens` test reads `:root`, not `[data-theme="dark"]`).
5. **The AI-narration label missing on a frame** (for example during an explainer scene): Pinned in Task 4 (`FastPilotDemo` renders the label in its root layer, test on three frames).

---

### Task 1: Approve Remotion as a development-only tool (owner merge)

**Files:** Modify `docs/decisions/0012-dependencies-and-pre-approved-packages.md` (add `remotion`, `@remotion/cli`, `@remotion/media-utils`: development only, `tools/explainers/` only, licence note), `docs/references/third-party.md`.

- [ ] **Step 1:** Edit both files; cite #135 and the 26 Nov route decision. **Step 2:** `make check` passes (dashes check included). **Step 3:** Commit, PR, label for owner merge. Later tasks wait for this merge.

### Task 2: Workspace package, manifest loader, tokens, captions

**Files:**
- Create: `tools/explainers/package.json` (private, `remotion` and `@remotion/cli` pinned to a release at least 7 days old), `tools/explainers/tsconfig.json`, `tools/explainers/src/manifest.ts`, `tools/explainers/src/tokens.ts`, `tools/explainers/src/captions.ts`, tests beside them (`*.test.ts`)
- Modify: `pnpm-workspace.yaml` (add `packages: ["tools/explainers"]`), `.gitignore` (`tools/explainers/public/footage/`, `tools/explainers/out/`), the budget scripts' ignore list if they scan `tools/`

**Interfaces:**
- Produces:
  - `type Scene = { name: string; kind: "footage" | "explainer"; start: number | null; end: number | null; done: number | null; audio: string; seconds: number; text: string; caption: string }` (`done`: when the page showed the scene finished, for speeding up a long wait after the line ends, labelled, as Foresight did; `caption`: what to show, which can differ from the spoken `text`, for example a web address. Both added after the part A review, 26 Nov 2026)
  - `type Manifest = { version: 1; narration: "ai-generated"; recorded: string; url: string; video: string; scenes: Scene[] }`
  - `loadManifest(json: unknown, files: Set<string>): Manifest` (throws `Error` naming the scene or field)
  - `readTokens(css: string): { paper: string; ink: string; lilac: string; teal: string; tealText: string }` (from `:root` only)
  - `captionChunks(text: string, seconds: number, maxChars = 42): { text: string; from: number; to: number }[]`

- [ ] **Step 1: Write the failing tests:** `loadManifest` rejects version 2, a footage scene with `start: null`, and a missing audio file (message names the scene); `readTokens` returns `#faf8f5` for paper from a CSS sample that also has a dark block; captions come from `scene.caption`, never `scene.text`; `captionChunks` splits a 120-character line into chunks of at most 42 characters, covers `0..seconds` with no gaps, and never contains `–` or `—`.
- [ ] **Step 2:** `pnpm --filter explainers test` FAILS. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `tools/explainers: manifest, tokens and captions (#135)`.

### Task 3: The two explainer scenes

**Files:** Create `tools/explainers/src/scenes/RetrievalScene.tsx`, `tools/explainers/src/scenes/RunnerScene.tsx`, `tools/explainers/src/Root.tsx` (registers each scene as its own composition for preview), tests.

**Interfaces:**
- Consumes: `readTokens`, `Scene` (Task 2).
- Produces: `<RetrievalScene scene={Scene} tokens={…} />`, `<RunnerScene scene={Scene} tokens={…} />`, each lasting `Math.ceil(scene.seconds * fps)` frames.

- [ ] **Step 1: Write the failing tests:** each scene's duration helper returns `Math.ceil(9.8 * 30) = 294` frames for a 9.8 s line at 30 fps; each scene's step labels (from a constant list) contain no dash between words.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. Retrieval: question → hybrid search (dense + BM25) → rerank → grounded answer with citations, one step lit at a time. Runner: visitor's code → isolated runner (no network, time and memory limits, processes and files removed after each run) → output. Copy for labels comes from FastPilot's `wiki/component-architecture.md`; the owner approves it before the final render.
- [ ] **Step 4:** PASS; `pnpm --filter explainers exec remotion studio` shows both. **Step 5:** Commit.

### Task 4: The edit: `FastPilotDemo` and `FastPilotCut`

**Files:** Create `tools/explainers/src/compositions/FastPilotDemo.tsx`, `tools/explainers/src/compositions/FastPilotCut.tsx`, `tools/explainers/src/timeline.ts`, `tools/explainers/cuts/fastpilot.json` (the cut's scene picks and caption copy), render scripts in `package.json` (`render:fastpilot-demo`, `render:fastpilot-cut`), tests.

**Interfaces:**
- Consumes: Tasks 2 and 3; footage and audio copied into `tools/explainers/public/footage/fastpilot/` (git-ignored).
- Produces: `sceneTimeline(m: Manifest, fps: number): { name: string; from: number; frames: number; freezeFrames: number }[]` and the rendered files `out/fastpilot-demo.mp4`, `out/fastpilot-cut.mp4`, `out/fastpilot-cut.webm`, `out/fastpilot-cut-poster.jpg`.

- [ ] **Step 1: Write the failing tests:** `sceneTimeline` gives a footage scene with a 6.0 s window and a 7.5 s line `freezeFrames = 45` at 30 fps; scenes follow the manifest order with no gaps; the cut's total from `cuts/fastpilot.json` is between 15 and 30 seconds; `FastPilotDemo`'s element tree (render the component function with a fixed manifest and inspect the returned elements) has `<NarrationLabel text="Narration is AI-generated" />` as a direct child of the root `<AbsoluteFill>`, outside every `<Sequence>`, so it shows on every frame. Manual check in Step 4: `remotion still` at frame 0, the first explainer frame and the last frame each shows the label.
- [ ] **Step 2:** FAIL. **Step 3:** Implement: footage via `<OffthreadVideo>` trimmed to each window, explainer scenes in between, each scene's WAV via `<Audio>`, captions from `captionChunks`, the label fixed in the root layer. The cut: silent, captions only, scenes from `cuts/fastpilot.json`.
- [ ] **Step 4:** PASS; render both. **Step 5:** Owner reviews the shot list, captions and both renders (claims policy). **Step 6:** Commit code only (not renders).

### Task 5: Hand the files over

- [ ] **Step 1:** Copy `out/fastpilot-demo.mp4` to FastPilot `docs/assets/demo/fastpilot-demo.mp4` (part A Task 4 makes the GIF and viewer notes there).
- [ ] **Step 2:** Website cut: hand to #161 stage 2 (poster, lazy, tap to play, pause control, captions, reduced motion shows the poster and a text summary), checked by `pnpm budget`.
- [ ] **Step 3:** `make check`; docs: a short `tools/explainers/README.md` (how to render, the licence note, never commit footage). Commit, PR.
