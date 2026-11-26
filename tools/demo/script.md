# FastPilot demo narration

One `## <scene> (footage|explainer)` section per beat, read in a cloned voice by `narrate.py`.
Footage scenes are recorded by `walkthrough.py`; explainer scenes are drawn in Remotion (part B of
the plan). A blank line inside a scene is a short pause. `<!-- source: … -->` comments say where a
fact comes from and are never read aloud. Draft: the founder approves the wording before recording.

## 01-open (footage)
This is FastPilot, a learning companion for FastAPI. You can ask it, watch it build, and practise, and everything it says comes from FastAPI's own documentation.

## 02-ask (footage)
Let's ask it how to add JWT authentication to a FastAPI app. The answer streams in as it's written.

## 03-sources (footage)
Every claim carries a citation. The sources under the answer link back to the exact pages it used, so you can check it rather than trust it.

## 04-retrieval (explainer)
Behind that answer, FastPilot searches the docs two ways at once: by meaning, and by exact words. <!-- source: wiki/component-architecture.md, hybrid dense + BM25 with RRF fusion -->

Then a reranker picks the ten passages that best fit the question. In testing, reranking alone was worth twenty-one points. <!-- source: wiki/component-architecture.md, "+21 points" from the 4-way bake-off -->

The model answers only from those passages.

## 05-agent (footage)
In Agent mode, you watch it work. It plans an endpoint, writes the code, runs it, and shows you each step and the output.

## 06-playground (footage)
In the Playground, the code is yours. Change it, run it, and if it fails, ask for a fix.

## 07-runner (explainer)
Your code runs in a separate runner with no network and no keys. <!-- source: wiki/component-architecture.md, runner container: network_mode none, no env_file -->

Each run gets its own user, limited memory and processes, and afterwards everything it left behind is removed. <!-- source: wiki/component-architecture.md, slots, 256 MB per process, clean-up after every run -->

## 08-close (footage)
Ask it, watch it, practise. FastPilot is live at fastpilot dot olaheavy dot dev, and the code is on GitHub.
