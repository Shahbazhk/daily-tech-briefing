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
