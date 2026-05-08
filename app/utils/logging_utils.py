from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(base_dir: str | Path) -> logging.Logger:
    logs_dir = Path(base_dir) / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / "app.log"

    logger = logging.getLogger("reliability_app")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
