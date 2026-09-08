# Project Manager's Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second daily show, "Project Manager's Room" (~10 min, PM/Delivery-Manager audience), running through the same pipeline as the existing tech briefing, publishing to a new YouTube playlist on the same channel, and surfaced in the Android app via a show toggle.

**Architecture:** A small show manifest (`SHOWS` dict) in `pipeline/common.py` parameterizes the existing mechanical stages (collect, TTS, video build, Firebase publish, YouTube publish) by show — one implementation, no duplication. Script generation gets its own file per show (`generate_script.py` for tech, new `generate_script_pm.py` for PM) since the content is genuinely different. `run_pipeline.py --show {tech,pm}` selects which show runs; a new GitHub Actions workflow schedules the PM show separately.

**Tech Stack:** Python 3.11 (pipeline), pytest, Kotlin/Android (app), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-08-pm-delivery-show-design.md`

## Global Constraints

- Tech show's existing file names, Firestore collection, GitHub Release tag, and YouTube playlist must stay byte-identical (unsuffixed) — every parameterization defaults to tech's current behavior so nothing published so far breaks.
- No LinkedIn automation, no new Firestore/FCM push infrastructure, no new YouTube channel — see spec Non-goals.
- PM show voice: `am_michael` (via existing `KOKORO_VOICE` env var, no code change). PM YouTube category id: `"27"` (Education). Tech stays category `"28"`.
- Story segment content must never use real company or person names (prompt-enforced, not code-verified — see Task 12 note).
- All new Python code follows this repo's existing style: stdlib + already-installed deps only, no new dependencies.

---

## Task 1: Show manifest and path helpers in `common.py`

**Files:**
- Modify: `pipeline/common.py`
- Test: `pipeline/tests/test_common.py`

**Interfaces:**
- Produces: `common.SHOWS: dict[str, dict]` (keys `"tech"`, `"pm"`; each a dict with `sources_path: Path`, `suffix: str`, `show_label: str`, `cover_image: str`, `script_module: str`, `firestore_collection: str`, `storage_prefix: str`, `push_topic: str`, `youtube_playlist_env: str`, `youtube_category_id: str`), `common.current_show() -> dict`, `common.artifact_path(kind: str, ext: str, date: str) -> Path`.

- [ ] **Step 1: Write the failing tests**

Append to `pipeline/tests/test_common.py`:

```python
def test_current_show_defaults_to_tech(monkeypatch):
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)
    assert common.current_show()["show_label"] == "Daily Tech Briefing"


def test_current_show_reads_pipeline_show_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHOW", "pm")
    assert common.current_show()["show_label"] == "Project Manager's Room"


def test_artifact_path_tech_is_unsuffixed(monkeypatch):
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)
    path = common.artifact_path("episode", "mp3", "2026-09-08")
    assert path == common.DATA_DIR / "episode_2026-09-08.mp3"


def test_artifact_path_pm_has_suffix(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHOW", "pm")
    path = common.artifact_path("episode", "mp3", "2026-09-08")
    assert path == common.DATA_DIR / "episode_pm_2026-09-08.mp3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_common.py -v`
Expected: FAIL — `AttributeError: module 'common' has no attribute 'current_show'` (and similar for `artifact_path`).

- [ ] **Step 3: Add the manifest and helpers**

Append to `pipeline/common.py` (after `ensure_data_dir`):

```python
SHOWS: dict[str, dict] = {
    "tech": {
        "sources_path": CONFIG_PATH,
        "suffix": "",
        "show_label": "Daily Tech Briefing",
        "cover_image": "cover.png",
        "script_module": "scripting.generate_script",
        "firestore_collection": "episodes",
        "storage_prefix": "episodes",
        "push_topic": "daily_episode",
        "youtube_playlist_env": "YOUTUBE_PLAYLIST_ID",
        "youtube_category_id": "28",  # Science & Technology
    },
    "pm": {
        "sources_path": PIPELINE_ROOT / "config" / "sources_pm.yaml",
        "suffix": "_pm",
        "show_label": "Project Manager's Room",
        "cover_image": "cover_pm.png",
        "script_module": "scripting.generate_script_pm",
        "firestore_collection": "episodes_pm",
        "storage_prefix": "episodes_pm",
        "push_topic": "daily_pm_episode",
        "youtube_playlist_env": "YOUTUBE_PM_PLAYLIST_ID",
        "youtube_category_id": "27",  # Education
    },
}


def current_show() -> dict:
    """Resolves the active show from the PIPELINE_SHOW env var (set by
    run_pipeline.py's --show flag), defaulting to "tech" so every existing
    call site and workflow keeps working unchanged."""
    return SHOWS[os.environ.get("PIPELINE_SHOW", "tech")]


def artifact_path(kind: str, ext: str, date: str) -> Path:
    """e.g. artifact_path("episode", "mp3", "2026-09-08") ->
    data/episode_2026-09-08.mp3 for the tech show (unsuffixed - matches every
    already-published filename) or data/episode_pm_2026-09-08.mp3 for pm."""
    suffix = current_show()["suffix"]
    return DATA_DIR / f"{kind}{suffix}_{date}.{ext}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_common.py -v`
Expected: PASS (all tests, including the two pre-existing `call_groq` tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/common.py pipeline/tests/test_common.py
git commit -m "Add show manifest and artifact_path helper to common.py"
```

---

## Task 2: Move safety-check code into `common.py`; generalize `allocate_word_budgets`

**Files:**
- Modify: `pipeline/common.py`
- Modify: `pipeline/scripting/generate_script.py`
- Test: `pipeline/tests/test_generate_script_safety.py` (existing tests must still pass unchanged)

**Interfaces:**
- Consumes: `common.call_groq` (Task 1's file, unchanged).
- Produces: `common.SAFETY_SYSTEM_PROMPT: str`, `common.ContentSafetyError`, `common.check_segment_safety(text: str) -> tuple[bool, str]`, `common.retry_with_safety_reminder(messages: list[dict], segment: str, reason: str, max_tokens: int) -> str`. `generate_script.allocate_word_budgets(topics_with_items, target_words=TOPIC_TARGET_WORDS, min_words=MIN_SEGMENT_WORDS, max_words=MAX_SEGMENT_WORDS) -> dict[str, int]` (new optional params, defaults preserve old behavior).

- [ ] **Step 1: Run the existing safety tests first to confirm the current baseline**

Run: `cd pipeline && python -m pytest tests/test_generate_script_safety.py -v`
Expected: PASS (4 tests) — this is the regression baseline these tests must still pass against after the refactor below.

- [ ] **Step 2: Move the safety-check code to `common.py`**

Append to `pipeline/common.py` (after the `SHOWS`/`current_show`/`artifact_path` block from Task 1):

```python
SAFETY_SYSTEM_PROMPT = """You are a content safety reviewer for a podcast script segment. Read
the segment text and decide if it violates either rule:
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


def retry_with_safety_reminder(messages: list[dict], segment: str, reason: str, max_tokens: int) -> str:
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

- [ ] **Step 3: Remove the moved code from `generate_script.py` and import it instead**

In `pipeline/scripting/generate_script.py`:

Replace line 39:
```python
from common import call_groq, ensure_data_dir, episode_date, get_logger  # noqa: E402
```
with:
```python
from common import (  # noqa: E402
    ContentSafetyError,
    call_groq,
    check_segment_safety,
    ensure_data_dir,
    episode_date,
    get_logger,
    retry_with_safety_reminder,
)
```

Delete lines 106–148 (the `SAFETY_SYSTEM_PROMPT` constant, `ContentSafetyError` class, `check_segment_safety`, and `_retry_with_safety_reminder` — now living in `common.py`).

Update the two call sites (originally lines 216 and 254) that called `_retry_with_safety_reminder(...)` to call `retry_with_safety_reminder(...)` (drop the leading underscore) instead — both are inside `generate_topic_segment` and `generate_architecture_segment`.

- [ ] **Step 4: Generalize `allocate_word_budgets`**

Replace the function (originally lines 262–272):
```python
def allocate_word_budgets(topics_with_items: list[tuple[str, list[dict]]]) -> dict[str, int]:
    """Splits TOPIC_TARGET_WORDS across topics proportionally to how many items
    each one has, so a topic with more news gets more airtime, within a
    [MIN_SEGMENT_WORDS, MAX_SEGMENT_WORDS] band per topic."""
    total_items = sum(len(items) for _, items in topics_with_items) or 1
    budgets = {}
    for label, items in topics_with_items:
        share = len(items) / total_items
        budget = round(TOPIC_TARGET_WORDS * share)
        budgets[label] = max(MIN_SEGMENT_WORDS, min(MAX_SEGMENT_WORDS, budget))
    return budgets
```
with:
```python
def allocate_word_budgets(
    topics_with_items: list[tuple[str, list[dict]]],
    target_words: int = TOPIC_TARGET_WORDS,
    min_words: int = MIN_SEGMENT_WORDS,
    max_words: int = MAX_SEGMENT_WORDS,
) -> dict[str, int]:
    """Splits `target_words` across topics proportionally to how many items each
    one has, so a topic with more news gets more airtime, within a
    [min_words, max_words] band per topic. Defaults match this show's own
    TOPIC_TARGET_WORDS/MIN_SEGMENT_WORDS/MAX_SEGMENT_WORDS; generate_script_pm.py
    (Task 12) passes its own smaller targets."""
    total_items = sum(len(items) for _, items in topics_with_items) or 1
    budgets = {}
    for label, items in topics_with_items:
        share = len(items) / total_items
        budget = round(target_words * share)
        budgets[label] = max(min_words, min(max_words, budget))
    return budgets
```

- [ ] **Step 5: Add a test for the new params, and rerun the full existing safety suite**

Append to `pipeline/tests/test_generate_script_safety.py`:

```python
def test_allocate_word_budgets_respects_custom_target_and_bounds():
    budgets = generate_script.allocate_word_budgets(
        [("A", [{}, {}]), ("B", [{}])],
        target_words=300,
        min_words=50,
        max_words=250,
    )
    assert budgets["A"] == 200  # 2/3 of 300
    assert budgets["B"] == 100  # 1/3 of 300
```

Run: `cd pipeline && python -m pytest tests/test_generate_script_safety.py -v`
Expected: PASS — all 5 tests (the original 4 plus this one). The original 4 pass unchanged because `patch("generate_script.check_segment_safety", ...)` and `generate_script.ContentSafetyError` still resolve correctly: importing a name via `from common import check_segment_safety` makes it an attribute of the `generate_script` module too, so patching `generate_script.check_segment_safety` still works exactly as before.

- [ ] **Step 6: Commit**

```bash
git add pipeline/common.py pipeline/scripting/generate_script.py pipeline/tests/test_generate_script_safety.py
git commit -m "Move content-safety check into common.py; generalize allocate_word_budgets"
```

---

## Task 3: Parameterize `collector/collect.py` by show

**Files:**
- Modify: `pipeline/collector/collect.py`
- Test: create `pipeline/tests/test_collect.py`

**Interfaces:**
- Consumes: `common.current_show()`, `common.artifact_path()` (Task 1).
- Produces: `collect.load_config()` now reads `current_show()["sources_path"]` instead of the fixed `CONFIG_PATH`; `collect.main()` writes to `artifact_path("collected", "json", date)`.

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_collect.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
import common  # noqa: E402
import collect  # noqa: E402


def test_load_config_reads_pm_sources_when_pm_show_active(monkeypatch, tmp_path):
    fake_sources = tmp_path / "sources_pm.yaml"
    fake_sources.write_text("topics:\n  agile:\n    label: Agile\n    rss: []\n    reddit_subs: []\n", encoding="utf-8")
    monkeypatch.setenv("PIPELINE_SHOW", "pm")
    monkeypatch.setitem(common.SHOWS["pm"], "sources_path", fake_sources)

    config = collect.load_config()

    assert "agile" in config["topics"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && python -m pytest tests/test_collect.py -v`
Expected: FAIL — `load_config()` still reads the hardcoded tech `CONFIG_PATH`, so `"agile"` isn't in its topics.

- [ ] **Step 3: Parameterize `collect.py`**

Replace line 30:
```python
from common import CONFIG_PATH, episode_date, ensure_data_dir, get_logger  # noqa: E402
```
with:
```python
from common import artifact_path, current_show, episode_date, ensure_data_dir, get_logger  # noqa: E402
```

Replace lines 38–40:
```python
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```
with:
```python
def load_config() -> dict:
    with open(current_show()["sources_path"], "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

Replace lines 243–244:
```python
    out_dir = ensure_data_dir()
    out_path = out_dir / f"collected_{result['date']}.json"
```
with:
```python
    ensure_data_dir()
    out_path = artifact_path("collected", "json", result["date"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd pipeline && python -m pytest tests/test_collect.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/collector/collect.py pipeline/tests/test_collect.py
git commit -m "Parameterize collect.py by show (sources path, output filename)"
```

---

## Task 4: Parameterize `tts/synthesize.py` by show

**Files:**
- Modify: `pipeline/tts/synthesize.py`

**Interfaces:**
- Consumes: `common.artifact_path()` (Task 1).
- Produces: no new public function — `main()` now reads/writes via `artifact_path`, output filenames unchanged for the tech show (suffix `""`).

- [ ] **Step 1: Update the import**

Replace line 27:
```python
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402
```
with:
```python
from common import artifact_path, ensure_data_dir, episode_date, get_logger  # noqa: E402
```

- [ ] **Step 2: Parameterize `main()`**

Replace lines 84–96:
```python
    data_dir = ensure_data_dir()
    date = episode_date()
    script_path = data_dir / f"script_{date}.md"
    if not script_path.exists():
        raise SystemExit(f"Missing {script_path} — run scripting/generate_script.py first.")

    text = script_path.read_text(encoding="utf-8")
    lang_code = os.environ.get("KOKORO_LANG_CODE", DEFAULT_LANG_CODE)
    voice = os.environ.get("KOKORO_VOICE", DEFAULT_VOICE)

    wav_path = data_dir / f"episode_{date}.wav"
    mp3_path = data_dir / f"episode_{date}.mp3"
    captions_path = data_dir / f"captions_{date}.json"
```
with:
```python
    ensure_data_dir()
    date = episode_date()
    script_path = artifact_path("script", "md", date)
    if not script_path.exists():
        raise SystemExit(f"Missing {script_path} — run scripting/generate_script.py first.")

    text = script_path.read_text(encoding="utf-8")
    lang_code = os.environ.get("KOKORO_LANG_CODE", DEFAULT_LANG_CODE)
    voice = os.environ.get("KOKORO_VOICE", DEFAULT_VOICE)

    wav_path = artifact_path("episode", "wav", date)
    mp3_path = artifact_path("episode", "mp3", date)
    captions_path = artifact_path("captions", "json", date)
```

- [ ] **Step 3: Run the existing synthesize tests to confirm no regression**

Run: `cd pipeline && python -m pytest tests/test_synthesize.py -v`
Expected: PASS (3 tests — they exercise `build_caption_cues` directly, unaffected by this change).

- [ ] **Step 4: Commit**

```bash
git add pipeline/tts/synthesize.py
git commit -m "Parameterize synthesize.py output paths by show"
```

---

## Task 5: Parameterize `video/thumbnail.py` by show

**Files:**
- Modify: `pipeline/video/thumbnail.py`
- Test: `pipeline/tests/test_thumbnail.py`

**Interfaces:**
- Produces: `thumbnail.generate_thumbnail(date, topics, out_path, show_label="Daily Tech Briefing")` (new optional 4th param, default preserves current behavior).

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/test_thumbnail.py`:

```python
def test_generate_thumbnail_uses_show_label_for_empty_topics_fallback(tmp_path):
    out_path = tmp_path / "thumb.png"
    thumbnail.generate_thumbnail("2026-09-08", [], out_path, show_label="Project Manager's Room")
    assert out_path.exists()
```

(This test only asserts the call succeeds with the new parameter — the visual text isn't asserted, matching this file's existing style of checking file existence/size rather than pixel content.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && python -m pytest tests/test_thumbnail.py -v`
Expected: FAIL — `TypeError: generate_thumbnail() got an unexpected keyword argument 'show_label'`.

- [ ] **Step 3: Parameterize `thumbnail.py`**

Replace line 15:
```python
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402
```
with:
```python
from common import artifact_path, current_show, ensure_data_dir, episode_date, get_logger  # noqa: E402
```

Replace lines 57–74 (`generate_thumbnail`):
```python
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
```
with:
```python
def generate_thumbnail(date: str, topics: list[str], out_path: Path, show_label: str = "Daily Tech Briefing") -> None:
    accent = topic_accent_color(topics[0]) if topics else DEFAULT_ACCENT
    bg = tuple(max(0, c - 180) for c in accent)

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, HEIGHT - 220), (WIDTH, HEIGHT)], fill=accent)

    date_font = _load_font(48)
    topics_font = _load_font(64)

    draw.text((60, 50), date, font=date_font, fill=(255, 255, 255))

    topics_text = " - ".join(topics[:3]) if topics else show_label
    draw.text((60, HEIGHT - 180), topics_text, font=topics_font, fill=(20, 20, 20))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
```

Replace `main()` (lines 77–89):
```python
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
```
with:
```python
def main() -> None:
    ensure_data_dir()
    date = episode_date()
    transcript_path = artifact_path("transcript", "json", date)
    if not transcript_path.exists():
        raise SystemExit(f"Missing {transcript_path} — run scripting/generate_script.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]

    out_path = artifact_path("thumbnail", "png", date)
    generate_thumbnail(date, topics, out_path, show_label=current_show()["show_label"])
    log.info("Wrote %s", out_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_thumbnail.py -v`
Expected: PASS (5 tests — the original 4 unaffected since `show_label` defaults to `"Daily Tech Briefing"`, plus the new one).

- [ ] **Step 5: Commit**

```bash
git add pipeline/video/thumbnail.py pipeline/tests/test_thumbnail.py
git commit -m "Parameterize thumbnail.py by show (paths, fallback label)"
```

---

## Task 6: Parameterize `video/metadata.py` by show

**Files:**
- Modify: `pipeline/video/metadata.py`
- Test: `pipeline/tests/test_metadata.py`

**Interfaces:**
- Produces: `metadata.build_metadata_system_prompt(show_label: str) -> str`; `metadata.generate_metadata(date, topics, script, show_label="Daily Tech Briefing") -> dict` (new optional 4th param); `metadata._normalize(data, date, show_label)` (internal, signature changed).

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/test_metadata.py`:

```python
def test_generate_metadata_uses_show_label_in_default_title():
    fake_json = '{"description": "D", "tags": []}'
    with patch("metadata.call_groq", return_value=fake_json):
        result = metadata.generate_metadata("2026-09-08", ["Agile"], "script", show_label="Project Manager's Room")
    assert result["title"] == "Project Manager's Room — 2026-09-08"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pipeline && python -m pytest tests/test_metadata.py -v`
Expected: FAIL — `TypeError: generate_metadata() got an unexpected keyword argument 'show_label'`.

- [ ] **Step 3: Parameterize `metadata.py`**

Replace line 15:
```python
from common import call_groq, ensure_data_dir, episode_date, get_logger  # noqa: E402
```
with:
```python
from common import artifact_path, call_groq, current_show, ensure_data_dir, episode_date, get_logger  # noqa: E402
```

Replace the `METADATA_SYSTEM_PROMPT` constant (lines 26–35):
```python
METADATA_SYSTEM_PROMPT = """You write YouTube metadata for a daily technology news podcast video.
Given the date, topic list, and full narration script for today's episode, produce a JSON object
with exactly these keys:
- "title": a short, specific, compelling title (under 100 characters), mentioning the date and the
  most notable topic(s) - not a generic template.
- "description": 2-4 sentences summarizing what's covered, followed by a line listing the topics.
- "tags": a JSON array of 5-10 relevant lowercase tags (e.g. "java", "spring boot", "kubernetes").

Respond with ONLY the JSON object, no other text, no markdown code fences.
"""
```
with:
```python
def build_metadata_system_prompt(show_label: str) -> str:
    return f"""You write YouTube metadata for "{show_label}", a daily podcast video.
Given the date, topic list, and full narration script for today's episode, produce a JSON object
with exactly these keys:
- "title": a short, specific, compelling title (under 100 characters), mentioning the date and the
  most notable topic(s) - not a generic template.
- "description": 2-4 sentences summarizing what's covered, followed by a line listing the topics.
- "tags": a JSON array of 5-10 relevant lowercase tags (e.g. "java", "spring boot", "kubernetes").

Respond with ONLY the JSON object, no other text, no markdown code fences.
"""
```

Replace `_normalize` (lines 55–77):
```python
def _normalize(data: dict, date: str) -> dict:
    # Never trust the LLM's output shape/length against YouTube's own limits - a
    # missing key, an oversized title, or a non-list tags field costs the day's
    # upload with a bare HTTP 400 and no automatic retry.
    title = str(data.get("title") or f"Daily Tech Briefing — {date}")
```
with:
```python
def _normalize(data: dict, date: str, show_label: str) -> dict:
    # Never trust the LLM's output shape/length against YouTube's own limits - a
    # missing key, an oversized title, or a non-list tags field costs the day's
    # upload with a bare HTTP 400 and no automatic retry.
    title = str(data.get("title") or f"{show_label} — {date}")
```
(rest of `_normalize` unchanged).

Replace `generate_metadata` (lines 80–99):
```python
def generate_metadata(date: str, topics: list[str], script: str) -> dict:
    messages = [
        {"role": "system", "content": METADATA_SYSTEM_PROMPT},
        {"role": "user", "content": build_metadata_prompt(date, topics, script)},
    ]
    raw = call_groq(messages, max_tokens=500)
    try:
        data = _parse_json(raw)
    except json.JSONDecodeError:
        log.warning("Metadata response wasn't valid JSON - retrying once...")
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": "That wasn't valid JSON. Respond with ONLY the JSON object, no other text."}
        )
        raw = call_groq(messages, max_tokens=500)
        data = _parse_json(raw)

    result = _normalize(data, date)
    result["description"] = result["description"].rstrip() + DISCLOSURE_LINE
    return result
```
with:
```python
def generate_metadata(date: str, topics: list[str], script: str, show_label: str = "Daily Tech Briefing") -> dict:
    messages = [
        {"role": "system", "content": build_metadata_system_prompt(show_label)},
        {"role": "user", "content": build_metadata_prompt(date, topics, script)},
    ]
    raw = call_groq(messages, max_tokens=500)
    try:
        data = _parse_json(raw)
    except json.JSONDecodeError:
        log.warning("Metadata response wasn't valid JSON - retrying once...")
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": "That wasn't valid JSON. Respond with ONLY the JSON object, no other text."}
        )
        raw = call_groq(messages, max_tokens=500)
        data = _parse_json(raw)

    result = _normalize(data, date, show_label)
    result["description"] = result["description"].rstrip() + DISCLOSURE_LINE
    return result
```

Replace `main()` (lines 102–116):
```python
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
```
with:
```python
def main() -> None:
    ensure_data_dir()
    date = episode_date()
    transcript_path = artifact_path("transcript", "json", date)
    if not transcript_path.exists():
        raise SystemExit(f"Missing {transcript_path} — run scripting/generate_script.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]

    result = generate_metadata(date, topics, transcript["script"], show_label=current_show()["show_label"])

    out_path = artifact_path("youtube_metadata", "json", date)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("Wrote %s: %s", out_path, result["title"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_metadata.py -v`
Expected: PASS (8 tests — the original 7 unaffected since `show_label` defaults to `"Daily Tech Briefing"`, plus the new one).

- [ ] **Step 5: Commit**

```bash
git add pipeline/video/metadata.py pipeline/tests/test_metadata.py
git commit -m "Parameterize metadata.py by show (paths, title/prompt label)"
```

---

## Task 7: Parameterize `video/make_cover.py`; generate and commit `cover_pm.png`

**Files:**
- Modify: `pipeline/video/make_cover.py`
- Create (binary asset): `pipeline/video/assets/cover_pm.png`

**Interfaces:**
- Produces: `make_cover.build_cover(show: str = "tech") -> None`.

This script is a one-time manual asset generator (not part of the daily pipeline — see its own docstring), so it gets a small local `COVERS` dict rather than reusing `common.SHOWS` (title/subtitle/accent-color are cover-art-specific, not pipeline plumbing).

- [ ] **Step 1: Parameterize `make_cover.py`**

Replace the whole file content from `WIDTH, HEIGHT = 1920, 1080` through the end of `build_cover()` (lines 12–55) with:

```python
import argparse

WIDTH, HEIGHT = 1920, 1080
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

COVERS = {
    "tech": {
        "bg_top": (13, 16, 36),
        "bg_bottom": (26, 31, 58),
        "accent": (124, 156, 255),
        "title": "Daily Tech Briefing",
        "subtitle": "Java - Spring Boot - Kubernetes - Cloud - and more",
        "out_name": "cover.png",
    },
    "pm": {
        "bg_top": (23, 21, 15),
        "bg_bottom": (46, 40, 26),
        "accent": (212, 175, 55),
        "title": "Project Manager's Room",
        "subtitle": "Agile - Delivery - Risk - Stakeholders - Leadership",
        "out_name": "cover_pm.png",
    },
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


def build_cover(show: str = "tech") -> None:
    cfg = COVERS[show]
    bg_top, bg_bottom, accent = cfg["bg_top"], cfg["bg_bottom"], cfg["accent"]

    img = Image.new("RGB", (WIDTH, HEIGHT), bg_top)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(int(bg_top[i] + (bg_bottom[i] - bg_top[i]) * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    title_font = _load_font(96)
    subtitle_font = _load_font(40)

    title = cfg["title"]
    subtitle = cfg["subtitle"]

    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(((WIDTH - title_w) / 2, HEIGHT / 2 - 100), title, font=title_font, fill=(255, 255, 255))

    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(((WIDTH - subtitle_w) / 2, HEIGHT / 2 + 30), subtitle, font=subtitle_font, fill=accent)

    out_path = ASSETS_DIR / cfg["out_name"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", choices=list(COVERS), default="tech")
    args = parser.parse_args()
    build_cover(args.show)
```

(The file's top-level docstring and `from pathlib import Path` / `from PIL import Image, ImageDraw, ImageFont` imports, lines 1–10, stay unchanged.)

- [ ] **Step 2: Run it locally to generate and verify both covers**

Run: `cd pipeline/video && python make_cover.py --show tech && python make_cover.py --show pm`
Expected: `Wrote .../assets/cover.png` then `Wrote .../assets/cover_pm.png`, both 1920x1080 PNGs. Open `cover_pm.png` to visually confirm the "Project Manager's Room" title/subtitle render legibly (this is manual — no automated visual test exists for this file, matching its existing one-time-manual-script nature).

- [ ] **Step 3: Commit the new asset (and the regenerated tech cover, which should be pixel-identical)**

```bash
git add pipeline/video/make_cover.py pipeline/video/assets/cover_pm.png
git commit -m "Parameterize make_cover.py by show; add cover_pm.png asset"
```

---

## Task 8: Parameterize `video/build_video.py` by show

**Files:**
- Modify: `pipeline/video/build_video.py`

**Interfaces:**
- Consumes: `common.artifact_path`, `common.current_show` (Task 1); `pipeline/video/assets/cover_pm.png` (Task 7).
- Produces: no new public function — `main()` reads/writes via `artifact_path` and resolves the cover image per show.

- [ ] **Step 1: Update the import and cover-image resolution**

Replace line 18:
```python
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402
```
with:
```python
from common import artifact_path, current_show, ensure_data_dir, episode_date, get_logger  # noqa: E402
```

Replace line 22:
```python
COVER_IMAGE = Path(__file__).resolve().parent / "assets" / "cover.png"
```
with:
```python
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def cover_image_path() -> Path:
    return ASSETS_DIR / current_show()["cover_image"]
```

Update `render_video`'s reference to `COVER_IMAGE` (line 61, `"-i", str(COVER_IMAGE),`) to `"-i", str(cover_image_path()),`.

- [ ] **Step 2: Parameterize `main()`**

Replace lines 81–96:
```python
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
```
with:
```python
def main() -> None:
    ensure_data_dir()
    date = episode_date()
    mp3_path = artifact_path("episode", "mp3", date)
    captions_path = artifact_path("captions", "json", date)
    if not mp3_path.exists() or not captions_path.exists():
        raise SystemExit(f"Missing episode audio/captions for {date} — run tts/synthesize.py first.")
    cover_path = cover_image_path()
    if not cover_path.exists():
        raise SystemExit(f"Missing {cover_path} — run video/make_cover.py once and commit the result.")

    cues = json.loads(captions_path.read_text(encoding="utf-8"))
    srt_path = artifact_path("captions", "srt", date)
    srt_path.write_text(build_srt(cues), encoding="utf-8")

    video_path = artifact_path("video", "mp4", date)
    render_video(mp3_path, srt_path, video_path)
    log.info("Wrote %s (%.1f MB)", video_path, video_path.stat().st_size / 1_000_000)
```

- [ ] **Step 3: Run the existing build_video tests to confirm no regression**

Run: `cd pipeline && python -m pytest tests/test_build_video.py -v`
Expected: PASS (5 tests — `format_srt_timestamp`, `build_srt`, `render_video`, `temp_render_path` are all exercised with explicit paths passed as arguments, unaffected by `main()`'s changes).

- [ ] **Step 4: Commit**

```bash
git add pipeline/video/build_video.py
git commit -m "Parameterize build_video.py paths and cover image by show"
```

---

## Task 9: Parameterize `publish/publish.py` by show

**Files:**
- Modify: `pipeline/publish/publish.py`

**Interfaces:**
- Consumes: `common.artifact_path`, `common.current_show` (Task 1).
- Produces: no new public function — `upload_audio`'s blob path, `write_episode_doc`'s collection, and `send_notification`'s topic are all show-parameterized; tech show defaults are unchanged (`episodes/episode_<date>.mp3`, collection `episodes`, topic `daily_episode`).

- [ ] **Step 1: Update the import**

Replace line 27:
```python
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402
```
with:
```python
from common import artifact_path, current_show, ensure_data_dir, episode_date, get_logger  # noqa: E402
```

- [ ] **Step 2: Parameterize `upload_audio`, `write_episode_doc`, `send_notification`**

Replace lines 53–68 (`upload_audio`):
```python
def upload_audio(mp3_path: Path, date: str) -> str:
    """Uploads the MP3 and returns a permanent public Firebase download URL."""
    from firebase_admin import storage

    bucket = storage.bucket()
    blob_path = f"episodes/episode_{date}.mp3"
    blob = bucket.blob(blob_path)
```
with:
```python
def upload_audio(mp3_path: Path, date: str) -> str:
    """Uploads the MP3 and returns a permanent public Firebase download URL."""
    from firebase_admin import storage

    bucket = storage.bucket()
    blob_path = f"{current_show()['storage_prefix']}/{mp3_path.name}"
    blob = bucket.blob(blob_path)
```
(rest of `upload_audio` unchanged).

Replace lines 71–84 (`write_episode_doc`):
```python
def write_episode_doc(date: str, audio_url: str, transcript: dict) -> None:
    from firebase_admin import firestore

    db = firestore.client()
    db.collection("episodes").document(date).set(
```
with:
```python
def write_episode_doc(date: str, audio_url: str, transcript: dict) -> None:
    from firebase_admin import firestore

    db = firestore.client()
    db.collection(current_show()["firestore_collection"]).document(date).set(
```
(rest unchanged).

Replace lines 87–99 (`send_notification`):
```python
def send_notification(date: str, audio_url: str, topics: list[str]) -> None:
    from firebase_admin import messaging

    topics_preview = ", ".join(topics[:4]) if topics else "today's tech world"
    message = messaging.Message(
        topic="daily_episode",
        notification=messaging.Notification(
            title="Your daily tech briefing is ready",
            body=f"Covering: {topics_preview}",
        ),
        data={"date": date, "audio_url": audio_url},
    )
    messaging.send(message)
```
with:
```python
def send_notification(date: str, audio_url: str, topics: list[str]) -> None:
    from firebase_admin import messaging

    show = current_show()
    topics_preview = ", ".join(topics[:4]) if topics else "today's update"
    message = messaging.Message(
        topic=show["push_topic"],
        notification=messaging.Notification(
            title=f"Your {show['show_label']} is ready",
            body=f"Covering: {topics_preview}",
        ),
        data={"date": date, "audio_url": audio_url},
    )
    messaging.send(message)
```

- [ ] **Step 3: Parameterize `main()`**

Replace lines 102–109:
```python
def main() -> None:
    data_dir = ensure_data_dir()
    date = episode_date()
    mp3_path = data_dir / f"episode_{date}.mp3"
    transcript_path = data_dir / f"transcript_{date}.json"

    if not mp3_path.exists() or not transcript_path.exists():
        raise SystemExit(f"Missing episode artifacts for {date} — run the earlier pipeline steps first.")
```
with:
```python
def main() -> None:
    ensure_data_dir()
    date = episode_date()
    mp3_path = artifact_path("episode", "mp3", date)
    transcript_path = artifact_path("transcript", "json", date)

    if not mp3_path.exists() or not transcript_path.exists():
        raise SystemExit(f"Missing episode artifacts for {date} — run the earlier pipeline steps first.")
```

- [ ] **Step 4: Verify the module still imports cleanly**

Run: `cd pipeline && python -c "import sys; sys.path.insert(0, 'publish'); sys.path.insert(0, '.'); import publish; print('ok')"`
Expected: `ok` (no test file exists for `publish.py` today — it has no unit tests to run since every function needs live Firebase credentials; this import-sanity check is the existing project's own level of coverage for this file).

- [ ] **Step 5: Commit**

```bash
git add pipeline/publish/publish.py
git commit -m "Parameterize publish.py by show (paths, Firestore collection, storage prefix, push topic)"
```

---

## Task 10: Parameterize `publish/youtube_publish.py` by show

**Files:**
- Modify: `pipeline/publish/youtube_publish.py`
- Test: `pipeline/tests/test_youtube_publish.py`

**Interfaces:**
- Consumes: `common.artifact_path`, `common.current_show` (Task 1); `metadata.generate_metadata(..., show_label=...)` (Task 6); `thumbnail.generate_thumbnail(..., show_label=...)` (Task 5).
- Produces: `youtube_publish.youtube_configured()` and `main()` now resolve the playlist env var, category id, and all data paths from `current_show()`; existing tests (which all run under the default `"tech"` show) keep passing unchanged.

- [ ] **Step 1: Run the existing tests to confirm the baseline**

Run: `cd pipeline && python -m pytest tests/test_youtube_publish.py -v`
Expected: PASS (5 tests) — this is the regression baseline.

- [ ] **Step 2: Update the import and `youtube_configured`**

Replace line 18:
```python
from common import ensure_data_dir, episode_date, get_logger  # noqa: E402
```
with:
```python
from common import artifact_path, current_show, ensure_data_dir, episode_date, get_logger  # noqa: E402
```

Replace lines 24–36:
```python
SCOPES = ["https://www.googleapis.com/auth/youtube"]
CATEGORY_SCIENCE_AND_TECHNOLOGY = "28"


class YouTubeAuthError(Exception):
    """Raised when the stored OAuth refresh token is missing/expired/revoked."""


def youtube_configured() -> bool:
    return all(
        os.environ.get(var)
        for var in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_PLAYLIST_ID")
    )
```
with:
```python
SCOPES = ["https://www.googleapis.com/auth/youtube"]


class YouTubeAuthError(Exception):
    """Raised when the stored OAuth refresh token is missing/expired/revoked."""


def youtube_configured() -> bool:
    return all(
        os.environ.get(var)
        for var in (
            "YOUTUBE_CLIENT_ID",
            "YOUTUBE_CLIENT_SECRET",
            "YOUTUBE_REFRESH_TOKEN",
            current_show()["youtube_playlist_env"],
        )
    )
```

- [ ] **Step 3: Parameterize `upload_video`'s category id**

Replace line 95 (inside `upload_video`'s `body` dict):
```python
            "categoryId": CATEGORY_SCIENCE_AND_TECHNOLOGY,
```
with:
```python
            "categoryId": current_show()["youtube_category_id"],
```

- [ ] **Step 4: Parameterize `main()`**

Replace lines 134–151:
```python
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
```
with:
```python
def main() -> None:
    ensure_data_dir()
    date = episode_date()
    show = current_show()

    if not youtube_configured():
        log.warning(
            "YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN/%s not fully set - skipping YouTube publish.",
            show["youtube_playlist_env"],
        )
        return

    video_path = artifact_path("video", "mp4", date)
    transcript_path = artifact_path("transcript", "json", date)
    if not video_path.exists() or not transcript_path.exists():
        raise SystemExit(f"Missing video/transcript for {date} — run video/build_video.py first.")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    topics = [t["topic"] for t in transcript["topics_covered"]]
    playlist_id = os.environ[show["youtube_playlist_env"]]
```

Replace lines 168–172:
```python
    thumbnail_path = data_dir / f"thumbnail_{date}.png"
    generate_thumbnail(date, topics, thumbnail_path)

    result = generate_metadata(date, topics, transcript["script"])
    (data_dir / f"youtube_metadata_{date}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
```
with:
```python
    thumbnail_path = artifact_path("thumbnail", "png", date)
    generate_thumbnail(date, topics, thumbnail_path, show_label=show["show_label"])

    result = generate_metadata(date, topics, transcript["script"], show_label=show["show_label"])
    artifact_path("youtube_metadata", "json", date).write_text(json.dumps(result, indent=2), encoding="utf-8")
```

- [ ] **Step 5: Run tests to verify they still pass**

Run: `cd pipeline && python -m pytest tests/test_youtube_publish.py -v`
Expected: PASS (5 tests, unchanged — all run under the default `PIPELINE_SHOW` unset → `"tech"`, whose `youtube_playlist_env` is `"YOUTUBE_PLAYLIST_ID"` and `youtube_category_id` is `"28"`, matching what the tests already set up).

- [ ] **Step 6: Commit**

```bash
git add pipeline/publish/youtube_publish.py
git commit -m "Parameterize youtube_publish.py by show (paths, playlist env var, category id)"
```

---

## Task 11: PM source config

**Files:**
- Create: `pipeline/config/sources_pm.yaml`

**Interfaces:**
- Consumed by: `generate_script_pm.py` (Task 12) via `collect.py`'s already-parameterized `load_config()` (Task 3).

- [ ] **Step 1: Write the file**

Create `pipeline/config/sources_pm.yaml`:

```yaml
# Topic -> source config for "Project Manager's Room" (the PM/Delivery show).
# Same shape as ../sources.yaml. RSS entries below are BEST-EFFORT and UNVERIFIED —
# attempted verification during design (2026-09-08) was inconclusive (Agile Alliance
# and Scrum.org didn't resolve to parseable feed XML via fetch; PMI blocked the fetch
# with a 403, most likely bot-blocking rather than a real paywall). Confirm/replace
# these URLs in a browser before the first real run. The collector skips a broken
# feed silently (with a log line) rather than failing the whole run, same as sources.yaml.
#
# No PMI login/credentials are used here or anywhere in this pipeline (see design spec
# for why) — the PMI blog entry below is the public blog only.

topics:
  agile_delivery:
    label: "Agile & Scrum Delivery"
    rss: []
    reddit_subs: ["agile", "scrum"]
    hn_query: "agile delivery"

  risk_stakeholder:
    label: "Risk & Stakeholder Management"
    rss: []
    reddit_subs: ["projectmanagement"]
    hn_query: "project risk management"

  pmi_pmbok:
    label: "PMI & PMBOK News"
    description: >
      News from the Project Management Institute and PMBOK-related certification/standards
      updates. Source is PMI's public blog (not member-gated content) - see note above.
    rss:
      - https://www.pmi.org/blog/rss  # UNVERIFIED - confirm before relying on it
    reddit_subs: ["pmp"]
    hn_query: "PMI project management"

  hybrid_remote_delivery:
    label: "Hybrid & Remote Team Delivery"
    rss: []
    reddit_subs: ["projectmanagement", "agile"]
    hn_query: "remote team delivery"

  pm_tooling:
    label: "PM Tooling (Jira, MS Project, Azure DevOps)"
    rss:
      - https://www.agilealliance.org/feed/  # UNVERIFIED - confirm before relying on it
      - https://www.scrum.org/resources/blog/rss  # UNVERIFIED - confirm before relying on it
    reddit_subs: ["projectmanagement"]
    hn_query: "project management tools"

# Collection window, in hours, applied uniformly to all sources above.
lookback_hours: 24

# Cap on raw items collected per topic before ranking/summarization.
max_items_per_topic: 8
```

- [ ] **Step 2: Sanity-check the YAML parses**

Run: `cd pipeline && python -c "import yaml; print(list(yaml.safe_load(open('config/sources_pm.yaml'))['topics'].keys()))"`
Expected: `['agile_delivery', 'risk_stakeholder', 'pmi_pmbok', 'hybrid_remote_delivery', 'pm_tooling']`

- [ ] **Step 3: Commit**

```bash
git add pipeline/config/sources_pm.yaml
git commit -m "Add PM/Delivery show source config"
```

---

## Task 12: PM script generator (`generate_script_pm.py`)

**Files:**
- Create: `pipeline/scripting/generate_script_pm.py`
- Test: create `pipeline/tests/test_generate_script_pm_safety.py`

**Interfaces:**
- Consumes: `common.artifact_path`, `common.episode_date`, `common.get_logger`, `common.call_groq`, `common.check_segment_safety`, `common.retry_with_safety_reminder`, `common.ContentSafetyError` (Task 1 & 2); `generate_script.allocate_word_budgets` (Task 2, imported not copied).
- Produces: `generate_script_pm.story_theme_for_date(date_str: str) -> str`, `generate_script_pm.pick_deep_dive(topics_with_items) -> tuple[str, dict, str]`, `generate_script_pm.generate_latest_updates_segment(topic_label, items, target_words, description="") -> str`, `generate_script_pm.generate_deep_dive_segment(topic_label, anchor_item, target_words) -> str`, `generate_script_pm.generate_story_segment(theme, target_words) -> str`, `generate_script_pm.main()`.

> **Note on the "no real names" rule:** enforcement here is prompt-only (the LLM is instructed not to use real company/person names), not code-verified — matching how this codebase already trusts prompted instructions for its other content rules (e.g. "don't invent facts" has no code-level check either). `# ponytail: no-real-names rule is prompt-only; add a named-entity check here if this proves unreliable in practice.`

- [ ] **Step 1: Write the failing safety test**

Create `pipeline/tests/test_generate_script_pm_safety.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripting"))
import generate_script_pm  # noqa: E402


def test_story_theme_for_date_is_deterministic_and_cycles():
    theme_a = generate_script_pm.story_theme_for_date("2026-01-01")
    theme_b = generate_script_pm.story_theme_for_date("2026-01-01")
    assert theme_a == theme_b
    assert theme_a in generate_script_pm.STORY_THEMES


def test_pick_deep_dive_selects_topic_with_most_items_and_longest_item_as_anchor():
    topics_with_items = [
        ("Agile & Scrum Delivery", [{"title": "A", "snippet": "short"}], ""),
        (
            "Risk & Stakeholder Management",
            [
                {"title": "B", "snippet": "short"},
                {"title": "C", "snippet": "a much longer and more detailed snippet here"},
            ],
            "",
        ),
    ]
    label, anchor, description = generate_script_pm.pick_deep_dive(topics_with_items)
    assert label == "Risk & Stakeholder Management"
    assert anchor["title"] == "C"


def test_generate_story_segment_retries_once_then_raises_if_still_flagged():
    calls = {"n": 0}

    def fake_call_groq(messages, max_tokens=1200):
        calls["n"] += 1
        return f"segment text {calls['n']} " + "x " * 300

    with patch("generate_script_pm.call_groq", side_effect=fake_call_groq), \
         patch("generate_script_pm.check_segment_safety", return_value=(False, "FLAGGED: unethical example")):
        try:
            generate_script_pm.generate_story_segment("scope creep", target_words=300)
            assert False, "expected ContentSafetyError"
        except generate_script_pm.ContentSafetyError as e:
            assert e.segment_label == "Story"
            assert "unethical example" in e.reason

    assert calls["n"] == 2


def test_generate_deep_dive_segment_returns_text_when_safe():
    with patch("generate_script_pm.call_groq", return_value="x " * 300), \
         patch("generate_script_pm.check_segment_safety", return_value=(True, "")):
        result = generate_script_pm.generate_deep_dive_segment(
            "Agile & Scrum Delivery", {"title": "T", "snippet": "s", "url": "http://x"}, target_words=300
        )
    assert result == "x " * 300
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_generate_script_pm_safety.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generate_script_pm'`.

- [ ] **Step 3: Write `generate_script_pm.py`**

Create `pipeline/scripting/generate_script_pm.py`:

```python
"""
Turns pipeline/data/collected_pm_<date>.json into a single narrated podcast script for
"Project Manager's Room" (~10 min / ~1,500 words) using Groq - see design spec
docs/superpowers/specs/2026-09-08-pm-delivery-show-design.md.

Structure: intro -> latest updates across PM/delivery sub-topics (~5 min) -> deep dive on
today's biggest item (~2 min) -> a fictional/illustrative story segment (~3 min) -> outro.

Unlike generate_script.py, the story segment is explicitly ALLOWED to invent characters,
dialogue, and scenario (never real company/person names) - the one deliberate exception to
this codebase's "never invent facts" rule, scoped to this one segment only. The story segment
runs every day regardless of news volume, since it isn't sourced from collected items - so
even a quiet PM-news day still produces a real (if shorter) episode, consistent with this
codebase's "don't pad with invented content just to hit a length" rule for sourced segments.

Output:
  pipeline/data/script_pm_<date>.md        - the narration script (fed to TTS)
  pipeline/data/transcript_pm_<date>.json  - script + per-topic source links
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (  # noqa: E402
    ContentSafetyError,
    artifact_path,
    call_groq,
    check_segment_safety,
    episode_date,
    get_logger,
    retry_with_safety_reminder,
)
from generate_script import allocate_word_budgets  # noqa: E402

log = get_logger("scripting_pm")

LATEST_UPDATES_TARGET_WORDS = 750
MIN_SEGMENT_WORDS = 100
MAX_SEGMENT_WORDS = 250
SEGMENT_RETRY_THRESHOLD = 0.5

DEEP_DIVE_TARGET_WORDS = 300
STORY_TARGET_WORDS = 450

STORY_THEMES = [
    "scope creep",
    "stakeholder conflict",
    "vendor and dependency risk",
    "distributed-team friction",
    "burnout and crunch",
    "agile vs. waterfall tension",
    "scope negotiation",
    "communication breakdown",
]

LATEST_UPDATES_SYSTEM_PROMPT = """You are the writer for "Project Manager's Room," a daily
podcast for IT project and delivery managers. You write ONE segment of the show at a time
covering a single PM/delivery sub-topic - not the whole episode. Another process stitches your
segments together with an intro and outro, so do NOT write any "welcome" or "that's it for today"
framing - just dive straight into the sub-topic's news as if the listener is already mid-episode.

Rules:
- Plain, conversational, simple English aimed at a working delivery/project manager.
- For each item, explain what happened, why it matters for someone running delivery day to day,
  and (when the source supports it) which teams/organizations/tools are affected.
- Do not invent facts, company names, or outcomes not supported by the provided items. If you run
  out of genuine substance before hitting the word target, stop rather than pad with filler.
- Continuous spoken narration only - no markdown headers, no bullet points, no segment title (the
  sub-topic name is introduced separately). This text is read aloud by a TTS engine.
- Never include vulgarity, profanity, or sexual content. Never present an unethical practice (e.g.
  manipulating stakeholders, hiding risk from sponsors, exploiting a team through crunch) as
  something to emulate or admire - if a source item is fundamentally about such a practice, report
  it critically or skip it rather than endorsing it.
"""

DEEP_DIVE_SYSTEM_PROMPT = """You are the writer for the "Deep Dive" segment of "Project Manager's
Room," a daily podcast for IT project and delivery managers. You write ONLY this segment - another
process stitches it in, so do NOT write "welcome" or "goodbye" framing, just dive in.

This segment takes the single most significant PM/delivery story collected today and goes deeper
than a news blurb: what happened, the background context a listener might not already know, and
concretely what a working delivery manager should take away from it - a risk to watch for, a
practice to consider, a question to ask on their own project.

Rules:
- Plain, conversational, simple English, but keep the substance real for an experienced audience.
- Do not invent facts, numbers, or outcomes not supported by the provided source material. If the
  source is thin on a detail, speak in the general terms it actually supports.
- Continuous spoken narration only - no markdown headers, no bullet points, no title.
- Never include vulgarity, profanity, or sexual content. Never present an unethical practice as
  something to emulate or admire.
"""


def build_story_system_prompt(theme: str) -> str:
    return f"""You are the writer for the "Story" segment of "Project Manager's Room," a daily
podcast for IT project and delivery managers. You write ONLY this segment - another process
stitches it in, so do NOT write "welcome" or "goodbye" framing, just dive in.

Unlike every other segment on this show, this one is explicitly FICTIONAL and ILLUSTRATIVE: invent
a short, realistic scenario - with characters, dialogue, and a concrete situation - that brings
today's theme to life for a delivery/project manager audience. This is the one segment where you
are allowed, and expected, to invent details.

Today's theme: {theme}

Rules:
- Invent fictional characters and a fictional company/team - generic, plausible names (e.g. "Maria,
  a delivery manager at a mid-sized logistics company"). NEVER use the name of a real, identifiable
  company, product, or person, and never imply the story is a real reported event.
- Ground the scenario in realistic day-to-day project-management detail (a standup, a steering
  committee, a status call, a hallway conversation) so it reads as plausible, not cartoonish.
- End with a brief, concrete takeaway a real delivery manager could apply.
- Continuous spoken narration only - no markdown headers, no bullet points, no title, no "the
  following is fictional" disclaimer text (a separate templated line already introduces it as a
  story before your text plays).
- Never include vulgarity, profanity, or sexual content. Never depict an unethical practice (e.g.
  retaliating against a whistleblower, falsifying status reports, exploiting a team through crunch)
  as something to emulate or admire - if the scenario involves such a practice, show it going wrong
  or being corrected, not rewarded.
"""


INTRO_TEMPLATE = (
    "Here's today's Project Manager's Room briefing for {date}. Coming up: the latest in "
    "{topics}, a closer look at today's biggest story, and a scenario from the field. "
    "Let's get into it."
)
QUIET_DAY_INTRO_TEMPLATE = (
    "Here's today's Project Manager's Room briefing for {date}. It's a quiet day across the "
    "tracked PM and delivery topics, so we're going straight to today's scenario."
)
DEEP_DIVE_TRANSITION = "Now, let's take a closer look at today's biggest story."
STORY_TRANSITION = (
    "Now, a quick scenario — a fictional situation to bring today's theme to life."
)
OUTRO_TEXT = "And that's Project Manager's Room for today. See you tomorrow."


def build_segment_prompt(topic_label: str, items: list[dict], target_words: int, description: str = "") -> str:
    lines = [f"Topic for this segment: {topic_label}"]
    if description:
        lines.append(f"Context on this topic: {description.strip()}")
    lines.append(f"Target length for this segment: about {target_words} words.")
    lines.append("")
    lines.append("Items collected in the last 24 hours for this topic:")
    for item in items:
        lines.append(f"- [{item['source']}] {item['title']} — {item['snippet']} (source: {item['url']})")
    return "\n".join(lines)


def _generate_with_retry_and_safety(
    system_prompt: str,
    user_prompt: str,
    target_words: int,
    segment_label: str,
    retry_reminder: str,
    max_tokens_cap: int = 1600,
) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    max_tokens = min(max_tokens_cap, target_words * 3)
    segment = call_groq(messages, max_tokens=max_tokens)

    word_count = len(segment.split())
    if word_count < target_words * SEGMENT_RETRY_THRESHOLD:
        log.warning(
            "%s segment came back at %d words (target ~%d) - retrying once...",
            segment_label, word_count, target_words,
        )
        messages.append({"role": "assistant", "content": segment})
        messages.append({"role": "user", "content": f"That was only about {word_count} words. {retry_reminder}"})
        segment = call_groq(messages, max_tokens=max_tokens)

    is_safe, reason = check_segment_safety(segment)
    if not is_safe:
        log.warning("%s segment flagged by safety check (%s) - retrying once...", segment_label, reason)
        segment = retry_with_safety_reminder(messages, segment, reason, max_tokens=max_tokens)
        is_safe, reason = check_segment_safety(segment)
        if not is_safe:
            raise ContentSafetyError(segment_label, reason)

    return segment


def generate_latest_updates_segment(topic_label: str, items: list[dict], target_words: int, description: str = "") -> str:
    return _generate_with_retry_and_safety(
        LATEST_UPDATES_SYSTEM_PROMPT,
        build_segment_prompt(topic_label, items, target_words, description),
        target_words,
        topic_label,
        retry_reminder=(
            "Rewrite it, going deeper on why it matters for a working delivery manager, aiming "
            f"for closer to {target_words} words. If there's genuinely not enough substance, get "
            "as close as you honestly can."
        ),
    )


def pick_deep_dive(topics_with_items: list[tuple[str, list[dict], str]]) -> tuple[str, dict, str]:
    """Returns (topic_label, anchor_item, description) for the sub-topic with the most
    collected items that day, anchored on its longest/most detailed item - no extra LLM
    call needed for selection."""
    label, items, description = max(topics_with_items, key=lambda t: len(t[1]))
    anchor = max(items, key=lambda i: len(i.get("snippet", "")))
    return label, anchor, description


def generate_deep_dive_segment(topic_label: str, anchor_item: dict, target_words: int) -> str:
    user_prompt = (
        f"Topic: {topic_label}\n"
        f"Target length: about {target_words} words.\n\n"
        f"The story: [{anchor_item['source']}] {anchor_item['title']} — {anchor_item['snippet']} "
        f"(source: {anchor_item['url']})"
    )
    return _generate_with_retry_and_safety(
        DEEP_DIVE_SYSTEM_PROMPT,
        user_prompt,
        target_words,
        "Deep Dive",
        retry_reminder=(
            f"Go deeper on the background and the concrete takeaway for a delivery manager, "
            f"aiming for closer to {target_words} words. If the source is genuinely thin, get "
            "as close as you honestly can without inventing details."
        ),
    )


def story_theme_for_date(date_str: str) -> str:
    day_of_year = datetime.strptime(date_str, "%Y-%m-%d").timetuple().tm_yday
    return STORY_THEMES[day_of_year % len(STORY_THEMES)]


def generate_story_segment(theme: str, target_words: int) -> str:
    return _generate_with_retry_and_safety(
        build_story_system_prompt(theme),
        f"Write today's story segment now, following the rules above. Target length: about {target_words} words.",
        target_words,
        "Story",
        retry_reminder=(
            f"Rewrite it with more concrete scene detail (dialogue, setting, a specific decision "
            f"point), aiming for closer to {target_words} words, while still following all the "
            "rules above."
        ),
    )


def main() -> None:
    date = episode_date()
    collected_path = artifact_path("collected", "json", date)
    if not collected_path.exists():
        raise SystemExit(f"Missing {collected_path} — run collector/collect.py first.")

    with open(collected_path, "r", encoding="utf-8") as f:
        collected = json.load(f)

    topics_with_items = [
        (t["label"], t["items"], t.get("description", ""))
        for t in collected["topics"].values()
        if t["items"]
    ]

    parts: list[str] = []
    topics_covered: list[dict] = []

    try:
        if topics_with_items:
            budgets = allocate_word_budgets(
                [(label, items) for label, items, _ in topics_with_items],
                target_words=LATEST_UPDATES_TARGET_WORDS,
                min_words=MIN_SEGMENT_WORDS,
                max_words=MAX_SEGMENT_WORDS,
            )
            topic_names = [label for label, _, _ in topics_with_items]
            topics_phrase = ", ".join(topic_names[:-1]) + (
                f", and {topic_names[-1]}" if len(topic_names) > 1 else topic_names[0]
            )
            parts.append(INTRO_TEMPLATE.format(date=date, topics=topics_phrase))

            for label, items, description in topics_with_items:
                log.info(
                    "Generating latest-updates segment: %s (target ~%d words, %d items)",
                    label, budgets[label], len(items),
                )
                parts.append(generate_latest_updates_segment(label, items, budgets[label], description))
                topics_covered.append(
                    {"topic": label, "sources": [{"title": i["title"], "url": i["url"]} for i in items]}
                )

            parts.append(DEEP_DIVE_TRANSITION)
            deep_label, anchor_item, _ = pick_deep_dive(topics_with_items)
            log.info("Generating deep dive: %s", deep_label)
            parts.append(generate_deep_dive_segment(deep_label, anchor_item, DEEP_DIVE_TARGET_WORDS))
            topics_covered.append(
                {"topic": f"Deep Dive: {deep_label}", "sources": [{"title": anchor_item["title"], "url": anchor_item["url"]}]}
            )
        else:
            parts.append(QUIET_DAY_INTRO_TEMPLATE.format(date=date))

        parts.append(STORY_TRANSITION)
        theme = story_theme_for_date(date)
        log.info("Generating story segment (theme: %s)", theme)
        parts.append(generate_story_segment(theme, STORY_TARGET_WORDS))
        topics_covered.append({"topic": f"Story: {theme}", "sources": []})

        parts.append(OUTRO_TEXT)
        script_text = "\n\n".join(parts)
    except ContentSafetyError as e:
        log.error(
            "CONTENT SAFETY CHECK BLOCKED PUBLISH for %s (pm): %s segment - %s. No script/transcript "
            "written; today's PM episode will not publish.",
            date, e.segment_label, e.reason,
        )
        raise SystemExit(f"Content safety check blocked publish for {date} (pm): {e}") from e

    script_path = artifact_path("script", "md", date)
    script_path.write_text(script_text, encoding="utf-8")
    word_count = len(script_text.split())
    log.info("Wrote %s (%d words, ~%.1f min at 150wpm)", script_path, word_count, word_count / 150)

    transcript = {"date": date, "script": script_text, "topics_covered": topics_covered}
    transcript_path = artifact_path("transcript", "json", date)
    transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    log.info("Wrote %s", transcript_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_generate_script_pm_safety.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Also confirm this new file didn't break the tech show's generator (different module, but shares `generate_script.allocate_word_budgets`)**

Run: `cd pipeline && python -m pytest tests/test_generate_script_safety.py -v`
Expected: PASS (5 tests, unchanged from Task 2).

- [ ] **Step 6: Commit**

```bash
git add pipeline/scripting/generate_script_pm.py pipeline/tests/test_generate_script_pm_safety.py
git commit -m "Add PM show script generator (latest updates, deep dive, fictional story segments)"
```

---

## Task 13: `run_pipeline.py --show` dispatch

**Files:**
- Modify: `pipeline/run_pipeline.py`
- Test: `pipeline/tests/test_run_pipeline.py`

**Interfaces:**
- Consumes: `common.SHOWS` (Task 1); `pipeline/scripting/generate_script_pm.py` (Task 12) must exist at `scripting/generate_script_pm.py` for the pm dispatch path to resolve to a real file.
- Produces: `run_pipeline.py` accepts `--show {tech,pm}` (default `tech`) and sets `PIPELINE_SHOW` in `os.environ` before running any stage.

- [ ] **Step 1: Write the failing test**

Append to `pipeline/tests/test_run_pipeline.py`:

```python
import os


def test_main_with_show_pm_sets_env_and_dispatches_pm_script_stage(monkeypatch):
    calls = []

    def fake_run_stage(name, path, required=True):
        calls.append((name, path))
        return True

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--show", "pm", "--skip-publish"])
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)

    run_pipeline.main()

    assert os.environ["PIPELINE_SHOW"] == "pm"
    script_call = next(c for c in calls if c[0] == "generate_script")
    assert script_call[1].endswith("generate_script_pm.py")


def test_main_with_default_show_dispatches_tech_script_stage(monkeypatch):
    calls = []

    def fake_run_stage(name, path, required=True):
        calls.append((name, path))
        return True

    monkeypatch.setattr(run_pipeline, "run_stage", fake_run_stage)
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--skip-publish"])
    monkeypatch.delenv("PIPELINE_SHOW", raising=False)

    run_pipeline.main()

    assert os.environ["PIPELINE_SHOW"] == "tech"
    script_call = next(c for c in calls if c[0] == "generate_script")
    assert script_call[1].endswith("generate_script.py") and not script_call[1].endswith("_pm.py")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_run_pipeline.py -v`
Expected: FAIL — `error: unrecognized arguments: --show pm` (argparse rejects the unknown flag).

- [ ] **Step 3: Add the `--show` flag and dispatch**

Replace line 6 area's import (currently `from common import get_logger  # noqa: E402`) with:
```python
from common import SHOWS, get_logger  # noqa: E402
```
And add `import os` to the existing top-of-file imports (`import argparse`, `import runpy`, `import sys`, `import time`, `from pathlib import Path`) — insert `import os` alphabetically after `import argparse`.

Replace `main()`:
```python
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
```
with:
```python
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-publish", action="store_true", help="Skip the Firebase/YouTube publish stages")
    parser.add_argument("--show", choices=list(SHOWS), default="tech", help="Which show to run (default: tech)")
    args = parser.parse_args()

    os.environ["PIPELINE_SHOW"] = args.show
    script_module_file = SHOWS[args.show]["script_module"].split(".")[-1] + ".py"

    root = Path(__file__).resolve().parent
    run_stage("collect", str(root / "collector" / "collect.py"))
    run_stage("generate_script", str(root / "scripting" / script_module_file))
    run_stage("synthesize", str(root / "tts" / "synthesize.py"))
    run_stage("build_video", str(root / "video" / "build_video.py"), required=False)
    if not args.skip_publish:
        run_stage("publish", str(root / "publish" / "publish.py"))
        run_stage("youtube_publish", str(root / "publish" / "youtube_publish.py"), required=False)
    else:
        log.info("Skipping publish stages (--skip-publish)")

    log.info("Pipeline complete.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_run_pipeline.py -v`
Expected: PASS (7 tests — the original 5 plus the 2 new ones).

- [ ] **Step 5: Run the full pipeline test suite as a final regression check**

Run: `cd pipeline && python -m pytest tests/ -v`
Expected: PASS, all tests across every file touched in Tasks 1–13.

- [ ] **Step 6: Commit**

```bash
git add pipeline/run_pipeline.py pipeline/tests/test_run_pipeline.py
git commit -m "Add --show flag to run_pipeline.py, dispatching the right script generator per show"
```

---

## Task 14: PM show GitHub Actions workflow

**Files:**
- Create: `.github/workflows/daily-pm-episode.yml`

**Interfaces:**
- Consumes: `pipeline/run_pipeline.py --show pm` (Task 13); reuses the tech show's existing secrets plus one new one, `YOUTUBE_PM_PLAYLIST_ID` (you'll need to add this to the repo's Settings → Secrets and variables → Actions before this workflow can publish to YouTube).

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/daily-pm-episode.yml`, copied from `.github/workflows/daily-episode.yml`'s structure with the show-specific pieces changed:

```yaml
name: Project Manager's Room


on:
  schedule:
    # 09:00 UTC ~= 12:00 PM AST - several hours after the tech show's 00:00 UTC run,
    # landing as a distinct midday touchpoint and avoiding scheduler/Groq-rate-limit
    # contention between the two jobs (see design spec's Workflow section).
    - cron: "0 9 * * *"
  workflow_dispatch: {} # allows manual "Run workflow" for testing

permissions:
  contents: write # needed only for the GitHub Release fallback step

jobs:
  build-pm-episode:
    runs-on: ubuntu-latest
    env:
      GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
      GH_API_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}
      REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}
      REDDIT_USER_AGENT: ${{ secrets.REDDIT_USER_AGENT }}
      FIREBASE_SERVICE_ACCOUNT: ${{ secrets.FIREBASE_SERVICE_ACCOUNT }}
      FIREBASE_STORAGE_BUCKET: ${{ secrets.FIREBASE_STORAGE_BUCKET }}
      YOUTUBE_CLIENT_ID: ${{ secrets.YOUTUBE_CLIENT_ID }}
      YOUTUBE_CLIENT_SECRET: ${{ secrets.YOUTUBE_CLIENT_SECRET }}
      YOUTUBE_REFRESH_TOKEN: ${{ secrets.YOUTUBE_REFRESH_TOKEN }}
      YOUTUBE_PM_PLAYLIST_ID: ${{ secrets.YOUTUBE_PM_PLAYLIST_ID }}
      KOKORO_VOICE: am_michael
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install system deps (ffmpeg for WAV -> MP3, espeak-ng for Kokoro's phonemizer, fonts for captions/thumbnail)
        run: sudo apt-get update && sudo apt-get install -y ffmpeg espeak-ng fonts-dejavu-core

      - name: Install PyTorch (CPU-only build - the default PyPI wheel pulls in unused CUDA libs)
        run: pip install torch --index-url https://download.pytorch.org/whl/cpu

      - name: Install Python deps
        run: pip install -r pipeline/requirements.txt

      - name: Run pipeline for the PM show (collect -> script -> TTS -> build_video -> publish -> youtube_publish)
        run: python pipeline/run_pipeline.py --show pm

      - name: Fallback - attach episode to a GitHub Release (only if Firebase isn't configured)
        if: ${{ env.FIREBASE_SERVICE_ACCOUNT == '' }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          DATE=$(date -u +%F)
          gh release delete "episode-pm-$DATE" --yes 2>/dev/null || true
          gh release create "episode-pm-$DATE" \
            pipeline/data/episode_pm_*.mp3 \
            pipeline/data/transcript_pm_*.json \
            --title "Project Manager's Room - $DATE" \
            --notes "Automated PM/Delivery episode. Firebase publish was not configured, so the app should poll this release."
```

- [ ] **Step 2: Validate the YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/daily-pm-episode.yml')); print('valid yaml')"`
Expected: `valid yaml`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/daily-pm-episode.yml
git commit -m "Add daily-pm-episode workflow (staggered schedule, own YouTube playlist)"
```

(Note for you, not part of this task's automation: add the `YOUTUBE_PM_PLAYLIST_ID` secret in GitHub before relying on this workflow to actually upload — same one-time manual step as the original `YOUTUBE_PLAYLIST_ID` setup in the README.)

---

## Task 15: Android — parameterize `EpisodeRepository` by show, fix the release-tag filter bug

**Files:**
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeRepository.kt`

**Interfaces:**
- Produces: `enum class Show(val releasesTagRegex: Regex)` with values `TECH`, `PM`; `class EpisodeRepository(val show: Show = Show.TECH)`.

This also fixes a latent bug this feature would otherwise trigger: the current filter `tag_name.startsWith("episode-")` would incorrectly match a future `episode-pm-2026-09-08` release tag too, since it's a prefix match, not an exact-date match.

- [ ] **Step 1: Rewrite `EpisodeRepository.kt`**

Replace the full file content:

```kotlin
package com.shahbaz.dailytechupdates

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Which show a repository instance serves. releasesTagRegex is matched against a
 * GitHub Release's tag_name to pick that show's releases out of the shared release
 * list (this repo also publishes "app-latest" APK releases and, once both shows
 * exist, the other show's dated releases into the same list) - an EXACT match
 * (not a prefix match) is required so "episode-pm-2026-09-08" is never picked up
 * as a TECH release.
 */
enum class Show(val releasesTagRegex: Regex) {
    TECH(Regex("^episode-\\d{4}-\\d{2}-\\d{2}$")),
    PM(Regex("^episode-pm-\\d{4}-\\d{2}-\\d{2}$")),
}

/**
 * Reads the latest episode for [show] straight from GitHub Releases published by
 * pipeline/publish/publish.py's fallback path (used whenever FIREBASE_SERVICE_ACCOUNT
 * isn't configured - see BRD Section 14.5). No auth needed: the repo is public and this
 * is well under GitHub's unauthenticated rate limit for a single-user app checking once
 * in a while.
 *
 * Deliberately does NOT use GET /releases/latest: this repo also publishes an "app-latest"
 * release for APK builds (build-apk.yml) into the same release list, and GitHub's "latest"
 * is whichever release was published most recently repo-wide - not the most recent episode.
 * An APK rebuild after an episode publish would silently make /releases/latest point at the
 * APK release (no audio asset) until the next episode overtakes it. Instead, list all
 * releases and pick the newest one matching this show's tag pattern ourselves.
 *
 * TODO: once Firebase is set up (BRD open item), swap this for a Firestore-backed
 * implementation with real push notifications instead of check-on-open polling.
 */
class EpisodeRepository(val show: Show = Show.TECH) {

    private val releasesUrl =
        "https://api.github.com/repos/Shahbazhk/daily-tech-briefing/releases"

    suspend fun getLatestEpisode(): Episode? = withContext(Dispatchers.IO) {
        val releases = JSONArray(httpGet(releasesUrl))
        var release: JSONObject? = null
        for (i in 0 until releases.length()) {
            val candidate = releases.getJSONObject(i)
            val tag = candidate.optString("tag_name")
            if (show.releasesTagRegex.matches(tag)) {
                if (release == null || tag > release!!.getString("tag_name")) {
                    release = candidate
                }
            }
        }
        val chosen = release ?: return@withContext null
        val assets = chosen.getJSONArray("assets")

        var audioUrl = ""
        var transcriptUrl = ""
        for (i in 0 until assets.length()) {
            val asset = assets.getJSONObject(i)
            val name = asset.getString("name")
            val url = asset.getString("browser_download_url")
            if (name.endsWith(".mp3")) audioUrl = url
            if (name.startsWith("transcript_") && name.endsWith(".json")) transcriptUrl = url
        }
        if (audioUrl.isEmpty()) return@withContext null

        var date = chosen.optString("tag_name", "").removePrefix("episode-").removePrefix("pm-")
        var script = ""
        var topics = emptyList<String>()
        if (transcriptUrl.isNotEmpty()) {
            val transcript = JSONObject(httpGet(transcriptUrl))
            date = transcript.optString("date", date)
            script = transcript.optString("script", "")
            transcript.optJSONArray("topics_covered")?.let { topicsArray ->
                topics = (0 until topicsArray.length()).map {
                    topicsArray.getJSONObject(it).optString("topic")
                }
            }
        }

        Episode(date = date, audioUrl = audioUrl, topicsCovered = topics, script = script)
    }

    private fun httpGet(urlString: String): String {
        val connection = URL(urlString).openConnection() as HttpURLConnection
        connection.setRequestProperty("Accept", "application/vnd.github+json")
        connection.connectTimeout = 15_000
        connection.readTimeout = 15_000
        return try {
            connection.inputStream.bufferedReader().use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }
}
```

(Only three things changed from the original: the new `Show` enum, the constructor now taking `val show: Show = Show.TECH` — the default preserves every existing no-arg `EpisodeRepository()` call site — and the tag match switching from `startsWith("episode-")` to `show.releasesTagRegex.matches(tag)`, plus the date-extraction fallback handling the `episode-pm-` prefix too.)

- [ ] **Step 2: Verify the module compiles**

Run: `cd android-app && ./gradlew compileDebugKotlin` (or `gradlew.bat compileDebugKotlin` if running under Windows PowerShell directly rather than Git Bash)
Expected: `BUILD SUCCESSFUL`. (No Kotlin unit test suite exists in this project today to run instead — this compile check is this file's existing level of automated verification.)

- [ ] **Step 3: Commit**

```bash
git add android-app/app/src/main/java/com/shahbaz/dailytechupdates/EpisodeRepository.kt
git commit -m "Parameterize EpisodeRepository by show; fix release-tag prefix-match bug"
```

---

## Task 16: Android — show toggle in `MainActivity`

**Files:**
- Modify: `android-app/app/src/main/res/layout/activity_main.xml`
- Modify: `android-app/app/src/main/res/values/strings.xml`
- Modify: `android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt`

**Interfaces:**
- Consumes: `EpisodeRepository(show: Show)`, `Show.TECH`/`Show.PM` (Task 15).

- [ ] **Step 1: Add the toggle buttons to the layout**

In `android-app/app/src/main/res/layout/activity_main.xml`, insert this `LinearLayout` immediately after the opening `<androidx.constraintlayout.widget.ConstraintLayout ...>` tag (before the `dateText` `TextView`):

```xml
    <LinearLayout
        android:id="@+id/showToggle"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:orientation="horizontal"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent">

        <Button
            android:id="@+id/techShowButton"
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="1"
            android:text="@string/show_tech" />

        <Button
            android:id="@+id/pmShowButton"
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="1"
            android:text="@string/show_pm" />

    </LinearLayout>

```

Then change the `dateText` `TextView`'s constraint from:
```xml
        app:layout_constraintTop_toTopOf="parent"
```
to:
```xml
        android:layout_marginTop="16dp"
        app:layout_constraintTop_toBottomOf="@id/showToggle"
```
(everything else in the layout file is unchanged — `topicsText`, `statusText`, and `playPauseButton` keep their existing constraints, which are all relative to `dateText`/`topicsText`, not to `parent`, so they shift down automatically).

- [ ] **Step 2: Add the new strings**

In `android-app/app/src/main/res/values/strings.xml`, add two entries (after `<string name="app_name">...`):
```xml
    <string name="show_tech">Tech Briefing</string>
    <string name="show_pm">Project Manager\'s Room</string>
```

- [ ] **Step 3: Wire up the toggle in `MainActivity.kt`**

Replace the whole file content:

```kotlin
package com.shahbaz.dailytechupdates

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import com.shahbaz.dailytechupdates.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var player: ExoPlayer
    private var repository = EpisodeRepository(Show.TECH)
    private var isPlaying = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        player = ExoPlayer.Builder(this).build()

        binding.playPauseButton.setOnClickListener { togglePlayback() }
        binding.statusText.setOnClickListener { loadTodayEpisode() }
        binding.techShowButton.setOnClickListener { switchShow(Show.TECH) }
        binding.pmShowButton.setOnClickListener { switchShow(Show.PM) }

        loadTodayEpisode()
    }

    private fun switchShow(show: Show) {
        if (repository.show == show) return
        player.pause()
        isPlaying = false
        binding.playPauseButton.text = getString(R.string.play)
        repository = EpisodeRepository(show)
        loadTodayEpisode()
    }

    private fun loadTodayEpisode() {
        binding.statusText.text = getString(R.string.loading_episode)
        lifecycleScope.launch {
            val episode = try {
                repository.getLatestEpisode()
            } catch (e: Exception) {
                null
            }
            if (episode == null || episode.audioUrl.isEmpty()) {
                binding.statusText.text = getString(R.string.no_episode_yet)
                return@launch
            }
            binding.dateText.text = episode.date
            binding.topicsText.text = episode.topicsCovered.joinToString(" • ")
            binding.statusText.text = getString(R.string.ready_to_play)
            player.setMediaItem(MediaItem.fromUri(episode.audioUrl))
            player.prepare()
        }
    }

    private fun togglePlayback() {
        isPlaying = !isPlaying
        if (isPlaying) {
            player.play()
            binding.playPauseButton.text = getString(R.string.pause)
        } else {
            player.pause()
            binding.playPauseButton.text = getString(R.string.play)
        }
    }

    override fun onDestroy() {
        player.release()
        super.onDestroy()
    }
}
```

(Changes from the original: `repository` becomes `var` initialized to `EpisodeRepository(Show.TECH)`, two new button click listeners, and the new `switchShow` function. `loadTodayEpisode`, `togglePlayback`, and `onDestroy` are unchanged.)

- [ ] **Step 4: Verify the app builds**

Run: `cd android-app && ./gradlew assembleDebug` (or `gradlew.bat assembleDebug`)
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 5: Manual smoke test**

Run the app on a device/emulator (Android Studio, or `./gradlew installDebug` + launch manually). Confirm: the two toggle buttons appear above the date/topics text; tapping "Project Manager's Room" shows "No episode yet" (since no PM episode has been published yet at this point in the rollout) without crashing; tapping back to "Tech Briefing" still loads the existing tech episode correctly.

- [ ] **Step 6: Commit**

```bash
git add android-app/app/src/main/res/layout/activity_main.xml android-app/app/src/main/res/values/strings.xml android-app/app/src/main/java/com/shahbaz/dailytechupdates/MainActivity.kt
git commit -m "Add show toggle to MainActivity for the PM show"
```

---

## Rollout notes (manual steps, not part of the automated tasks above)

1. Before Task 14's workflow can publish to YouTube: create the "Project Manager's Room" playlist on the same YouTube channel, note its playlist ID, add it as the `YOUTUBE_PM_PLAYLIST_ID` GitHub Actions secret.
2. Before Task 11's source config goes live: open the three RSS URLs marked UNVERIFIED in a browser and confirm or replace them.
3. First real run: trigger `daily-pm-episode.yml` manually via **Actions → Run workflow** (same pattern as the existing tech show) rather than waiting for the 09:00 UTC cron, to confirm the whole chain end-to-end before relying on the schedule.
