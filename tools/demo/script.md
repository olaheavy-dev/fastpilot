# FastPilot demo narration

One `## <scene> (footage|explainer)` section per beat, read in a cloned voice by `narrate.py`.
Footage scenes are recorded by `walkthrough.py`; explainer scenes are drawn in Remotion (part B of
the plan). A blank line inside a scene is a short pause. `<!-- source: … -->` comments say where a
fact comes from and are never read aloud; a `<!-- caption: … -->` comment replaces the caption when it
should differ from the spoken words (a web address).

Approved by the founder on 26 Nov 2026 ("script aproved"); a later change to a line needs approval again.
Changed on 26 Nov 2026, ported from the earlier Loom demo (`video-transcript.md`) and Foresight's script
(founder's choice: all four ports): the problem-first opener, the follow-up scene, the Agent's
self-correction and the closing tagline with the stack. These changed lines await the founder's approval.

## 01-open (footage)
Learning FastAPI means jumping between the docs, the project template and GitHub threads, and all that tab-switching makes learning feel fragmented. <!-- source: video-transcript.md, Problem Setup -->

FastPilot brings them into one place. Ask it, watch it build, and practise, and everything it says comes from FastAPI's documentation, its project template and its GitHub community. <!-- source: docs/scoping.md, four corpus sources: docs, full-stack template, GitHub issues, GitHub discussions -->

## 02-ask (footage)
Let's ask it how to add JWT authentication to a FastAPI app. The answer streams in as it's written.

## 03-sources (footage)
Every claim carries a citation. The sources under the answer link back to the exact pages it used, so you can check it rather than trust it.

## 04-followup (footage)
Now a vague follow-up: can I make it expire? On its own, that could mean anything. FastPilot remembers the conversation and rewrites it into a full question about JWT expiry. You can see what it searched for, just above the sources. <!-- source: frontend/app.py, the "searched as" note; app/services/conversation.py, conditional rewrite -->

## 05-retrieval (explainer)
Here's how it's built. A FastAPI backend streams each answer to this Streamlit app as it's written. <!-- source: wiki/overview.md, FastAPI backend, Streamlit frontend, SSE streaming -->

Behind every answer, FastPilot searches the docs two ways at once in Qdrant: by meaning, and by exact words. <!-- source: wiki/component-architecture.md, hybrid dense + BM25 with RRF fusion -->

Then a Voyage reranker picks the ten passages that best fit the question. In our tests, reranking nearly doubled the score. <!-- source: docs/retrieval-strategy.md, Reranking: 43 points vs 22 (rerank_top_k=10, app/config.py) -->

Gemini answers only from those passages. <!-- source: app/config.py, llm_model gemini-3.8-flash -->

## 06-agent (footage)
In Agent mode, you watch it work. It plans an endpoint, writes the code and runs it, showing you each step. If the first try fails, it reads the error, fixes the code, and runs it again. <!-- source: video-transcript.md, Query 3; tests/test_visual.py, test_agent_flow_shows_self_correction -->

## 07-playground (footage)
In the Playground, the code is yours. Change it, run it, and if it fails, ask for a fix.

## 08-runner (explainer)
Your code runs in a separate runner with no network and no keys. <!-- source: wiki/component-architecture.md, runner container: network_mode none, no env_file -->

Runs use separate users, so two visitors can't see each other's files. Memory and processes are limited, and after every run everything it left behind is removed. <!-- source: wiki/component-architecture.md, two slot users, 256 MB per process, clean-up after every run -->

## 09-close (footage)
Ask it, watch it, practise. FastPilot: learn FastAPI, fast. <!-- source: video-transcript.md, product tagline -->
