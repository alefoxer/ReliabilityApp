from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import app.utils.app_constants as const
from app.import_export.file_service import SaveFormat, choose_save_path, notify_save_result
from app.core.rbd_models import ReportData
from app.reports.report_exporters import export_docx, export_html, export_pdf, export_txt, export_xlsx, report_to_html
from app.gui.screen_utils import fit_widget_to_screen
from app.utils.paths import demo_path


class ReportGenerator:
    """Совместимый фасад для HTML-представления отчёта."""

    @staticmethod
    def generate_html(title, inputs, results, extra_info=None):
        report = ReportData(
            title=title,
            subtitle=extra_info.get("Z_title_2", const.ConstText.Z_title_2) if extra_info else const.ConstText.Z_title_2,
            created_at=datetime.now(),
            inputs=inputs,
            results=results,
            method_name=title,
            methodology=(extra_info or {}).get("Z_3_0", const.ConstText.Z_3_0),
            notes=(extra_info or {}).get("notes", ""),
        )
        return report_to_html(report)


def _module_library_path(filename: str) -> Path:
    path = Path(filename)
    if path.is_absolute():
        return path
    if path.name in {"db_modules.json", "db_modules.txt"} and path.parent == Path("."):
        return demo_path(path.name)
    return path


class DialogNomenclature(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор номенклатуры показателей надежности")
        fit_widget_to_screen(self, width_ratio=0.45, height_ratio=0.72)
        layout = QVBoxLayout(self)

        gb1 = QGroupBox("Назначение изделия")
        l1 = QVBoxLayout(gb1)
        self.rb_kn = QRadioButton("Конкретное назначение")
        self.rb_on = QRadioButton("Общее назначение")
        self.rb_kn.setChecked(True)
        l1.addWidget(self.rb_kn)
        l1.addWidget(self.rb_on)
        layout.addWidget(gb1)

        gb2 = QGroupBox("Режим применения")
        l2 = QVBoxLayout(gb2)
        self.rb_npdp = QRadioButton("Непрерывное длительное применение")
        self.rb_mkcp = QRadioButton("Многократное циклическое применение")
        self.rb_okrp = QRadioButton("Однократное применение с ожиданием")
        self.rb_part = QRadioButton("Режим с частичным отказом")
        self.rb_npdp.setChecked(True)
        for item in (self.rb_npdp, self.rb_mkcp, self.rb_okrp, self.rb_part):
            l2.addWidget(item)
        layout.addWidget(gb2)

        gb3 = QGroupBox("Восстановление")
        l3 = QVBoxLayout(gb3)
        self.rb_vos_obs = QRadioButton("Восстанавливаемое обслуживаемое изделие")
        self.rb_vos_neobs = QRadioButton("Восстанавливаемое необслуживаемое изделие")
        self.rb_nevos = QRadioButton("Невосстанавливаемое изделие")
        self.rb_vos_obs.setChecked(True)
        for item in (self.rb_vos_obs, self.rb_vos_neobs, self.rb_nevos):
            l3.addWidget(item)
        layout.addWidget(gb3)

        self.lbl_tto = QLabel("Время технического обслуживания [ч]:")
        self.line_tto = QLineEdit()
        layout.addWidget(self.lbl_tto)
        layout.addWidget(self.line_tto)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button is not None:
            ok_button.setText("OK")
        if cancel_button is not None:
            cancel_button.setText("Закрыть")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        for button in (self.rb_vos_obs, self.rb_vos_neobs, self.rb_nevos):
            button.toggled.connect(self.check_tto)
        self.check_tto()

    def check_tto(self):
        enabled = self.rb_vos_obs.isChecked()
        self.line_tto.setEnabled(enabled)
        if not enabled:
            self.line_tto.clear()

    def get_data(self):
        return {"Tto": self.line_tto.text()}


class DialogNomenclature(QDialog):
    PURPOSE_OPTIONS = {
        "specific": (
            "Конкретное назначение",
            "Изделие рассматривается в составе конкретной системы или под фиксированный сценарий применения.",
        ),
        "general": (
            "Общее назначение",
            "Изделие оценивается как типовой элемент без жёсткой привязки к одной задаче.",
        ),
    }
    USAGE_OPTIONS = {
        "continuous": (
            "Непрерывное длительное применение",
            "Работа идёт долго и без регулярных остановок. Обычно важны P(t), T0 и показатели готовности.",
        ),
        "cyclic": (
            "Многократное циклическое применение",
            "Изделие многократно включается и выключается по повторяющемуся циклу эксплуатации.",
        ),
        "standby": (
            "Однократное применение с ожиданием",
            "Большую часть времени изделие ожидает команды и должно сработать в заданный момент.",
        ),
        "partial_failure": (
            "Режим с частичным отказом",
            "Допускается ухудшение работы без полного отказа, поэтому важны пояснения по допустимому снижению функции.",
        ),
    }
    RECOVERY_OPTIONS = {
        "serviceable": (
            "Восстанавливаемое обслуживаемое изделие",
            "После отказа изделие восстанавливают, а регламентное обслуживание влияет на готовность.",
        ),
        "recoverable": (
            "Восстанавливаемое необслуживаемое изделие",
            "Изделие восстанавливают после отказа, но отдельное техническое обслуживание в расчёт не включают.",
        ),
        "nonrecoverable": (
            "Невосстанавливаемое изделие",
            "После отказа изделие считают выбывшим из работы. Обычно акцент на P(t) и T0.",
        ),
    }

    def __init__(self, parent=None, initial_data: dict | None = None):
        super().__init__(parent)
        self._initial_data = dict(initial_data or {})
        self.setWindowTitle("Выбор номенклатуры показателей надёжности")
        fit_widget_to_screen(self, width_ratio=0.52, height_ratio=0.82)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "Справочник помогает выбрать формулировки для отчёта и понять, какие показатели "
            "обычно ожидают увидеть для выбранного сценария. На сами формулы и расчёт он не влияет."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #536274;")
        layout.addWidget(intro)

        self.purpose_buttons: dict[str, QRadioButton] = {}
        self.usage_buttons: dict[str, QRadioButton] = {}
        self.recovery_buttons: dict[str, QRadioButton] = {}
        self.purpose_group = QButtonGroup(self)
        self.usage_group = QButtonGroup(self)
        self.recovery_group = QButtonGroup(self)

        layout.addWidget(
            self._build_option_group(
                "Назначение изделия",
                self.PURPOSE_OPTIONS,
                self.purpose_buttons,
                self._initial_data.get("purpose_code", "specific"),
                self.purpose_group,
            )
        )
        layout.addWidget(
            self._build_option_group(
                "Режим применения",
                self.USAGE_OPTIONS,
                self.usage_buttons,
                self._initial_data.get("usage_mode_code", "continuous"),
                self.usage_group,
            )
        )
        layout.addWidget(
            self._build_option_group(
                "Восстановление и обслуживание",
                self.RECOVERY_OPTIONS,
                self.recovery_buttons,
                self._initial_data.get("recovery_mode_code", "serviceable"),
                self.recovery_group,
            )
        )

        tto_box = QGroupBox("Параметр обслуживания")
        tto_layout = QVBoxLayout(tto_box)
        self.lbl_tto = QLabel("Время технического обслуживания Tто, ч")
        self.line_tto = QLineEdit()
        self.line_tto.setPlaceholderText("Например: 2.5")
        self.tto_hint = QLabel()
        self.tto_hint.setWordWrap(True)
        self.tto_hint.setStyleSheet("color: #536274;")
        tto_layout.addWidget(self.lbl_tto)
        tto_layout.addWidget(self.line_tto)
        tto_layout.addWidget(self.tto_hint)
        layout.addWidget(tto_box)

        summary_box = QGroupBox("Итог выбора")
        summary_layout = QVBoxLayout(summary_box)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-weight: 600; color: #16324f;")
        self.metrics_label = QLabel()
        self.metrics_label.setWordWrap(True)
        self.metrics_label.setStyleSheet("color: #536274;")
        summary_layout.addWidget(self.summary_label)
        summary_layout.addWidget(self.metrics_label)
        layout.addWidget(summary_box)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button is not None:
            ok_button.setText("Применить")
        if cancel_button is not None:
            cancel_button.setText("Закрыть")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        for button in [*self.purpose_buttons.values(), *self.usage_buttons.values(), *self.recovery_buttons.values()]:
            button.toggled.connect(self._on_selection_changed)
        self.line_tto.setText(str(self._initial_data.get("tto", "")))
        self._on_selection_changed()

    def _build_option_group(self, title, options, storage, default_code, button_group):
        box = QGroupBox(title)
        group_layout = QVBoxLayout(box)
        group_layout.setSpacing(10)
        for code, (label, description) in options.items():
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            button = QRadioButton(label)
            button.setChecked(code == default_code)
            button_group.addButton(button)
            description_label = QLabel(description)
            description_label.setWordWrap(True)
            description_label.setStyleSheet("color: #536274;")
            row_layout.addWidget(button, 0)
            row_layout.addWidget(description_label, 1)
            group_layout.addWidget(row)
            storage[code] = button
        return box

    @staticmethod
    def _selected_code(buttons: dict[str, QRadioButton]) -> str:
        for code, button in buttons.items():
            if button.isChecked():
                return code
        return next(iter(buttons))

    def _recommended_metrics_text(self) -> str:
        usage_code = self._selected_code(self.usage_buttons)
        recovery_code = self._selected_code(self.recovery_buttons)
        metrics = ["P(t)", "T0"]
        if recovery_code in {"serviceable", "recoverable"}:
            metrics.append("Kг")
        if recovery_code == "serviceable":
            metrics.append("Tто")
        if usage_code == "standby":
            return "Рекомендуемо показать: P(t) на момент применения, T0 и пояснение по режиму ожидания."
        return "Рекомендуемо показать: " + ", ".join(metrics) + "."

    def _summary_text(self) -> str:
        purpose_code = self._selected_code(self.purpose_buttons)
        usage_code = self._selected_code(self.usage_buttons)
        recovery_code = self._selected_code(self.recovery_buttons)
        requires_tto = recovery_code == "serviceable"
        tto_text = self.line_tto.text().strip() if requires_tto and self.line_tto.text().strip() else "не задано"
        if not requires_tto:
            tto_text = "не требуется"
        return (
            f"Назначение: {self.PURPOSE_OPTIONS[purpose_code][0]}\n"
            f"Режим применения: {self.USAGE_OPTIONS[usage_code][0]}\n"
            f"Восстановление: {self.RECOVERY_OPTIONS[recovery_code][0]}\n"
            f"Tто: {tto_text}"
        )

    def _on_selection_changed(self):
        enabled = self._selected_code(self.recovery_buttons) == "serviceable"
        self.line_tto.setEnabled(enabled)
        self.lbl_tto.setEnabled(enabled)
        if enabled:
            self.tto_hint.setText("Укажите Tто, если регламентное обслуживание учитывается в эксплуатации изделия.")
        else:
            self.line_tto.clear()
            self.tto_hint.setText("Для выбранного типа изделия параметр Tто в справочнике не требуется.")
        self.summary_label.setText(self._summary_text())
        self.metrics_label.setText(self._recommended_metrics_text())

    def get_data(self):
        purpose_code = self._selected_code(self.purpose_buttons)
        usage_code = self._selected_code(self.usage_buttons)
        recovery_code = self._selected_code(self.recovery_buttons)
        requires_tto = recovery_code == "serviceable"
        return {
            "purpose_code": purpose_code,
            "purpose_label": self.PURPOSE_OPTIONS[purpose_code][0],
            "usage_mode_code": usage_code,
            "usage_mode_label": self.USAGE_OPTIONS[usage_code][0],
            "recovery_mode_code": recovery_code,
            "recovery_mode_label": self.RECOVERY_OPTIONS[recovery_code][0],
            "requires_tto": requires_tto,
            "tto": self.line_tto.text().strip() if requires_tto else "",
            "summary_text": self._summary_text(),
            "recommended_metrics_text": self._recommended_metrics_text(),
        }


class DialogReportSettings(QDialog):
    def __init__(self, current_results, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметры отчёта")
        fit_widget_to_screen(self, width_ratio=0.58, height_ratio=0.85)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll_widget = QGroupBox()
        layout = QVBoxLayout(self.scroll_widget)
        scroll.setWidget(self.scroll_widget)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)

        self.inputs: dict[str, QLineEdit] = {}
        self.texts: dict[str, QPlainTextEdit] = {}

        text_fields = [
            ("Организация", const.ConstText.Z_title_1),
            ("Изделие", const.ConstText.Z_title_2),
            ("Подзаголовок отчёта", "Расчёт показателей надежности сложного изделия"),
        ]
        for label_text, default_value in text_fields:
            layout.addWidget(QLabel(label_text))
            line_edit = QLineEdit(default_value)
            layout.addWidget(line_edit)
            self.inputs[label_text] = line_edit

        long_texts = [
            ("Определение надежности", const.ConstText.Z_1_1),
            ("Методика расчёта", const.ConstText.Z_3_0),
            ("Примечания", ""),
        ]
        for label_text, default_value in long_texts:
            layout.addWidget(QLabel(label_text))
            text_edit = QPlainTextEdit(default_value)
            text_edit.setMaximumHeight(110)
            layout.addWidget(text_edit)
            self.texts[label_text] = text_edit

        layout.addWidget(QLabel("Таблица результатов"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Параметр", "Значение"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        for key, value in current_results.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(key)))
            value_text = f"{value:.6f}" if isinstance(value, (float, int)) else str(value)
            self.table.setItem(row, 1, QTableWidgetItem(value_text))

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_data(self):
        data = {
            "Z_title_1": self.inputs["Организация"].text(),
            "Z_title_2": self.inputs["Изделие"].text(),
            "subtitle": self.inputs["Подзаголовок отчёта"].text(),
            "Z_1_1": self.texts["Определение надежности"].toPlainText(),
            "Z_3_0": self.texts["Методика расчёта"].toPlainText(),
            "notes": self.texts["Примечания"].toPlainText(),
        }
        results = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if not key_item or not value_item:
                continue
            try:
                results[key_item.text()] = float(value_item.text())
            except ValueError:
                results[key_item.text()] = value_item.text()
        return data, results


class DialogSaveModule(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сохранение шаблона компонента")
        fit_widget_to_screen(self, width_ratio=0.42, height_ratio=0.46)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.inp_name = QLineEdit()
        self.inp_file = QLineEdit("db_modules.json")
        self.inp_module = QLineEdit(str(data.get("module", "")))
        self.inp_module.setReadOnly(True)
        self.inp_lam = QLineEdit(str(data.get("lambda", "")))
        self.inp_lam.setReadOnly(True)
        self.inp_tv = QLineEdit(str(data.get("Tv", "")))
        self.inp_tv.setReadOnly(True)
        self.inp_t = QLineEdit(str(data.get("t", "")))
        self.inp_t.setReadOnly(True)
        form.addRow("Название шаблона:", self.inp_name)
        form.addRow("Файл библиотеки:", self.inp_file)
        form.addRow("Метод:", self.inp_module)
        form.addRow("Лямбда:", self.inp_lam)
        form.addRow("Tv:", self.inp_tv)
        form.addRow("Время t:", self.inp_t)
        layout.addLayout(form)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def save(self):
        name = self.inp_name.text().strip()
        filename = self.inp_file.text().strip() or "db_modules.json"
        if not name or "/" in name or "#" in name:
            QMessageBox.warning(self, "Ошибка", "Введите корректное имя шаблона.")
            return
        target = _module_library_path(filename)
        record = {
            "name": name,
            "module": self.inp_module.text(),
            "t": self.inp_t.text(),
            "lambda": self.inp_lam.text(),
            "Tv": self.inp_tv.text(),
        }
        try:
            if target.suffix.lower() == ".json":
                data = []
                if target.exists():
                    data = json.loads(target.read_text(encoding="utf-8"))
                data = [item for item in data if item.get("name") != name]
                data.append(record)
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                exists = target.exists()
                with target.open("a", encoding="utf-8") as file:
                    if not exists:
                        file.write("#Название/Модуль/Время/Лямбда/Tv\n")
                    file.write(f"{name}/{record['module']}/{record['t']}/{record['lambda']}/{record['Tv']}\n")
            QMessageBox.information(self, "Сохранение", "Шаблон компонента сохранён.")
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", str(exc))


class DialogLoadModule(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор шаблона компонента")
        fit_widget_to_screen(self, width_ratio=0.62, height_ratio=0.55)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Название", "Метод", "Время", "Лямбда", "Tv"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.table)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.modules_data = []
        self.load_data()

    def load_data(self):
        json_path = demo_path("db_modules.json")
        txt_path = demo_path("db_modules.txt")
        try:
            if json_path.exists():
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                for item in raw:
                    self._append_row(item)
            elif txt_path.exists():
                with txt_path.open("r", encoding="utf-8") as file:
                    for line in file:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("/")
                        if len(parts) >= 5:
                            self._append_row(
                                {
                                    "name": parts[0],
                                    "module": parts[1],
                                    "t": parts[2],
                                    "lambda": parts[3],
                                    "Tv": parts[4],
                                }
                            )
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка чтения", str(exc))

    def _append_row(self, item):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [item.get("name", ""), item.get("module", ""), item.get("t", ""), item.get("lambda", ""), item.get("Tv", "")]
        for index, value in enumerate(values):
            self.table.setItem(row, index, QTableWidgetItem(str(value)))
        self.modules_data.append(item)

    def get_selected_data(self):
        row = self.table.currentRow()
        return self.modules_data[row] if 0 <= row < len(self.modules_data) else None


class BlockPropsDialog(QDialog):
    BLOCK_TYPES = (
        ("ordinary", "Обычный элемент"),
        ("reserve", "Элемент с резервом"),
        ("k_of_n", "k из N / скользящий резерв"),
        ("subscheme", "Подсхема"),
        ("passive", "Служебный/пассивный"),
    )

    def __init__(self, name, props, is_subscheme=False):
        super().__init__()
        self.setWindowTitle("Свойства блока")
        fit_widget_to_screen(self, width_ratio=0.42, height_ratio=0.66)
        self._original_props = dict(props or {})

        layout = QVBoxLayout(self)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(6, 6, 6, 6)
        form.setSpacing(8)

        self.inp_name = QLineEdit(name)
        form.addRow("Имя блока:", self.inp_name)

        self.inputs: dict[str, QLineEdit | QComboBox] = {}
        self.row_labels: dict[str, QLabel] = {}
        self.row_widgets: dict[str, QWidget] = {}
        self._add_line_field(
            form,
            "formula_symbol",
            "Короткое обозначение блока в формулах и на схеме. Например: B1, B2, P1.",
            props.get("formula_symbol", name),
            "Обозначение в формуле:",
        )

        self.type_combo = QComboBox()
        for role, label in self.BLOCK_TYPES:
            self.type_combo.addItem(label, role)
        self.type_combo.setToolTip("Тип блока задает инженерный смысл элемента для расчета, валидации и генератора формул.")
        form.addRow("Тип блока:", self.type_combo)

        self._add_line_field(form, "lambda", "Интенсивность отказов λ.", props.get("lambda", 0.001), "Интенсивность отказов λ:")
        self._add_line_field(form, "Tv", "Среднее время восстановления Tв.", props.get("Tv", 10.0), "Среднее время восстановления Tв:")
        self._add_line_field(form, "t", "Горизонт расчета по времени t.", props.get("t", 1000), "Горизонт расчета t:")
        self._add_line_field(form, "reserve_count", "Количество резервных элементов для схемы 1+m.", props.get("reserve_count", 1), "Число резервов m:")
        self._add_line_field(form, "k_required", "Требуемое число работоспособных элементов k.", props.get("k_required", 1), "Требуемо работоспособных k:")
        self._add_line_field(form, "n_total", "Общее число элементов N.", props.get("n_total", 2), "Всего элементов N:")

        reserve_type = QComboBox()
        reserve_type.addItem("Авто", "")
        reserve_type.addItem("Обычный резерв", "standard")
        reserve_type.addItem("Скользящий резерв", "sliding")
        reserve_type.addItem("Нагруженный резерв", "loaded")
        reserve_type.addItem("Ненагруженный резерв", "unloaded")
        reserve_type.setToolTip("Классификационный признак режима резервирования. Используется генератором формул и диагностикой.")
        self.inputs["reserve_type"] = reserve_type
        self._add_widget_row(form, "reserve_type", "Тип резерва:", reserve_type)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setProperty("role", "muted")
        form.addRow(self.hint_label)
        layout.addWidget(form_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        initial_role = self._detect_block_role(self._original_props, is_subscheme)
        self._set_current_role(initial_role)
        reserve_type_index = reserve_type.findData(str(props.get("reserve_type", "")))
        if reserve_type_index >= 0:
            reserve_type.setCurrentIndex(reserve_type_index)
        self.type_combo.currentIndexChanged.connect(self._refresh_type_ui)
        self._refresh_type_ui()

    def _add_line_field(self, form: QFormLayout, key: str, tooltip: str, value, label_text: str) -> None:
        line_edit = QLineEdit(str(value))
        line_edit.setToolTip(tooltip)
        self.inputs[key] = line_edit
        self._add_widget_row(form, key, label_text, line_edit)

    def _add_widget_row(self, form: QFormLayout, key: str, label_text: str, widget: QWidget) -> None:
        label = QLabel(label_text)
        form.addRow(label, widget)
        self.row_labels[key] = label
        self.row_widgets[key] = widget

    @classmethod
    def _detect_block_role(cls, props: dict, is_subscheme: bool) -> str:
        if is_subscheme or str(props.get("block_role", "")).lower() == "subscheme":
            return "subscheme"
        role = str(props.get("block_role", "")).lower().strip()
        valid = {item[0] for item in cls.BLOCK_TYPES}
        if role in valid:
            return role
        if "k_required" in props or "n_total" in props or str(props.get("reserve_type", "")).lower() == "sliding":
            return "k_of_n"
        try:
            if int(float(props.get("reserve_count", 0) or 0)) > 0:
                return "reserve"
        except (TypeError, ValueError):
            pass
        return "ordinary"

    def _set_current_role(self, role: str) -> None:
        index = self.type_combo.findData(role)
        self.type_combo.setCurrentIndex(index if index >= 0 else 0)

    def _refresh_type_ui(self) -> None:
        role = self.current_block_role()
        visible_by_role = {
            "ordinary": {"formula_symbol", "lambda", "Tv", "t"},
            "reserve": {"formula_symbol", "lambda", "Tv", "t", "reserve_count", "reserve_type"},
            "k_of_n": {"formula_symbol", "lambda", "Tv", "t", "k_required", "n_total", "reserve_type"},
            "subscheme": {"formula_symbol", "lambda", "Tv", "t"},
            "passive": {"formula_symbol", "lambda", "Tv", "t"},
        }
        active_keys = visible_by_role.get(role, {"formula_symbol", "lambda", "Tv", "t"})
        for key in self.row_widgets:
            visible = key in active_keys
            self.row_labels[key].setVisible(visible)
            self.row_widgets[key].setVisible(visible)
        hints = {
            "ordinary": "Обычный расчетный элемент: используются базовые параметры λ, Tв и t.",
            "reserve": "Резерв 1+m: reserve_count задает число резервных копий для структурной формулы.",
            "k_of_n": "Специальный режим k из N: требуется задать k_required и n_total. При отсутствии verified-методики будет показан manual review.",
            "subscheme": "Блок трактуется как вложенная подсхема. Резервные параметры для него не используются.",
            "passive": "Служебный/пассивный блок сохраняет параметры, но не должен выдавать нормативную специальную формулу.",
        }
        self.hint_label.setText(hints.get(role, ""))

    def get_name(self):
        return self.inp_name.text().strip()

    def get_props(self):
        role = self.current_block_role()
        props: dict[str, object] = {
            "block_role": role,
            "formula_symbol": self._text_value("formula_symbol", default=self.get_name()),
            "lambda": self._float_value("lambda", default=0.0),
            "Tv": self._float_value("Tv", default=0.0),
            "t": self._float_value("t", default=1000.0),
        }
        if role == "reserve":
            props["reserve_count"] = self._int_value("reserve_count", default=0)
            reserve_type = self._combo_value("reserve_type")
            if reserve_type:
                props["reserve_type"] = reserve_type
        elif role == "k_of_n":
            props["k_required"] = self._int_value("k_required", default=0)
            props["n_total"] = self._int_value("n_total", default=0)
            props["reserve_type"] = self._combo_value("reserve_type") or "sliding"
        return props

    def is_subscheme(self):
        return self.current_block_role() == "subscheme"

    def current_block_role(self) -> str:
        return str(self.type_combo.currentData() or "ordinary")

    def _float_value(self, key: str, default: float = 0.0) -> float:
        widget = self.inputs[key]
        assert isinstance(widget, QLineEdit)
        try:
            return float(widget.text().replace(",", "."))
        except ValueError:
            return default

    def _int_value(self, key: str, default: int = 0) -> int:
        return int(round(self._float_value(key, float(default))))

    def _combo_value(self, key: str) -> str:
        widget = self.inputs[key]
        assert isinstance(widget, QComboBox)
        return str(widget.currentData() or "")

    def _text_value(self, key: str, default: str = "") -> str:
        widget = self.inputs[key]
        assert isinstance(widget, QLineEdit)
        return widget.text().strip() or default


REPORT_FORMATS = [
    SaveFormat("HTML", ".html", "otchet_nadezhnosti.html"),
    SaveFormat("DOCX", ".docx", "otchet_nadezhnosti.docx"),
    SaveFormat("XLSX", ".xlsx", "dannye_rascheta.xlsx"),
    SaveFormat("PDF", ".pdf", "otchet_nadezhnosti.pdf"),
    SaveFormat("TXT", ".txt", "rezultaty_rascheta.txt"),
]


def export_report_bundle(report: ReportData, parent=None) -> list[Path]:
    path, chosen_format = choose_save_path(parent, "Экспорт отчёта", REPORT_FORMATS)
    if path is None or chosen_format is None:
        return []

    exporters = {
        ".html": export_html,
        ".docx": export_docx,
        ".xlsx": export_xlsx,
        ".pdf": export_pdf,
        ".txt": export_txt,
    }
    exporter = exporters[chosen_format.extension]
    try:
        exported = exporter(path, report)
    except Exception as exc:
        error_text = str(exc)
        if chosen_format.extension == ".docx" and "python-docx" in error_text:
            error_text += (
                f"\n\nТекущий интерпретатор: {sys.executable}"
                "\nЗапустите приложение через .venv, где зависимость уже установлена."
            )
        elif chosen_format.extension == ".xlsx" and ("openpyxl" in error_text or "Pillow" in error_text):
            error_text += (
                f"\n\nТекущий интерпретатор: {sys.executable}"
                "\nЗапустите приложение через .venv, где зависимости уже установлены."
            )
        notify_save_result(parent, path, success=False, title="Экспорт отчёта", error=error_text)
        return []

    notify_save_result(parent, exported, success=True, title="Экспорт отчёта")
    return [exported]
