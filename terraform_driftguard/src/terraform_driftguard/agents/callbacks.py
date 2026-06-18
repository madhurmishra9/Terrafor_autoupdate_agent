"""Pipeline-level callbacks: state clearing and eval-artifact capture."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from ..common.config import get_config
from ..common.logging_setup import get_logger
from ..common.state import ALL_KEYS, clear_pipeline_state

logger = get_logger(__name__)


def cb_before_pipeline(callback_context: Any) -> None:
    """Clear all pipeline state keys before the pipeline runs."""
    clear_pipeline_state(callback_context.state)


def cb_after_pipeline(callback_context: Any) -> None:
    """Write an eval artifact of the final state when CAPTURE_ENABLED=true."""
    cfg = get_config()
    if not cfg.pipeline.capture_enabled:
        return
    os.makedirs(cfg.pipeline.capture_dir, exist_ok=True)
    state = callback_context.state
    snapshot = {k: state.get(k) for k in ALL_KEYS}
    fname = os.path.join(cfg.pipeline.capture_dir, f"run-{int(time.time())}.json")
    with open(fname, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, default=str)
    logger.info("Wrote eval artifact: %s", fname)
