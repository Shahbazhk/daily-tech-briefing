# Daily YouTube Video Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the daily pipeline so each episode is also turned into a captioned video and uploaded, fully unattended, to the user's YouTube channel/playlist — gated by a new content-safety guardrail on script generation.

**Architecture:** Two new stages (`build_video`, `youtube_publish`) added to `pipeline/run_pipeline.py`'s existing stage-runner, after `synthesize` and after `publish` respectively. Caption timing comes free from Kokoro's own per-chunk synthesis output. Thumbnails are templated (Pillow), not AI-generated. YouTube auth uses a one-time local OAuth consent flow producing a long-lived refresh token stored as a GitHub secret. A new safety-net check in `generate_script.py` gates both the existing app-publish path and the new YouTube path.

**Tech Stack:** Python 3.11, ffmpeg (subtitles/libass), Pillow, google-api-python-client, google-auth-oauthlib, Groq (existing), Kokoro (existing), pytest (new — first test suite in this project).

## Global Constraints

- $0/month; open-weight/free tools only where a choice exists (per BRD Section 14 and the design spec).
- Public GitHub repo → unlimited free Actions minutes; no runtime budget concern.
- ffmpeg is already available on the GitHub-hosted `ubuntu-latest` runner and its packaged build includes libass, so the `subtitles` filter needs no new system package.
- Every pipeline stage script is runnable standalone (`if __name__ == "__main__": main()`), reads its required upstream artifact from `pipeline/data/<name>_<date>.<ext>`, and does `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` before `from common import ...`. New stage scripts must follow this same pattern.
- Use `episode_date()` (UTC `YYYY-MM-DD`) and `ensure_data_dir()` from `pipeline/common.py` as the canonical date-stamp/data-dir helpers — do not reimplement.
- Missing-upstream-artifact stages raise `SystemExit(f"Missing {path} — run <stage> first.")` — new stages follow this same pattern.
- Groq model is configurable via the `GROQ_MODEL` env var (default `llama-3.3-70b-versatile`).
- YouTube uploads MUST set `status.containsSyntheticMedia: true` (verified against current YouTube Data API v3 docs — this is the real field for the AI/altered-content disclosure, added in a 2024+ API revision).
- OAuth scope is `https://www.googleapis.com/auth/youtube` (the broad scope) — NOT `youtube.upload`, because `playlistItems.insert`/`playlistItems.update` require the broader scope per the API docs; `youtube.upload` alone would 403 on the playlist step.
- Video category ID is the standard, stable `"28"` (Science & Technology).
- This project has no existing test suite. Task 1 introduces `pytest` for the first time — used for pure/mockable logic (formatting, mapping, retry/skip decisions). Live, real end-to-end verification via `gh workflow run` + inspecting real output remains how this project validates full runs, consistent with every prior stage of this project — pytest supplements that, it doesn't replace it.
- No placeholders, no invented API fields: every external API call in this plan was checked against current YouTube Data API v3 documentation before writing.

---

### Task 1: Shared `call_groq` helper + content safety guardrails in script generation

**Files:**
- Modify: `pipeline/common.py`
- Modify: `pipeline/scripting/generate_script.py`
- Test: `pipeline/tests/test_common.py`
- Test: `pipeline/tests/test_generate_script_safety.py`

**Interfaces:**
- Produces: `common.call_groq(messages: list[dict], max_tokens: int = 1200) -> str` — moved here from `generate_script.py` so `metadata.py` (Task 6) can reuse it too.
- Produces: `common.DEFAULT_GROQ_MODEL: str = "llama-3.3-70b-versatile"`.
- Produces (in `generate_script.py`): `class ContentSafetyError(Exception)` with `.segment_label` and `.reason` attributes; `check_segment_safety(text: str) -> tuple[bool, str]`.
- Consumes: nothing from earlier tasks (this is the first task).

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/test_common.py`:

```python
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402


def test_call_groq_uses_env_model_and_returns_stripped_content(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("GROQ_MODEL", "custom-model")

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "  hello world  \n"

    with patch("groq.Groq") as MockGroq:
        MockGroq.return_value.chat.completions.create.return_value = fake_response
        result = common.call_groq([{"role": "user", "content": "hi"}], max_tokens=50)

    assert result == "hello world"
    MockGroq.return_value.chat.completions.create.assert_called_once_with(
        model="custom-model",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        max_tokens=50,
    )


def test_call_groq_falls_back_to_default_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    fake_response = MagicMock()
    fake_response.choices[0].message.content = "ok"

    with patch("groq.Groq") as MockGroq:
        MockGroq.return_value.chat.completions.create.return_value = fake_response
        common.call_groq([{"role": "user", "content": "hi"}])

    _, kwargs = MockGroq.return_value.chat.completions.create.call_args
    assert kwargs["model"] == common.DEFAULT_GROQ_MODEL
```

Create `pipeline/tests/test_generate_script_safety.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripting"))
import generate_script  # noqa: E402


def test_check_segment_safety_parses_safe_verdict():
    with patch("generate_script.call_groq", return_value="SAFE"):
        is_safe, reason = generate_script.check_segment_safety("Java 24 shipped a new GC.")
    assert is_safe is True
    assert reason == ""


def test_check_segment_safety_parses_flagged_verdict():
    with patch("generate_script.call_groq", return_value="FLAGGED: contains profanity"):
        is_safe, reason = generate_script.check_segment_safety("some text")
    assert is_safe is False
    assert reason == "FLAGGED: contains profanity"


def test_generate_topic_segment_retries_once_then_raises_if_still_flagged():
    calls = {"n": 0}

    def fake_call_groq(messages, max_tokens=1200):
        calls["n"] += 1
        return f"segment text {calls['n']}"

    with patch("generate_script.call_groq", side_effect=fake_call_groq), \
         patch("generate_script.check_segment_safety", return_value=(False, "FLAGGED: unethical example")):
        try:
            generate_script.generate_topic_segment("Java", [], target_words=300)
            assert False, "expected ContentSafetyError"
        except generate_script.ContentSafetyError as e:
            assert e.segment_label == "Java"
            assert "unethical example" in e.reason

    # 1 generation + 1 safety-retry generation = 2 call_groq calls (length-retry not
    # triggered since word count is fine; only the safety path retries here).
    assert calls["n"] == 2


def test_generate_topic_segment_returns_text_when_safe():
    with patch("generate_script.call_groq", return_value="x " * 300), \
         patch("generate_script.check_segment_safety", return_value=(True, "")):
        result = generate_script.generate_topic_segment("Java", [], target_words=300)
    assert result == "x " * 300
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_common.py tests/test_generate_script_safety.py -v`
Expected: FAIL — `common` has no attribute `call_groq`/`DEFAULT_GROQ_MODEL`; `generate_script` has no attribute `check_segment_safety`/`ContentSafetyError`.

- [ ] **Step 3: Move `call_groq` into `common.py`**

Add to `pipeline/common.py` (after the existing imports, before `_LOGGING_CONFIGURED`):

```python
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def call_groq(messages: list[dict], max_tokens: int = 1200) -> str:
    from groq import Groq

    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.5,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()
```

- [ ] **Step 4: Update `generate_script.py` to use the shared helper and add guardrails**

In `pipeline/scripting/generate_script.py`:

1. Change the import line (currently `from common import ensure_data_dir, episode_date, get_logger`) to:

```python
from common import call_groq, ensure_data_dir, episode_date, get_logger  # noqa: E402
```

2. Delete the `DEFAULT_MODEL = "llama-3.3-70b-versatile"` line and the entire `call_groq` function definition (both now live in `common.py`).

3. Update the module docstring's model-id note (currently ends "...check https://console.groq.com/docs/models and update the default below or set GROQ_MODEL in the environment.") to say "...check https://console.groq.com/docs/models and update `DEFAULT_GROQ_MODEL` in `common.py`, or set `GROQ_MODEL` in the environment." instead — the default no longer lives in this file.

4. Add one bullet to the `Rules:` list in both `SEGMENT_SYSTEM_PROMPT` and `ARCHITECTURE_SYSTEM_PROMPT` (append as the last rule in each):

```
- Never include vulgarity, profanity, or sexual content. Never present an unethical use-case,
  project, or example (e.g. building surveillance tools to spy on people without consent,
  exploit/attack tooling meant to cause harm, discriminatory or privacy-violating systems) as
  something to emulate or admire — if a source item is fundamentally about such a use-case, skip
  it rather than covering it.
```

5. Add these new constants and functions after `ARCHITECTURE_SYSTEM_PROMPT` (before `INTRO_TEMPLATE`):

```python
SAFETY_SYSTEM_PROMPT = """You are a content safety reviewer for a technology podcast script
segment. Read the segment text and decide if it violates either rule:
1. Contains vulgarity, profanity, or sexual content.
2. Presents an unethical use-case, project, or example (e.g. surveillance abuse, exploit/attack
   tooling meant to cause harm, discriminatory or privacy-violating systems) as something to
   emulate or admire, rather than something to avoid or merely report as news.

Respond with exactly one line: either "SAFE" or "FLAGGED: <one-sentence reason>". No other text.
"""


class ContentSafetyError(Exception):
    def __init__(self, segment_label: str, reason: str):
        self.segment_label = segment_label
        self.reason = reason
        super().__init__(f"{segment_label} segment failed content safety check: {reason}")


def check_segment_safety(text: str) -> tuple[bool, str]:
    messages = [
        {"role": "system", "content": SAFETY_SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    verdict = call_groq(messages, max_tokens=60)
    if verdict.strip().upper().startswith("SAFE"):
        return True, ""
    return False, verdict.strip()


def _retry_with_safety_reminder(messages: list[dict], segment: str, reason: str, max_tokens: int) -> str:
    messages.append({"role": "assistant", "content": segment})
    messages.append(
        {
            "role": "user",
            "content": (
                f"That segment was flagged by a content safety review: {reason}. Rewrite it so it "
                f"fully avoids vulgarity and does not present any unethical use-case, project, or "
                f"example as something to emulate, while still covering the same underlying news "
                f"items."
            ),
        }
    )
    return call_groq(messages, max_tokens=max_tokens)
```

6. In `generate_topic_segment`, after the existing length-retry block and before the final `return segment`, add:

```python
    is_safe, reason = check_segment_safety(segment)
    if not is_safe:
        log.warning("%s segment flagged by safety check (%s) - retrying once...", topic_label, reason)
        segment = _retry_with_safety_reminder(messages, segment, reason, max_tokens=min(1600, target_words * 3))
        is_safe, reason = check_segment_safety(segment)
        if not is_safe:
            raise ContentSafetyError(topic_label, reason)

    return segment
```

7. In `generate_architecture_segment`, make the equivalent change before its final `return segment` (same pattern, `max_tokens=min(1800, target_words * 3)`, and use `"The Architect's Corner"` as the label passed to `ContentSafetyError`):

```python
    is_safe, reason = check_segment_safety(segment)
    if not is_safe:
        log.warning("Architect's Corner flagged by safety check (%s) - retrying once...", reason)
        segment = _retry_with_safety_reminder(messages, segment, reason, max_tokens=min(1800, target_words * 3))
        is_safe, reason = check_segment_safety(segment)
        if not is_safe:
            raise ContentSafetyError("The Architect's Corner", reason)

    return segment
```

8. In `main()`, wrap the block that builds `parts` (from `parts: list[str] = []` through the end of the `if arch_has_items:` block, i.e. everything that calls `generate_topic_segment`/`generate_architecture_segment`) in a `try/except ContentSafetyError`. Change:

```python
    else:
        parts: list[str] = []

        if topics_with_items:
```

to:

```python
    else:
        parts: list[str] = []

        try:
            if topics_with_items:
```

and indent the rest of that block one level further (through `parts.append(generate_architecture_segment(...))`), then immediately after that block add:

```python
        except ContentSafetyError as e:
            log.error(
                "CONTENT SAFETY CHECK BLOCKED PUBLISH for %s: %s segment - %s. No script/transcript "
                "written; today's episode (app + YouTube) will not publish.",
                date, e.segment_label, e.reason,
            )
            raise SystemExit(f"Content safety check blocked publish for {date}: {e}") from e
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_common.py tests/test_generate_script_safety.py -v`
Expected: PASS — 2 tests in `test_common.py`, 4 tests in `test_generate_script_safety.py`, 6 total.

- [ ] **Step 6: Commit**

```bash
git add pipeline/common.py pipeline/scripting/generate_script.py pipeline/tests/test_common.py pipeline/tests/test_generate_script_safety.py
git commit -m "Add content safety guardrails to script generation, share call_groq via common.py"
```

---

### Task 2: Caption timing cues from Kokoro synthesis

**Files:**
- Modify: `pipeline/tts/synthesize.py`
- Test: `pipeline/tests/test_synthesize.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `synthesize.build_caption_cues(chunks: list[tuple[str, "numpy.ndarray"]], sample_rate: int) -> list[dict]`, where each dict is `{"text": str, "start": float, "end": float}` (seconds, rounded to 3 decimals). Writes `pipeline/data/captions_<date>.json` (a JSON array of those same dicts) — consumed by Task 4's `build_video.py`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_synthesize.py`:

```python
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tts"))
import synthesize  # noqa: E402


def test_build_caption_cues_computes_cumulative_timestamps():
    sample_rate = 1000
    chunks = [
        ("Hello there.", np.zeros(1000)),   # 1.0s
        ("Java shipped a new release.", np.zeros(2500)),  # 2.5s
        ("That's all.", np.zeros(500)),  # 0.5s
    ]

    cues = synthesize.build_caption_cues(chunks, sample_rate)

    assert cues == [
        {"text": "Hello there.", "start": 0.0, "end": 1.0},
        {"text": "Java shipped a new release.", "start": 1.0, "end": 3.5},
        {"text": "That's all.", "start": 3.5, "end": 4.0},
    ]


def test_build_caption_cues_strips_whitespace_from_text():
    cues = synthesize.build_caption_cues([("  padded text  \n", np.zeros(1000))], 1000)
    assert cues[0]["text"] == "padded text"


def test_build_caption_cues_empty_list():
    assert synthesize.build_caption_cues([], 1000) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && python -m pytest tests/test_synthesize.py -v`
Expected: FAIL with `AttributeError: module 'synthesize' has no attribute 'build_caption_cues'`

- [ ] **Step 3: Implement `build_caption_cues` and wire it into `run_kokoro`**

In `pipeline/tts/synthesize.py`, add `import json` to the imports at the top (alongside `os`, `subprocess`, `sys`).

Add this function before `run_kokoro`:

```python
def build_caption_cues(chunks: list[tuple[str, np.ndarray]], sample_rate: int) -> list[dict]:
    cues = []
    cursor = 0.0
    for text, audio in chunks:
        duration = len(audio) / sample_rate
        cues.append({"text": text.strip(), "start": round(cursor, 3), "end": round(cursor + duration, 3)})
        cursor += duration
    return cues
```

Replace `run_kokoro` with:

```python
def run_kokoro(text: str, lang_code: str, voice: str, wav_out: Path, captions_out: Path) -> None:
    from kokoro import KPipeline

    log.info("Running Kokoro (lang_code=%s, voice=%s)", lang_code, voice)
    pipeline = KPipeline(lang_code=lang_code)
    chunks = [(graphemes, audio) for graphemes, _, audio in pipeline(text, voice=voice)]
    if not chunks:
        raise RuntimeError("Kokoro produced no audio for this script")

    cues = build_caption_cues(chunks, SAMPLE_RATE)
    captions_out.write_text(json.dumps(cues, indent=2), encoding="utf-8")

    audio = np.concatenate([np.asarray(chunk) for _, chunk in chunks])
    sf.write(str(wav_out), audio, SAMPLE_RATE)
```

Update `main()`'s body (the part between building `wav_path`/`mp3_path` and the final log line) to:

```python
    wav_path = data_dir / f"episode_{date}.wav"
    mp3_path = data_dir / f"episode_{date}.mp3"
    captions_path = data_dir / f"captions_{date}.json"

    run_kokoro(text, lang_code, voice, wav_path, captions_path)
    convert_to_mp3(wav_path, mp3_path)
    wav_path.unlink(missing_ok=True)

    log.info("Wrote %s (%.1f MB)", mp3_path, mp3_path.stat().st_size / 1_000_000)
    log.info("Wrote %s", captions_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd pipeline && python -m pytest tests/test_synthesize.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/tts/synthesize.py pipeline/tests/test_synthesize.py
git commit -m "Record caption timing cues alongside Kokoro synthesis"
```

---

### Task 3: Static cover-art asset

**Files:**
- Create: `pipeline/video/make_cover.py`
- Create (generated, then committed): `pipeline/video/assets/cover.png`

**Interfaces:**
- Produces: `pipeline/video/assets/cover.png`, a 1920x1080 PNG — consumed by Task 4's `build_video.py` as `COVER_IMAGE`.
- Consumes: nothing.

This is a one-time local asset generator, not part of the daily pipeline — no automated test (image aesthetics can't be asserted), verified by visual inspection.

- [ ] **Step 1: Write the generator script**

Create `pipeline/video/make_cover.py`:

```python
"""
One-time asset generator - NOT part of the daily pipeline. Run locally once to
produce pipeline/video/assets/cover.png, then commit the resulting PNG. The
daily video-build stage (build_video.py) reuses this same static image every
day rather than regenerating it.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
BG_TOP = (13, 16, 36)
BG_BOTTOM = (26, 31, 58)
ACCENT = (124, 156, 255)
OUT_PATH = Path(__file__).resolve().parent / "assets" / "cover.png"


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def build_cover() -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    title_font = _load_font(96)
    subtitle_font = _load_font(40)

    title = "Daily Tech Briefing"
    subtitle = "Java - Spring Boot - Kubernetes - Cloud - and more"

    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(((WIDTH - title_w) / 2, HEIGHT / 2 - 100), title, font=title_font, fill=(255, 255, 255))

    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(((WIDTH - subtitle_w) / 2, HEIGHT / 2 + 30), subtitle, font=subtitle_font, fill=ACCENT)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build_cover()
```

- [ ] **Step 2: Run it and inspect the result**

Run: `cd pipeline && pip install Pillow==10.4.0 && python video/make_cover.py`
Expected: prints `Wrote .../pipeline/video/assets/cover.png`. Open the PNG and confirm it's a legible 1920x1080 dark-blue gradient card with "Daily Tech Briefing" centered — this is a manual visual check, there's no automated assertion for "looks good."

- [ ] **Step 3: Commit**

```bash
git add pipeline/video/make_cover.py pipeline/video/assets/cover.png
git commit -m "Add static cover-art asset for daily videos"
```

---

### Task 4: Video rendering (captions burned into cover art)

**Files:**
- Create: `pipeline/video/build_video.py`
- Test: `pipeline/tests/test_build_video.py`

**Interfaces:**
- Consumes: `pipeline/data/captions_<date>.json` (Task 2's output, list of `{"text","start","end"}`), `pipeline/data/episode_<date>.mp3`, `pipeline/video/assets/cover.png` (Task 3).
- Produces: `format_srt_timestamp(seconds: float) -> str`, `build_srt(cues: list[dict]) -> str`, and `pipeline/data/video_<date>.mp4` — consumed by Task 8's `youtube_publish.py`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/test_build_video.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video"))
import build_video  # noqa: E402


def test_format_srt_timestamp():
    assert build_video.format_srt_timestamp(0) == "00:00:00,000"
    assert build_video.format_srt_timestamp(1.5) == "00:00:01,500"
    assert build_video.format_srt_timestamp(65.25) == "00:01:05,250"
    assert build_video.format_srt_timestamp(3725.001) == "01:02:05,001"


def test_build_srt_formats_multiple_cues():
    cues = [
        {"text": "Hello there.", "start": 0.0, "end": 1.0},
        {"text": "Second cue.", "start": 1.0, "end": 2.5},
    ]
    srt = build_video.build_srt(cues)
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,000\nHello there.\n\n"
        "2\n00:00:01,000 --> 00:00:02,500\nSecond cue.\n"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_build_video.py -v`
Expected: FAIL — `build_video` module doesn't exist yet.

- [ ] **Step 3: Implement `build_video.py`**

Create `pipeline/video/build_video.py`:

```python
"""
Renders pipeline/data/video_<date>.mp4: the static cover-art image
(pipeline/video/assets/cover.png) with the episode's actual narration
captioned on top in sync with the audio, using the timing cues
tts/synthesize.py already records for free from Kokoro's own synthesis
chunks (pipeline/data/captions_<date>.json) - no forced-alignment/ASR tool
needed. Uses ffmpeg's `subtitles` filter (burned-in captions via a generated
SRT file), which needs ffmpeg built with libass - already true of the
GitHub-hosted ubuntu runner's packaged ffmpeg.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("build_video")

COVER_IMAGE = Path(__file__).resolve().parent / "assets" / "cover.png"


def format_srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(cues: list[dict]) -> str:
    lines = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{format_srt_timestamp(cue['start'])} --> {format_srt_timestamp(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    return "\n".join(lines)


def render_video(mp3_path: Path, srt_path: Path, out_path: Path) -> None:
    # ffmpeg's subtitles filter argument needs colons escaped (it uses ':' as its
    # own option separator) - this always runs on the Linux GitHub Actions runner.
    srt_arg = str(srt_path).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(COVER_IMAGE),
        "-i", str(mp3_path),
        "-vf",
        f"subtitles='{srt_arg}':force_style="
        f"'FontSize=28,PrimaryColour=&H00FFFFFF,BorderStyle=3,BackColour=&H80000000,"
        f"Alignment=2,MarginV=60'",
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    log.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    mp3_path = data_dir / f"episode_{date}.mp3"
    captions_path = data_dir / f"captions_{date}.json"
    if not mp3_path.exists() or not captions_path.exists():
        raise SystemExit(f"Missing episode audio/captions for {date} — run tts/synthesize.py first.")
    if not COVER_IMAGE.exists():
        raise SystemExit(f"Missing {COVER_IMAGE} — run video/make_cover.py once and commit the result.")

    cues = json.loads(captions_path.read_text(encoding="utf-8"))
    srt_path = data_dir / f"captions_{date}.srt"
    srt_path.write_text(build_srt(cues), encoding="utf-8")

    video_path = data_dir / f"video_{date}.mp4"
    render_video(mp3_path, srt_path, video_path)
    log.info("Wrote %s (%.1f MB)", video_path, video_path.stat().st_size / 1_000_000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_build_video.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/video/build_video.py pipeline/tests/test_build_video.py
git commit -m "Add video rendering stage (cover art + burned-in synced captions)"
```

---

### Task 5: Templated thumbnail generation

**Files:**
- Create: `pipeline/video/thumbnail.py`
- Test: `pipeline/tests/test_thumbnail.py`

**Interfaces:**
- Consumes: `pipeline/data/transcript_<date>.json`'s `topics_covered` field (list of `{"topic": str, "sources": [...]}`, produced by `generate_script.py`).
- Produces: `thumbnail.topic_accent_color(topic_label: str) -> tuple[int, int, int]`, `thumbnail.generate_thumbnail(date: str, topics: list[str], out_path: Path) -> None`, and `pipeline/data/thumbnail_<date>.png` — consumed by Task 8's `youtube_publish.py`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/test_thumbnail.py`:

```python
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video"))
import thumbnail  # noqa: E402


def test_topic_accent_color_known_topic():
    assert thumbnail.topic_accent_color("Java") == (247, 152, 29)


def test_topic_accent_color_unknown_topic_falls_back_to_default():
    assert thumbnail.topic_accent_color("Some New Topic") == thumbnail.DEFAULT_ACCENT


def test_generate_thumbnail_writes_correct_size_png(tmp_path):
    out_path = tmp_path / "thumb.png"
    thumbnail.generate_thumbnail("2026-08-03", ["Java", "The Architect's Corner"], out_path)

    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == (thumbnail.WIDTH, thumbnail.HEIGHT)
        assert img.mode == "RGB"


def test_generate_thumbnail_handles_empty_topics(tmp_path):
    out_path = tmp_path / "thumb.png"
    thumbnail.generate_thumbnail("2026-08-03", [], out_path)
    assert out_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_thumbnail.py -v`
Expected: FAIL — `thumbnail` module doesn't exist yet.

- [ ] **Step 3: Implement `thumbnail.py`**

Create `pipeline/video/thumbnail.py`:

```python
"""
Generates pipeline/data/thumbnail_<date>.png - a templated (not AI-generated)
YouTube thumbnail, colored by that day's dominant topic. Deterministic,
instant, zero external calls - appropriate for a fully unattended daily job
(see design spec Section 6 for why templated over AI-generated).
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("thumbnail")

WIDTH, HEIGHT = 1280, 720
DEFAULT_ACCENT = (124, 156, 255)

# Matches the topic labels in pipeline/config/sources.yaml plus the Architect's Corner.
TOPIC_ACCENT_COLORS = {
    "Java": (247, 152, 29),
    "Spring Boot": (109, 179, 63),
    "Liferay DXP": (0, 107, 143),
    "Hibernate": (191, 55, 50),
    "Apache Kafka": (35, 35, 35),
    "Redis": (220, 56, 45),
    "Docker": (13, 136, 214),
    "Microservices": (108, 92, 231),
    "Kubernetes": (50, 108, 229),
    "Jenkins": (240, 86, 34),
    "Git": (240, 80, 51),
    "Angular": (200, 30, 45),
    "Cloud (AWS / Azure / GCP)": (0, 153, 204),
    "The Architect's Corner": (255, 159, 67),
}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def topic_accent_color(topic_label: str) -> tuple[int, int, int]:
    return TOPIC_ACCENT_COLORS.get(topic_label, DEFAULT_ACCENT)


def generate_thumbnail(date: str, topics: list[str], out_path: Path) -> None:
    accent = topic_accent_color(topics[0]) if topics else DEFAULT_ACCENT
    bg = tuple(max(0, c - 180) for c in accent)

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, HEIGHT - 220), (WIDTH, HEIGHT)], fill=accent)

    date_font = _load_font(48)
    topics_font = _load_font(64)

    draw.text((60, 50), date, font=date_font, fill=(255, 255, 255))

    topics_text = " - ".join(topics[:3]) if topics else "Daily Tech Briefing"
    draw.text((60, HEIGHT - 180), topics_text, font=topics_font, fill=(20, 20, 20))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    transcript_path = data_dir / f"transcript_{date}.json"
    if not transcript_path.exists():
        raise SystemExit(f"Missing {transcript_path} — run scripting/generate_script.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]

    out_path = data_dir / f"thumbnail_{date}.png"
    generate_thumbnail(date, topics, out_path)
    log.info("Wrote %s", out_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_thumbnail.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/video/thumbnail.py pipeline/tests/test_thumbnail.py
git commit -m "Add templated per-topic thumbnail generation"
```

---

### Task 6: Title/description/tags generation (Groq)

**Files:**
- Create: `pipeline/video/metadata.py`
- Test: `pipeline/tests/test_metadata.py`

**Interfaces:**
- Consumes: `common.call_groq` (Task 1), `pipeline/data/transcript_<date>.json`'s `script` and `topics_covered` fields.
- Produces: `metadata.generate_metadata(date: str, topics: list[str], script: str) -> dict` returning `{"title": str, "description": str, "tags": list[str]}` — consumed by Task 8's `youtube_publish.py`.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/test_metadata.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video"))
import metadata  # noqa: E402


def test_build_metadata_prompt_includes_date_topics_and_script():
    prompt = metadata.build_metadata_prompt("2026-08-03", ["Java", "Kubernetes"], "the script text")
    assert "2026-08-03" in prompt
    assert "Java, Kubernetes" in prompt
    assert "the script text" in prompt


def test_generate_metadata_parses_json_and_appends_disclosure():
    fake_json = '{"title": "Java 24 and more", "description": "Today we cover Java.", "tags": ["java"]}'
    with patch("metadata.call_groq", return_value=fake_json):
        result = metadata.generate_metadata("2026-08-03", ["Java"], "script text")

    assert result["title"] == "Java 24 and more"
    assert result["tags"] == ["java"]
    assert result["description"].startswith("Today we cover Java.")
    assert "AI voice (Kokoro TTS)" in result["description"]


def test_generate_metadata_retries_once_on_invalid_json_then_succeeds():
    responses = iter(["not json", '{"title": "T", "description": "D", "tags": []}'])
    with patch("metadata.call_groq", side_effect=lambda *a, **k: next(responses)):
        result = metadata.generate_metadata("2026-08-03", ["Java"], "script")
    assert result["title"] == "T"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_metadata.py -v`
Expected: FAIL — `metadata` module doesn't exist yet.

- [ ] **Step 3: Implement `metadata.py`**

Create `pipeline/video/metadata.py`:

```python
"""
Generates the YouTube title/description/tags for today's episode via one
additional Groq call (same free API already used for the script), fed the
already safety-approved script + topic list - see design spec Section 3.4:
no separate safety check needed here since the source script has already
passed the guardrail in scripting/generate_script.py.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import call_groq, ensure_data_dir, episode_date, get_logger  # noqa: E402

log = get_logger("metadata")

METADATA_SYSTEM_PROMPT = """You write YouTube metadata for a daily technology news podcast video.
Given the date, topic list, and full narration script for today's episode, produce a JSON object
with exactly these keys:
- "title": a short, specific, compelling title (under 100 characters), mentioning the date and the
  most notable topic(s) - not a generic template.
- "description": 2-4 sentences summarizing what's covered, followed by a line listing the topics.
- "tags": a JSON array of 5-10 relevant lowercase tags (e.g. "java", "spring boot", "kubernetes").

Respond with ONLY the JSON object, no other text, no markdown code fences.
"""

DISCLOSURE_LINE = (
    "\n\nThis episode is narrated by an AI voice (Kokoro TTS) and its news content is "
    "aggregated and summarized from public sources."
)


def build_metadata_prompt(date: str, topics: list[str], script: str) -> str:
    return f"Date: {date}\nTopics covered: {', '.join(topics)}\n\nFull script:\n{script}"


def generate_metadata(date: str, topics: list[str], script: str) -> dict:
    messages = [
        {"role": "system", "content": METADATA_SYSTEM_PROMPT},
        {"role": "user", "content": build_metadata_prompt(date, topics, script)},
    ]
    raw = call_groq(messages, max_tokens=500)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Metadata response wasn't valid JSON - retrying once...")
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": "That wasn't valid JSON. Respond with ONLY the JSON object, no other text."}
        )
        raw = call_groq(messages, max_tokens=500)
        data = json.loads(raw)

    data["description"] = data["description"].rstrip() + DISCLOSURE_LINE
    return data


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    transcript_path = data_dir / f"transcript_{date}.json"
    if not transcript_path.exists():
        raise SystemExit(f"Missing {transcript_path} — run scripting/generate_script.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]

    result = generate_metadata(date, topics, transcript["script"])

    out_path = data_dir / f"youtube_metadata_{date}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("Wrote %s: %s", out_path, result["title"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_metadata.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/video/metadata.py pipeline/tests/test_metadata.py
git commit -m "Add Groq-generated YouTube title/description/tags"
```

---

### Task 7: One-time local YouTube OAuth consent script

**Files:**
- Create: `pipeline/auth/youtube_oauth_setup.py`

**Interfaces:**
- Consumes: `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET` env vars (from a Google Cloud OAuth Desktop-app client the user creates manually).
- Produces: prints a refresh token to the terminal — the user stores this as the `YOUTUBE_REFRESH_TOKEN` GitHub secret. Not imported by any other module; run manually, once, locally.

No automated test — this script's entire purpose is an interactive browser-based OAuth consent flow that cannot run headlessly or be meaningfully mocked in a way that proves anything real. Verified in Task 13 by actually running it.

- [ ] **Step 1: Write the script**

Create `pipeline/auth/youtube_oauth_setup.py`:

```python
"""
One-time, LOCAL-ONLY script: run this once on your own machine (never in CI)
to authorize this project against your YouTube channel and print a refresh
token. Requires a Google Cloud OAuth 2.0 Desktop-app client id/secret (create
one at https://console.cloud.google.com/apis/credentials after enabling the
YouTube Data API v3 for your project).

Usage:
  export YOUTUBE_CLIENT_ID=...        # PowerShell: $env:YOUTUBE_CLIENT_ID = "..."
  export YOUTUBE_CLIENT_SECRET=...
  python pipeline/auth/youtube_oauth_setup.py

Opens a browser for you to sign in and grant access, then prints the refresh
token to store as the YOUTUBE_REFRESH_TOKEN GitHub Actions secret.
"""

import os

from google_auth_oauthlib.flow import InstalledAppFlow

# Broad "youtube" scope (not the narrower "youtube.upload") because this project also
# calls playlistItems.insert, which requires the broader scope.
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def main() -> None:
    client_id = os.environ["YOUTUBE_CLIENT_ID"]
    client_secret = os.environ["YOUTUBE_CLIENT_SECRET"]

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    credentials = flow.run_local_server(port=0)

    print("\nSuccess. Store this as the YOUTUBE_REFRESH_TOKEN GitHub Actions secret:\n")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/auth/youtube_oauth_setup.py
git commit -m "Add one-time local YouTube OAuth consent script"
```

(This task's real verification — actually running it against a live Google account — happens in Task 13, since it needs the Google Cloud project/OAuth client that only the user can create.)

---

### Task 8: YouTube upload stage

**Files:**
- Create: `pipeline/publish/youtube_publish.py`
- Test: `pipeline/tests/test_youtube_publish.py`

**Interfaces:**
- Consumes: `video.thumbnail.generate_thumbnail` (Task 5), `video.metadata.generate_metadata` (Task 6), `pipeline/data/video_<date>.mp4` (Task 4), `pipeline/data/transcript_<date>.json`.
- Produces: `youtube_publish.youtube_configured() -> bool`, `youtube_publish.video_already_uploaded(youtube, playlist_id: str, date: str) -> bool`, `youtube_publish.YouTubeAuthError` — this is the last new stage; nothing downstream consumes its outputs besides the real YouTube API.

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/test_youtube_publish.py`:

```python
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "publish"))
import youtube_publish  # noqa: E402


def test_youtube_configured_true_when_all_vars_set(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "a")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "b")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "c")
    monkeypatch.setenv("YOUTUBE_PLAYLIST_ID", "d")
    assert youtube_publish.youtube_configured() is True


def test_youtube_configured_false_when_one_missing(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "a")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "b")
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("YOUTUBE_PLAYLIST_ID", "d")
    assert youtube_publish.youtube_configured() is False


def test_video_already_uploaded_true_when_date_in_a_title():
    fake_youtube = MagicMock()
    fake_youtube.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [
            {"snippet": {"title": "Daily Tech Briefing - Aug 2, 2026"}},
            {"snippet": {"title": "Daily Tech Briefing - 2026-08-03"}},
        ]
    }
    assert youtube_publish.video_already_uploaded(fake_youtube, "PL123", "2026-08-03") is True


def test_video_already_uploaded_false_when_no_match():
    fake_youtube = MagicMock()
    fake_youtube.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [{"snippet": {"title": "Daily Tech Briefing - 2026-08-02"}}]
    }
    assert youtube_publish.video_already_uploaded(fake_youtube, "PL123", "2026-08-03") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_youtube_publish.py -v`
Expected: FAIL — `youtube_publish` module doesn't exist yet.

- [ ] **Step 3: Implement `youtube_publish.py`**

Create `pipeline/publish/youtube_publish.py`:

```python
"""
Uploads today's video + thumbnail to YouTube and adds it to the configured
playlist. Independent, additive pipeline stage: failures here must never
block the app's audio delivery (already completed by publish/publish.py
before this stage runs - see design spec Section 9).

One-time setup: see pipeline/auth/youtube_oauth_setup.py and the README's
YouTube setup section for how to obtain YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN
and YOUTUBE_PLAYLIST_ID.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402
from video.metadata import generate_metadata  # noqa: E402
from video.thumbnail import generate_thumbnail  # noqa: E402

log = get_logger("youtube_publish")

SCOPES = ["https://www.googleapis.com/auth/youtube"]
CATEGORY_SCIENCE_AND_TECHNOLOGY = "28"


class YouTubeAuthError(Exception):
    """Raised when the stored OAuth refresh token is missing/expired/revoked."""


def youtube_configured() -> bool:
    return all(
        os.environ.get(var)
        for var in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_PLAYLIST_ID")
    )


def build_youtube_client():
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise YouTubeAuthError(
            f"Failed to refresh the YouTube OAuth token - it may have expired (7-day limit "
            f"on unverified apps) or been revoked. Re-run pipeline/auth/youtube_oauth_setup.py "
            f"and update the YOUTUBE_REFRESH_TOKEN secret. Original error: {e}"
        ) from e

    return build("youtube", "v3", credentials=creds)


def video_already_uploaded(youtube, playlist_id: str, date: str) -> bool:
    response = youtube.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=50).execute()
    return any(date in item["snippet"]["title"] for item in response.get("items", []))


def upload_video(youtube, video_path: Path, metadata: dict) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": CATEGORY_SCIENCE_AND_TECHNOLOGY,
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response["id"]


def set_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))).execute()


def add_to_playlist(youtube, playlist_id: str, video_id: str) -> None:
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()


def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()

    if not youtube_configured():
        log.warning(
            "YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN/PLAYLIST_ID not fully set - skipping YouTube publish."
        )
        return

    video_path = data_dir / f"video_{date}.mp4"
    transcript_path = data_dir / f"transcript_{date}.json"
    if not video_path.exists() or not transcript_path.exists():
        raise SystemExit(f"Missing video/transcript for {date} — run video/build_video.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]
    playlist_id = os.environ["YOUTUBE_PLAYLIST_ID"]

    try:
        youtube = build_youtube_client()
    except YouTubeAuthError as e:
        log.error("YOUTUBE AUTH FAILURE (action needed): %s", e)
        return

    if video_already_uploaded(youtube, playlist_id, date):
        log.info("A video for %s is already in the playlist - skipping (idempotent re-run).", date)
        return

    thumbnail_path = data_dir / f"thumbnail_{date}.png"
    generate_thumbnail(date, topics, thumbnail_path)

    result = generate_metadata(date, topics, transcript["script"])
    (data_dir / f"youtube_metadata_{date}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    log.info("Uploading %s to YouTube...", video_path.name)
    video_id = upload_video(youtube, video_path, result)
    log.info("Uploaded video id %s, setting thumbnail...", video_id)
    set_thumbnail(youtube, video_id, thumbnail_path)
    log.info("Adding to playlist %s...", playlist_id)
    add_to_playlist(youtube, playlist_id, video_id)

    log.info("Published YouTube video %s: %s", video_id, result["title"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_youtube_publish.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/publish/youtube_publish.py pipeline/tests/test_youtube_publish.py
git commit -m "Add YouTube upload stage (video + thumbnail + playlist, idempotent)"
```

---

### Task 9: Wire new stages into the pipeline runner, fault-isolated

**Files:**
- Modify: `pipeline/run_pipeline.py`
- Test: `pipeline/tests/test_run_pipeline.py`

**Interfaces:**
- Consumes: nothing new (this task only changes stage orchestration).
- Produces: `run_pipeline.run_stage(name: str, module_path: str, required: bool = True) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_run_pipeline.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_pipeline  # noqa: E402


def test_run_stage_required_reraises_on_failure():
    with patch("run_pipeline.runpy.run_path", side_effect=RuntimeError("boom")):
        try:
            run_pipeline.run_stage("some_stage", "fake/path.py", required=True)
            assert False, "expected RuntimeError to propagate"
        except RuntimeError:
            pass


def test_run_stage_not_required_swallows_failure_and_returns_false():
    with patch("run_pipeline.runpy.run_path", side_effect=RuntimeError("boom")):
        result = run_pipeline.run_stage("some_stage", "fake/path.py", required=False)
    assert result is False


def test_run_stage_not_required_swallows_system_exit_and_returns_false():
    with patch("run_pipeline.runpy.run_path", side_effect=SystemExit("no episode today")):
        result = run_pipeline.run_stage("some_stage", "fake/path.py", required=False)
    assert result is False


def test_run_stage_required_reraises_system_exit():
    with patch("run_pipeline.runpy.run_path", side_effect=SystemExit("missing input")):
        try:
            run_pipeline.run_stage("some_stage", "fake/path.py", required=True)
            assert False, "expected SystemExit to propagate"
        except SystemExit:
            pass


def test_run_stage_success_returns_true():
    with patch("run_pipeline.runpy.run_path", return_value=None):
        result = run_pipeline.run_stage("some_stage", "fake/path.py")
    assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && python -m pytest tests/test_run_pipeline.py -v`
Expected: FAIL — `run_pipeline.run_stage` currently takes no `required` kwarg, doesn't catch exceptions, and `runpy` is imported locally inside the function rather than at module level (so `run_pipeline.runpy` doesn't exist to patch).

- [ ] **Step 3: Update `run_pipeline.py`**

Replace the whole file content with:

```python
"""
Runs the full daily pipeline: collect -> generate_script -> synthesize -> build_video ->
publish -> youtube_publish.

Usage:
  python run_pipeline.py                 # run all stages
  python run_pipeline.py --skip-publish  # everything except the Firebase/YouTube publish stages
                                          # (handy for local testing without those creds)
"""

import argparse
import runpy
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_logger  # noqa: E402

log = get_logger("pipeline")


def run_stage(name: str, module_path: str, required: bool = True) -> bool:
    log.info("=== Stage: %s ===", name)
    start = time.time()
    try:
        runpy.run_path(module_path, run_name="__main__")
    except SystemExit as e:
        if required:
            raise
        log.error("=== Stage %s exited early (%s) - continuing, this stage is non-critical ===", name, e)
        return False
    except Exception:
        if required:
            raise
        log.exception("=== Stage %s failed - continuing, this stage is non-critical ===", name)
        return False
    log.info("=== Done: %s (%.1fs) ===", name, time.time() - start)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-publish", action="store_true", help="Skip the Firebase/YouTube publish stages")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    run_stage("collect", str(root / "collector" / "collect.py"))
    run_stage("generate_script", str(root / "scripting" / "generate_script.py"))
    run_stage("synthesize", str(root / "tts" / "synthesize.py"))
    run_stage("build_video", str(root / "video" / "build_video.py"), required=False)
    if not args.skip_publish:
        run_stage("publish", str(root / "publish" / "publish.py"))
        run_stage("youtube_publish", str(root / "publish" / "youtube_publish.py"), required=False)
    else:
        log.info("Skipping publish stages (--skip-publish)")

    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
```

(Note: `generate_script`'s content-safety `SystemExit` stays `required=True` by default — deliberately still halts the whole pipeline, per design spec Section 3.3/9. Only `build_video` and `youtube_publish` are marked `required=False`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_run_pipeline.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full pipeline test suite together**

Run: `cd pipeline && python -m pytest tests/ -v`
Expected: all tests from Tasks 1–9 PASS (should be ~21 tests total).

- [ ] **Step 6: Commit**

```bash
git add pipeline/run_pipeline.py pipeline/tests/test_run_pipeline.py
git commit -m "Wire build_video/youtube_publish stages into the pipeline, fault-isolated"
```

---

### Task 10: Workflow secrets and dependencies

**Files:**
- Modify: `pipeline/requirements.txt`
- Modify: `.github/workflows/daily-episode.yml`

**Interfaces:**
- Consumes: nothing (config-only task).
- Produces: CI environment with all new Python deps installed and new secrets available as env vars.

- [ ] **Step 1: Add new dependencies to `pipeline/requirements.txt`**

Append to `pipeline/requirements.txt`:

```
Pillow==10.4.0
google-api-python-client==2.149.0
google-auth-httplib2==0.2.0
google-auth-oauthlib==1.2.1
pytest==8.3.3
```

- [ ] **Step 2: Add new secrets to the workflow env block**

In `.github/workflows/daily-episode.yml`, in the `env:` block under `build-episode:` (currently ending with `FIREBASE_STORAGE_BUCKET: ${{ secrets.FIREBASE_STORAGE_BUCKET }}`), add:

```yaml
      YOUTUBE_CLIENT_ID: ${{ secrets.YOUTUBE_CLIENT_ID }}
      YOUTUBE_CLIENT_SECRET: ${{ secrets.YOUTUBE_CLIENT_SECRET }}
      YOUTUBE_REFRESH_TOKEN: ${{ secrets.YOUTUBE_REFRESH_TOKEN }}
      YOUTUBE_PLAYLIST_ID: ${{ secrets.YOUTUBE_PLAYLIST_ID }}
```

- [ ] **Step 3: Verify no other workflow changes are needed**

`run: python pipeline/run_pipeline.py` already runs the full pipeline including the two new stages (Task 9's change), so no new `run:` steps are needed — only the `pip install -r pipeline/requirements.txt` step (already present) needs to pick up the new deps, which it will automatically since they're now in the requirements file.

- [ ] **Step 4: Commit**

```bash
git add pipeline/requirements.txt .github/workflows/daily-episode.yml
git commit -m "Add YouTube/video Python deps and secrets to the daily workflow"
```

(Secrets themselves aren't set here — that happens in Task 13, once real values exist.)

---

### Task 11: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `BRD.md`

**Interfaces:** None (docs only).

- [ ] **Step 1: Update `README.md`**

Add a new numbered setup section (after the existing "4. Firebase project" section, renumbering "5. GitHub Actions secrets" if needed, or appending as a new "5." and shifting the old "5." to "6.") covering:
- Creating a Google Cloud project and enabling the YouTube Data API v3.
- Creating an OAuth 2.0 Desktop-app client (client ID + secret).
- Running `pipeline/auth/youtube_oauth_setup.py` locally to get a refresh token.
- The `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`, `YOUTUBE_PLAYLIST_ID` secrets.
- A short note that unverified OAuth apps have 7-day refresh tokens, and that this project goes through Google's OAuth verification for long-term unattended use (linking to the design spec for detail).

Also update the repo-layout code block near the top (currently ending at `android-app/          Android (Kotlin) app: ...`) to mention the video/YouTube stages, e.g. add a line under the `pipeline/` description noting `-> build video + upload to YouTube`.

- [ ] **Step 2: Update `BRD.md`**

Add a new subsection under Section 14 (e.g. "14.9 YouTube video publishing") summarizing: video style (cover art + synced captions), templated thumbnails, Groq-generated metadata, and the OAuth-verification approach for unattended uploads — referencing `docs/superpowers/specs/2026-08-03-youtube-video-design.md` for full detail rather than duplicating it. Also add one line to Section 7 (Content Topics) or wherever guardrails naturally fit, noting the content-safety guardrail now gates script generation.

- [ ] **Step 3: Commit**

```bash
git add README.md BRD.md
git commit -m "Document YouTube video publishing setup and guardrails"
```

---

### Task 12: Local dry run of the new stages

**Files:** None created/modified — this is a verification-only task using artifacts already in `pipeline/data/` from the most recent real pipeline run (from this session's earlier live tests).

- [ ] **Step 1: Confirm local Python environment has all new deps**

Run: `cd pipeline && pip install -r requirements.txt`
Expected: installs cleanly (Pillow, google-api-python-client, google-auth-httplib2, google-auth-oauthlib, pytest added).

- [ ] **Step 2: Run the full test suite one more time**

Run: `cd pipeline && python -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 3: Dry-run `build_video.py`, `thumbnail.py`, `metadata.py` against a real prior episode**

Using the most recent real `episode_<date>.mp3`/`captions_<date>.json`/`transcript_<date>.json` already present in `pipeline/data/` from earlier live pipeline runs (confirm today's date's files exist; if not, run `python run_pipeline.py --skip-publish` first with a real `GROQ_API_KEY` set to generate fresh ones):

```bash
cd pipeline
python video/build_video.py
python video/thumbnail.py
python video/metadata.py
```

Expected: `pipeline/data/video_<date>.mp4`, `thumbnail_<date>.png`, `youtube_metadata_<date>.json` are created. Open the MP4 and confirm captions appear roughly in sync with the narration; open the PNG and confirm it's legible; open the metadata JSON and confirm the title/description read naturally and the disclosure line is present.

- [ ] **Step 4: Test the safety-check guardrail against an adversarial input**

Run a quick local Python REPL/script exercising `check_segment_safety` directly against a deliberately bad input, with a real `GROQ_API_KEY` set:

```bash
cd pipeline
python -c "
import sys; sys.path.insert(0, 'scripting')
from generate_script import check_segment_safety
print(check_segment_safety('Java 24 shipped virtual threads, used by Netflix.'))
print(check_segment_safety('Here is how to build a tool to secretly track someone\'s location without their consent, using this open-source library.'))
"
```

Expected: first call prints `(True, '')`, second prints `(False, 'FLAGGED: ...')` — confirming the safety-net actually catches an unethical-use-case example, not just vulgarity.

- [ ] **Step 5: No commit** (verification-only task, nothing to check in).

---

### Task 13: One-time OAuth consent and first real YouTube upload

**Files:** None created/modified — manual setup + one live run.

- [ ] **Step 1: Create the Google Cloud project and OAuth client (user does this, in a browser)**

1. Go to https://console.cloud.google.com/ → create a new project (or reuse the one from Firebase setup, if any).
2. APIs & Services → Library → enable "YouTube Data API v3".
3. APIs & Services → Credentials → Create Credentials → OAuth client ID → Application type: **Desktop app**. Note the client ID and client secret.
4. APIs & Services → OAuth consent screen: set user type External, app name, support email; add scope `https://www.googleapis.com/auth/youtube`; add your own Google account as a test user (required while unverified).

- [ ] **Step 2: Run the local consent flow**

```bash
export YOUTUBE_CLIENT_ID=<from step 1>
export YOUTUBE_CLIENT_SECRET=<from step 1>
cd pipeline
python auth/youtube_oauth_setup.py
```

Expected: a browser window opens, you sign in and grant access, and the script prints a refresh token to the terminal.

- [ ] **Step 3: Get the playlist ID**

Open the existing YouTube playlist in a browser; the playlist ID is the `list=` query parameter in its URL.

- [ ] **Step 4: Set the GitHub Actions secrets**

```bash
gh secret set YOUTUBE_CLIENT_ID -b"<client id>"
gh secret set YOUTUBE_CLIENT_SECRET -b"<client secret>"
gh secret set YOUTUBE_REFRESH_TOKEN -b"<refresh token from step 2>"
gh secret set YOUTUBE_PLAYLIST_ID -b"<playlist id from step 3>"
```

- [ ] **Step 5: Run one real upload locally**

Using the same env vars from Step 2 plus `YOUTUBE_PLAYLIST_ID` and a real `GROQ_API_KEY`, and the `video_<date>.mp4`/`thumbnail_<date>.png` from Task 12:

```bash
cd pipeline
export YOUTUBE_PLAYLIST_ID=<from step 3>
python publish/youtube_publish.py
```

Expected: logs show "Uploading...", "Uploaded video id ...", "Adding to playlist...", "Published YouTube video ...". Open the playlist in a browser and confirm the video appears, with the correct title/description/thumbnail, marked as containing altered/synthetic content (visible in YouTube Studio's video details), and Public.

(This run doubles as the demo material needed for the OAuth verification submission in Task 14.)

- [ ] **Step 6: No commit** (credentials/setup only).

---

### Task 14: Full live workflow run, idempotency check, and OAuth verification submission

**Files:** None created/modified.

- [ ] **Step 1: Trigger the full workflow**

```bash
gh workflow run daily-episode.yml
gh run list --workflow=daily-episode.yml --limit 1 --json databaseId,status
```

Then watch it: `gh run watch <run-id> --exit-status`

Expected: all steps succeed, including the new `build_video`/`youtube_publish` stages inside `run_pipeline.py`'s output in the "Run pipeline" step's logs.

- [ ] **Step 2: Verify the real output**

- Confirm a new video appears in the YouTube playlist (title/description/thumbnail/disclosure correct).
- Confirm the app/Firebase (or GitHub Release fallback) episode still published normally — the YouTube stage must not have affected it.

- [ ] **Step 3: Verify idempotency**

Re-run the same workflow (`gh workflow run daily-episode.yml`) on the same day and confirm in the logs that `youtube_publish` logs "already in the playlist - skipping" rather than creating a duplicate upload. Confirm in YouTube Studio that only one video exists for that date.

- [ ] **Step 4: Submit for OAuth verification**

In the Google Cloud Console's OAuth consent screen settings, submit the app for verification: provide a short privacy policy (can be a simple static page — e.g. a `PRIVACY.md` in the repo, referenced by URL via GitHub's raw file view or GitHub Pages), justify the `youtube` scope usage ("automated daily upload of a personal tech-news video podcast to my own channel"), and attach/describe the Task 13 Step 5 run as the demo of the app's functionality.

- [ ] **Step 5: Note the interim state**

Until verification completes (days to weeks, per Google), the refresh token from Task 13 remains valid for 7 days at a time under "Testing" status. If `youtube_publish` ever logs a `YOUTUBE AUTH FAILURE` error in the Actions log, re-run Task 13 Steps 2 and 4 (get a fresh refresh token, update the secret) until verification lands.

- [ ] **Step 6: No commit** (operational verification only).

---

## Self-Review Notes

- **Spec coverage:** Section 3 (guardrails) → Task 1. Section 5 (video generation, incl. 5.1 caption timing) → Tasks 2 & 4. Section 6 (thumbnail) → Task 5. Section 7 (metadata) → Task 6. Section 8 (YouTube upload, incl. 8.1 setup, 8.2 verification, 8.3 upload flow, 8.4 idempotency) → Tasks 7, 8, 13, 14. Section 9 (error handling/fault isolation) → Task 9. Section 10 (workflow changes) → Task 10. Section 11 (testing plan) → Tasks 12, 13, 14. No spec section is without a task.
- **Placeholder scan:** no TBD/TODO; every code step has real, complete code; every API field/scope/category ID was verified against current YouTube Data API v3 docs rather than assumed.
- **Type/signature consistency:** `build_caption_cues` (Task 2) output shape `{"text","start","end"}` matches what Task 4's `build_srt` consumes (`cue['start']`, `cue['end']`, `cue["text"]`). `transcript["topics_covered"]` shape (`{"topic","sources"}`, set by the existing `generate_script.py`) matches what Tasks 5, 6, and 8 all read. `generate_metadata`'s return dict keys (`title`, `description`, `tags`) match exactly what Task 8's `upload_video` reads. `youtube_configured()`, `video_already_uploaded()`, `YouTubeAuthError` names are used consistently between Task 8's implementation and its own tests.
