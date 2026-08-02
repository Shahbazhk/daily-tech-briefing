"""
Runs the full daily pipeline: collect -> generate_script -> synthesize -> publish.

Usage:
  python run_pipeline.py                 # run all stages
  python run_pipeline.py --skip-publish  # everything except the Firebase publish step
                                          # (handy for local testing without Firebase creds)
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_logger  # noqa: E402

log = get_logger("pipeline")


def run_stage(name: str, module_path: str) -> None:
    import runpy

    log.info("=== Stage: %s ===", name)
    start = time.time()
    runpy.run_path(module_path, run_name="__main__")
    log.info("=== Done: %s (%.1fs) ===", name, time.time() - start)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-publish", action="store_true", help="Skip the Firebase publish stage")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    run_stage("collect", str(root / "collector" / "collect.py"))
    run_stage("generate_script", str(root / "scripting" / "generate_script.py"))
    run_stage("synthesize", str(root / "tts" / "synthesize.py"))
    if not args.skip_publish:
        run_stage("publish", str(root / "publish" / "publish.py"))
    else:
        log.info("Skipping publish stage (--skip-publish)")

    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
