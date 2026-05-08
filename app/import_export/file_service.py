from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from app.utils.paths import project_root


@dataclass(frozen=True, slots=True)
class SaveFormat:
    label: str
    extension: str
    default_name: str

    @property
    def file_filter(self) -> str:
        return f"{self.label} (*{self.extension})"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return project_root()


def app_resource_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)


def choose_save_path(
    parent: QWidget | None,
    title: str,
    formats: list[SaveFormat],
) -> tuple[Path | None, SaveFormat | None]:
    filter_string = ";;".join(item.file_filter for item in formats)
    default_path = _timestamped_default_name(formats[0].default_name) if formats else "output.dat"
    selected_path, selected_filter = QFileDialog.getSaveFileName(parent, title, default_path, filter_string)
    if not selected_path:
        return None, None

    chosen_format = next((item for item in formats if item.file_filter == selected_filter), formats[0])
    path = Path(selected_path)
    if path.suffix.lower() != chosen_format.extension.lower():
        path = path.with_suffix(chosen_format.extension)
    return path, chosen_format


def _timestamped_default_name(default_name: str) -> str:
    path = Path(default_name)
    stamp = datetime.now().strftime("%Y-%m-%d__%H-%M")
    stem = path.stem or "result"
    return f"{stem}__{stamp}{path.suffix}"


def notify_save_result(parent: QWidget | None, target: Path, *, success: bool, title: str, error: str = "") -> None:
    if success:
        QMessageBox.information(parent, title, f"Файл успешно сохранён:\n{target}")
    else:
        QMessageBox.critical(parent, title, f"Не удалось сохранить файл:\n{target}\n\n{error}")
