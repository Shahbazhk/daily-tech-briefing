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
