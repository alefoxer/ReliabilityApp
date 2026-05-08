from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from app.utils.paths import docs_path, project_root, resource_path


def _bootstrap_project_venv() -> None:
    """Relaunch the app through the local .venv when the script is started with another Python."""
    if getattr(sys, "frozen", False):
        return
    if os.environ.get("RELIABILITY_APP_VENV_BOOTSTRAPPED") == "1":
        return
    script_path = Path(__file__).resolve()
    argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] not in {"", "-c"} else None
    if argv0 != script_path:
        return
    root = project_root()
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        return
    current_python = Path(sys.executable).resolve()
    if current_python == venv_python.resolve():
        return
    os.environ["RELIABILITY_APP_VENV_BOOTSTRAPPED"] = "1"
    os.execv(str(venv_python), [str(venv_python), str(script_path), *sys.argv[1:]])


_bootstrap_project_venv()

from PyQt6.QtCore import QSettings, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import app.utils.app_constants as const
from app.import_export.file_service import SaveFormat, choose_save_path, notify_save_result
from app.gui.gui_calculator import ModuleUniversalCalc
from app.gui.gui_visual_editor import ModuleVisualRBD
from app.gui.help_content import ABOUT_TEXT, APP_NAME, HELP_TOPICS
from app.utils.logging_utils import configure_logging
from app.core.rbd_models import SchemeModel
from app.gui.screen_utils import fit_widget_to_screen
from app.gui.theme_manager import apply_theme


APP_DISPLAY_NAME = "Надёжность технических средств"
APP_USER_MODEL_ID = "Reliability.TechnicalReliability.App"


def _set_windows_app_identity() -> None:
    """Set a stable Windows app identity so the taskbar does not show Python."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


class MainWindow(QMainWindow):
    """Главное окно приложения."""

    def __init__(self):
        super().__init__()
        self.settings = QSettings("reliability-app", "desktop")
        self.logger = configure_logging(project_root())
        self.setWindowTitle(APP_DISPLAY_NAME)
        self._apply_window_icon()
        fit_widget_to_screen(self, width_ratio=0.94, height_ratio=0.9)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        sidebar = QFrame()
        sidebar.setProperty("role", "sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(8)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(72)
        self.tree.setMaximumHeight(96)
        self.tree.setHeaderLabel("Модули")
        self.tree.setMinimumWidth(160)
        self.editor_item = QTreeWidgetItem(self.tree, ["Графический редактор"])
        self.calculator_item = QTreeWidgetItem(self.tree, ["Калькулятор"])
        self.tree.expandAll()
        modules_box = QGroupBox("Модули")
        modules_layout = QVBoxLayout(modules_box)
        modules_layout.setContentsMargins(8, 8, 8, 8)
        modules_layout.addWidget(self.tree)
        sidebar_layout.addWidget(modules_box)
        self.sidebar_hint = QLabel(
            "<b>Графический редактор</b><br>"
            "Добавляйте блоки справа, соединяйте порты и проверяйте формулу. "
            "Ctrl + колесо меняет масштаб, средняя кнопка мыши панорамирует."
        )
        self.sidebar_hint.setWordWrap(True)
        self.sidebar_hint.setProperty("role", "hint")
        sidebar_layout.addWidget(self.sidebar_hint)
        self.sidebar_status = QLabel("Текущий модуль: графический редактор")
        self.sidebar_status.setWordWrap(True)
        self.sidebar_status.setProperty("role", "muted")
        sidebar_layout.addWidget(self.sidebar_status)
        sidebar_layout.addStretch()
        sidebar.setMinimumWidth(280)
        sidebar.setMaximumWidth(360)

        self.stack = QStackedWidget()
        self.editor = ModuleVisualRBD()
        self.calculator = ModuleUniversalCalc()
        sidebar_layout.insertWidget(1, self.editor.left_scroll, 1)
        sidebar_layout.insertWidget(2, self.calculator.left_scroll, 1)
        self.calculator.left_scroll.setVisible(False)
        self.sidebar_hint.setVisible(False)
        self.stack.addWidget(self.editor)
        self.stack.addWidget(self.calculator)

        splitter.addWidget(sidebar)
        splitter.addWidget(self.stack)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 8)
        splitter.setSizes([320, 1180])
        root_layout.addWidget(splitter, stretch=1)

        self.setCentralWidget(root)

        self.tree.setCurrentItem(self.editor_item)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        self.editor.scheme_calculated.connect(self.accept_scheme_result)
        self._build_menu()
        self._apply_saved_ui_scale()
        self.statusBar().showMessage("Готово к работе")

    def _build_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("Файл")
        analysis_menu = menu.addMenu("Анализ")
        view_menu = menu.addMenu("Вид")
        help_menu = menu.addMenu("Справка")

        action_export_scheme = file_menu.addAction("Экспорт изображения схемы")
        action_export_scheme.triggered.connect(self._export_scheme_from_menu)

        analysis_menu.addAction("Выполнить расчет", self.run_current_calculation)
        analysis_menu.addAction("Демо", self.run_demo_scenario)
        analysis_menu.addAction("Построить формулу по схеме", self.build_scheme_formula)
        analysis_menu.addAction("Показать результаты", self.show_results_module)
        analysis_menu.addAction("Сформировать отчет", self.export_report_from_menu)
        analysis_menu.addAction("Экспортировать график", self.export_plot_from_menu)

        for label, scale in [("Компактный", 0.9), ("Обычный", 1.0), ("Увеличенный", 1.15), ("Крупный", 1.3)]:
            action = view_menu.addAction(label)
            action.triggered.connect(lambda _, scale=scale: self.apply_ui_scale(scale))

        help_menu.addAction("О программе", self.show_about)
        help_menu.addAction("Справка", self.show_help)
        help_menu.addAction("Открыть руководство пользователя", self.open_user_manual)

    def _apply_window_icon(self):
        icon_path = resource_path("app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def run_current_calculation(self):
        try:
            if self.stack.currentIndex() == 0:
                self.editor.calc_graph()
                self.statusBar().showMessage("Расчет схемы выполнен", 5000)
            else:
                self.calculator.calc()
                self.statusBar().showMessage("Расчет выполнен", 5000)
        except Exception as exc:
            self.logger.exception("Ошибка выполнения расчета")
            QMessageBox.warning(self, "Ошибка расчета", str(exc))
            self.statusBar().showMessage("Ошибка расчета", 5000)

    def run_demo_scenario(self):
        try:
            self.stack.setCurrentIndex(0)
            self.tree.setCurrentItem(self.editor_item)
            self.editor.left_scroll.setVisible(True)
            self.calculator.left_scroll.setVisible(False)
            self.editor.run_sne_demo_scenario()
            self.stack.setCurrentIndex(1)
            self.tree.setCurrentItem(self.calculator_item)
            self.editor.left_scroll.setVisible(False)
            self.calculator.left_scroll.setVisible(True)
            self.sidebar_status.setText("Демо выполнено, открыт экран результатов")
            self.statusBar().showMessage("Демо выполнено", 5000)
        except Exception as exc:
            self.logger.exception("Ошибка демо")
            QMessageBox.warning(self, "Демо", str(exc))
            self.statusBar().showMessage("Ошибка демо", 5000)

    def build_scheme_formula(self):
        try:
            self.stack.setCurrentIndex(0)
            self.tree.setCurrentItem(self.editor_item)
            self.editor.left_scroll.setVisible(True)
            self.calculator.left_scroll.setVisible(False)
            self.editor.show_formula_dialog()
            self.statusBar().showMessage("Формула по схеме обновлена", 5000)
        except Exception as exc:
            self.logger.exception("Ошибка построения формулы")
            QMessageBox.warning(self, "Ошибка формулы", str(exc))

    def show_results_module(self):
        self.stack.setCurrentIndex(1)
        self.tree.setCurrentItem(self.calculator_item)
        self.editor.left_scroll.setVisible(False)
        self.calculator.left_scroll.setVisible(True)
        if hasattr(self.calculator, "results_tabs"):
            self.calculator.results_tabs.setCurrentIndex(0)
        self.statusBar().showMessage("Открыта панель результатов", 3000)

    def export_report_from_menu(self):
        self.stack.setCurrentIndex(1)
        self.tree.setCurrentItem(self.calculator_item)
        self.editor.left_scroll.setVisible(False)
        self.calculator.left_scroll.setVisible(True)
        self.calculator.export_current_report()
        self.statusBar().showMessage("Экспорт отчета завершен или отменен пользователем", 5000)

    def export_plot_from_menu(self):
        self.stack.setCurrentIndex(1)
        self.tree.setCurrentItem(self.calculator_item)
        self.editor.left_scroll.setVisible(False)
        self.calculator.left_scroll.setVisible(True)
        self.calculator.export_plot_image()
        self.statusBar().showMessage("Экспорт графика завершен или отменен пользователем", 5000)

    def _apply_saved_ui_scale(self):
        scale = float(self.settings.value("ui_scale", 1.0))
        self.apply_ui_scale(scale, persist=False)

    def apply_ui_scale(self, scale: float, *, persist: bool = True):
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, scale)
        if persist:
            self.settings.setValue("ui_scale", scale)
        self.statusBar().showMessage(f"Масштаб интерфейса: {int(scale * 100)}%", 3000)

    def on_tree_item_clicked(self, item, column):
        if "Калькулятор" in item.text(0):
            self.stack.setCurrentIndex(1)
            self.editor.left_scroll.setVisible(False)
            self.calculator.left_scroll.setVisible(True)
            self.sidebar_status.setText("Текущий модуль: калькулятор")
            self.sidebar_hint.setText(
                "<b>Калькулятор</b><br>"
                "Выберите методику F1.1-F7.2, задайте параметры и выполните расчет. "
                "Подробности метода раскрываются только по запросу."
            )
            self.statusBar().showMessage("Открыт модуль: калькулятор", 2000)
        else:
            self.stack.setCurrentIndex(0)
            self.editor.left_scroll.setVisible(True)
            self.calculator.left_scroll.setVisible(False)
            self.sidebar_status.setText("Текущий модуль: графический редактор")
            self.sidebar_hint.setText(
                "<b>Графический редактор</b><br>"
                "Добавляйте блоки справа, соединяйте порты и проверяйте формулу. "
                "Ctrl + колесо меняет масштаб, средняя кнопка мыши панорамирует."
            )
            self.statusBar().showMessage("Открыт модуль: графический редактор", 2000)

    def accept_scheme_result(self, result):
        scheme_images = self._export_scheme_images_for_report(self.editor.to_scheme_model())
        if scheme_images:
            result.details["scheme_image_path"] = str(scheme_images[0]["path"])
            result.details["scheme_images"] = scheme_images
        self.calculator.apply_scheme_result(result)
        self.sidebar_status.setText("Схема рассчитана, результат передан в калькулятор")
        self.statusBar().showMessage("Результат расчёта схемы передан в калькулятор", 5000)
        self.logger.info("Результат схемы передан в калькулятор")

    def _export_scheme_images_for_report(self, scheme: SchemeModel) -> list[dict[str, object]]:
        target_dir = Path(tempfile.mkdtemp(prefix="reliability_scheme_report_"))
        images: list[dict[str, object]] = []
        main_path = target_dir / "00_main_scheme.png"
        self._export_scheme_model_png(scheme, main_path)
        images.append({"title": "Схема системы", "path": str(main_path), "level": 0, "block_name": ""})
        self._collect_subscheme_images(scheme, target_dir, images, level=1, prefix="01")
        return images

    def _collect_subscheme_images(
        self,
        scheme: SchemeModel,
        target_dir: Path,
        images: list[dict[str, object]],
        *,
        level: int,
        prefix: str,
    ) -> None:
        child_index = 1
        for block in scheme.blocks:
            if not block.is_subscheme or block.nested_scheme is None:
                continue
            current_prefix = f"{prefix}_{child_index:02d}"
            image_path = target_dir / f"{current_prefix}_level{level}_{block.block_id}.png"
            self._export_scheme_model_png(block.nested_scheme, image_path)
            images.append(
                {
                    "title": f"Подсхема блока {block.name}",
                    "path": str(image_path),
                    "level": level,
                    "block_name": block.name,
                }
            )
            self._collect_subscheme_images(block.nested_scheme, target_dir, images, level=level + 1, prefix=current_prefix)
            child_index += 1

    @staticmethod
    def _export_scheme_model_png(scheme: SchemeModel, path: Path) -> str:
        editor = ModuleVisualRBD()
        editor.load_scheme_model(scheme)
        editor.export_current_scene_png(path)
        editor.deleteLater()
        return str(path)

    def _export_scheme_from_menu(self):
        target, _ = choose_save_path(
            self,
            "Экспорт схемы",
            [SaveFormat("PNG", ".png", "schema_nadezhnosti.png")],
        )
        if target is None:
            return
        try:
            self.editor.export_current_scene_png(target)
        except Exception as exc:
            notify_save_result(self, target, success=False, title="Экспорт схемы", error=str(exc))
            return
        notify_save_result(self, target, success=True, title="Экспорт схемы")

    def _obsolete_show_about(self):
        QMessageBox.information(
            self,
            "О программе",
            "Программа предназначена для построения структурных схем надежности,\n"
            "расчёта показателей, генерации формул, графиков и инженерных отчётов.",
        )

    def _obsolete_show_help(self):
        QMessageBox.information(
            self,
            "Справка",
            "1. Постройте схему в редакторе или выберите шаблон.\n"
            "2. Выполните проверку и расчёт.\n"
            "3. Передайте результат в калькулятор.\n"
            "4. Экспортируйте график, отчёт или изображение схемы.\n"
            "5. При необходимости измените масштаб интерфейса в меню «Вид».",
        )

    def _obsolete_open_user_manual(self):
        manual_candidates = [docs_path("USER_GUIDE.md"), project_root() / "README.md"]
        for candidate in manual_candidates:
            if candidate.exists():
                QMessageBox.information(self, "Руководство", f"Документ найден:\n{candidate}")
                return
        QMessageBox.warning(self, "Руководство", "Руководство пользователя пока не найдено.")


    def show_about(self):
        QMessageBox.about(self, f"О программе — {APP_NAME}", ABOUT_TEXT)

    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Справка")
        fit_widget_to_screen(dialog, width_ratio=0.78, height_ratio=0.82)

        layout = QVBoxLayout(dialog)
        content = QHBoxLayout()
        content.setSpacing(10)

        topics = QListWidget()
        topics.setMinimumWidth(240)
        topics.setMaximumWidth(320)
        for title, _html in HELP_TOPICS:
            topics.addItem(title)

        viewer = QTextBrowser()
        viewer.setOpenExternalLinks(True)
        viewer.setHtml(HELP_TOPICS[0][1])

        def show_topic(index: int) -> None:
            if 0 <= index < len(HELP_TOPICS):
                viewer.setHtml(HELP_TOPICS[index][1])

        topics.currentRowChanged.connect(show_topic)
        topics.setCurrentRow(0)

        content.addWidget(topics)
        content.addWidget(viewer, 1)
        layout.addLayout(content, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def open_user_manual(self):
        manual_candidates = [
            docs_path("USER_GUIDE.md"),
            project_root() / "README.md",
        ]
        for candidate in manual_candidates:
            if candidate.exists():
                opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
                if opened:
                    self.statusBar().showMessage(f"Открыто руководство пользователя: {candidate}", 5000)
                    return
                self.logger.warning("Не удалось открыть руководство пользователя: %s", candidate)
                QMessageBox.warning(
                    self,
                    "Руководство пользователя",
                    f"Файл найден, но не удалось открыть его системным просмотрщиком:\n{candidate}",
                )
                return
        QMessageBox.warning(
            self,
            "Руководство пользователя",
            "Руководство пользователя не найдено. Проверьте наличие файла docs/USER_GUIDE.md.",
        )

    @staticmethod
    def _app_root() -> Path:
        return project_root()


def main() -> int:
    _set_windows_app_identity()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app_icon = resource_path("app_icon.ico")
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
