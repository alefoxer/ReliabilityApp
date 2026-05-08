def build_app_style(scale: float = 1.0) -> str:
    font_size = max(9, int(round(10 * scale)))
    control_padding_v = max(6, int(round(8 * scale)))
    control_padding_h = max(10, int(round(14 * scale)))
    radius = max(8, int(round(10 * scale)))
    return f"""
QMainWindow, QWidget {{
    background: #f5f7fb;
    color: #1f2937;
    font-family: "Segoe UI";
    font-size: {font_size}pt;
}}
QFrame, QGroupBox, QScrollArea, QTextEdit, QPlainTextEdit, QTableWidget, QTreeWidget, QListWidget {{
    background: #ffffff;
    border: 1px solid #d8e0ea;
    border-radius: {radius}px;
}}
QFrame[role="sidebar"] {{
    background: #ffffff;
    border: 1px solid #d8e0ea;
    border-radius: {radius}px;
}}
QLabel[role="hint"] {{
    background: #f3f7fc;
    border: 1px solid #d8e0ea;
    border-radius: {radius - 2}px;
    padding: 8px;
    line-height: 1.25;
}}
QLabel[role="muted"] {{
    color: #536274;
    padding: 4px;
}}
QGroupBox {{
    font-weight: 600;
    margin-top: 10px;
    padding-top: 14px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px 0 6px;
}}
QFrame[role="details"] {{
    background: #ffffff;
    border: 1px solid #d8e0ea;
    border-radius: {radius}px;
}}
QTabWidget#resultsTabs::pane {{
    background: #ffffff;
    border: 1px solid #d8e0ea;
    border-radius: {radius}px;
    top: -1px;
    margin-top: 4px;
}}
QTabWidget#resultsTabs QWidget[role="resultsPage"] {{
    background: #fbfdff;
    border: 1px solid #e3ebf5;
    border-radius: {radius - 1}px;
}}
QTabWidget#resultsTabs QTabBar::tab {{
    background: #eaf0f8;
    color: #4a5b70;
    border: 1px solid #ced9e8;
    border-bottom: none;
    border-top-left-radius: {radius - 2}px;
    border-top-right-radius: {radius - 2}px;
    padding: {max(5, control_padding_v - 1)}px {max(12, control_padding_h - 1)}px;
    margin-right: 6px;
    min-width: 118px;
    font-weight: 600;
}}
QTabWidget#resultsTabs QTabBar::tab:hover {{
    background: #f2f6fc;
    color: #28435f;
}}
QTabWidget#resultsTabs QTabBar::tab:selected {{
    background: #ffffff;
    color: #153c61;
    border-color: #b9cbe0;
    font-weight: 700;
}}
QToolButton[role="detailsToggle"] {{
    background: #edf4fb;
    border: 1px solid #b7c9dd;
    border-radius: {radius - 2}px;
    color: #163f63;
    font-weight: 700;
    padding: 5px 10px;
    text-align: left;
}}
QToolButton[role="detailsToggle"]:checked {{
    background: #dcecfb;
    border-color: #7ea6cf;
}}
QPushButton {{
    background: #e6edf8;
    border: 1px solid #c8d4e7;
    border-radius: {radius - 2}px;
    padding: {control_padding_v}px {control_padding_h}px;
}}
QPushButton:hover {{
    background: #d9e7fa;
}}
QPushButton:pressed {{
    background: #ccdff8;
}}
QPushButton[role="primary"] {{
    background: #1f6fb2;
    color: white;
    border: 1px solid #15598f;
    font-weight: 700;
}}
QPushButton[role="danger"] {{
    background: #fceaea;
    border: 1px solid #eab7b7;
}}
QPushButton[role="tool"] {{
    min-width: 32px;
    padding: 4px 8px;
}}
QPushButton[role="compact"] {{
    min-height: 24px;
    padding: 5px 8px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: {radius - 2}px;
    padding: 6px 8px;
    min-height: 18px;
}}
QTextEdit, QPlainTextEdit {{
    padding: 8px;
}}
QHeaderView::section {{
    background: #ecf2f9;
    color: #32465a;
    border: none;
    border-bottom: 1px solid #d8e0ea;
    padding: 8px;
    font-weight: 600;
}}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{
    background: #dbeafe;
    color: #1e3a5f;
}}
QMenuBar {{
    background: #eef3f9;
}}
QStatusBar {{
    background: #eef3f9;
}}
"""
