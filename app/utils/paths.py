"""Project path helpers.

All helpers resolve paths from the installed/project root instead of the
current working directory, so GUI launchers, tests and packaged builds can use
the same resource lookup code.
"""

from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_root() -> Path:
    return project_root() / "app"


def resource_path(*parts: str) -> Path:
    return project_root().joinpath("resources", *parts)


def examples_path(*parts: str) -> Path:
    return project_root().joinpath("examples", *parts)


def docs_path(*parts: str) -> Path:
    return project_root().joinpath("docs", *parts)


def deliverables_path(*parts: str) -> Path:
    return project_root().joinpath("deliverables", *parts)


def demo_path(*parts: str) -> Path:
    return app_root().joinpath("demo", *parts)
