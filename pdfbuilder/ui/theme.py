"""Light and dark palettes plus the application stylesheet."""
from __future__ import annotations

DARK = {
    "bg": "#16181d", "bg2": "#1c1f26", "bg3": "#23272f", "card": "#1f232b",
    "line": "#2e333d", "line2": "#3a4049",
    "text": "#e8eaef", "dim": "#9aa2b1", "faint": "#6b7382",
    "accent": "#4f8cff", "accent2": "#2f6fe0", "accent_t": "#ffffff",
    "good": "#3ec07a", "warn": "#e9a33a", "bad": "#f2545b",
    "sel": "#2a3favoid", "canvas": "#101216", "paper": "#ffffff",
}
DARK["sel"] = "#273041"

LIGHT = {
    "bg": "#f6f7f9", "bg2": "#ffffff", "bg3": "#eef0f4", "card": "#ffffff",
    "line": "#dcdfe6", "line2": "#c7ccd6",
    "text": "#1b1f27", "dim": "#5b6472", "faint": "#8a93a2",
    "accent": "#2563eb", "accent2": "#1d4ed8", "accent_t": "#ffffff",
    "good": "#15803d", "warn": "#b45309", "bad": "#c7343b",
    "sel": "#e3ebfd", "canvas": "#e7e9ee", "paper": "#ffffff",
}

QSS = """
* { outline: none; }
QWidget { background: %(bg)s; color: %(text)s;
          font-size: 13px; }
QMainWindow, QDialog { background: %(bg)s; }

QLabel { background: transparent; }
QLabel[role="h1"] { font-size: 19px; font-weight: 600; }
QLabel[role="h2"] { font-size: 15px; font-weight: 600; }
QLabel[role="dim"] { color: %(dim)s; }
QLabel[role="faint"] { color: %(faint)s; font-size: 12px; }
QLabel[role="good"] { color: %(good)s; }
QLabel[role="bad"]  { color: %(bad)s; }
QLabel[role="warn"] { color: %(warn)s; }
QLabel[role="pill"] { background: %(bg3)s; border: 1px solid %(line)s;
                      border-radius: 9px; padding: 1px 8px; color: %(dim)s;
                      font-size: 11px; }

#Sidebar { background: %(bg2)s; border-right: 1px solid %(line)s; }
#Header  { background: %(bg2)s; border-bottom: 1px solid %(line)s; }
#Card, QGroupBox { background: %(card)s; border: 1px solid %(line)s;
                   border-radius: 10px; }
QGroupBox { margin-top: 14px; padding: 16px 12px 10px 12px;
            font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px;
                   color: %(dim)s; }

QPushButton { background: %(bg3)s; border: 1px solid %(line2)s;
              border-radius: 7px; padding: 7px 14px; color: %(text)s; }
QPushButton:hover { background: %(sel)s; border-color: %(accent)s; }
QPushButton:pressed { background: %(line)s; }
QPushButton:disabled { color: %(faint)s; background: %(bg2)s;
                       border-color: %(line)s; }
QPushButton[kind="primary"] { background: %(accent)s; color: %(accent_t)s;
                              border: 1px solid %(accent2)s;
                              font-weight: 600; padding: 9px 20px; }
QPushButton[kind="primary"]:hover { background: %(accent2)s; }
QPushButton[kind="primary"]:disabled { background: %(line)s;
                                       border-color: %(line)s;
                                       color: %(faint)s; }
QPushButton[kind="danger"]:hover { border-color: %(bad)s; color: %(bad)s; }
QPushButton[kind="flat"] { background: transparent; border: none;
                           padding: 5px 8px; color: %(dim)s; }
QPushButton[kind="flat"]:hover { color: %(accent)s; background: %(bg3)s; }
QPushButton[kind="tool"] { text-align: left; padding: 9px 12px;
                           border: 1px solid transparent;
                           background: transparent; border-radius: 8px; }
QPushButton[kind="tool"]:hover { background: %(bg3)s; }
QPushButton[kind="tool"]:checked { background: %(sel)s;
                                   border-color: %(accent)s; font-weight: 600; }
QPushButton[kind="cat"] { text-align: left; padding: 9px 12px;
                          border: none; background: transparent;
                          border-radius: 8px; color: %(dim)s; }
QPushButton[kind="cat"]:hover { background: %(bg3)s; color: %(text)s; }
QPushButton[kind="cat"]:checked { background: %(sel)s; color: %(text)s;
                                  font-weight: 600; }

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QDateEdit {
    background: %(bg2)s; border: 1px solid %(line2)s; border-radius: 7px;
    padding: 6px 9px; selection-background-color: %(accent)s;
    selection-color: %(accent_t)s; color: %(text)s; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {
    border-color: %(accent)s; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: %(faint)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: %(bg2)s; border: 1px solid %(line2)s;
    selection-background-color: %(sel)s; selection-color: %(text)s;
    padding: 4px; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button { width: 16px;
    background: %(bg3)s; border: none; }

QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px;
    border: 1px solid %(line2)s; background: %(bg2)s; border-radius: 4px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: %(accent)s; border-color: %(accent2)s; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: %(accent)s; }

QListWidget, QTreeWidget, QTableWidget {
    background: %(bg2)s; border: 1px solid %(line)s; border-radius: 9px;
    alternate-background-color: %(bg3)s; }
QListWidget::item, QTreeWidget::item { padding: 5px 6px; border-radius: 6px; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background: %(sel)s; color: %(text)s; }
QHeaderView::section { background: %(bg3)s; border: none;
    border-bottom: 1px solid %(line)s; padding: 6px; color: %(dim)s; }

QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: %(line2)s; border-radius: 5px;
    min-height: 28px; }
QScrollBar::handle:vertical:hover { background: %(dim)s; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(line2)s; border-radius: 5px;
    min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QProgressBar { background: %(bg3)s; border: none; border-radius: 6px;
    height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: %(accent)s; border-radius: 6px; }

QSplitter::handle { background: %(line)s; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

QTabWidget::pane { border: 1px solid %(line)s; border-radius: 9px;
                   background: %(card)s; }
QTabBar::tab { background: transparent; color: %(dim)s; padding: 8px 15px;
               border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: %(text)s; border-bottom-color: %(accent)s;
                        font-weight: 600; }
QTabBar::tab:hover { color: %(text)s; }

QMenuBar { background: %(bg2)s; border-bottom: 1px solid %(line)s; }
QMenuBar::item { padding: 6px 11px; background: transparent; }
QMenuBar::item:selected { background: %(sel)s; border-radius: 6px; }
QMenu { background: %(bg2)s; border: 1px solid %(line2)s; border-radius: 8px;
        padding: 5px; }
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: %(sel)s; }
QMenu::separator { height: 1px; background: %(line)s; margin: 4px 8px; }

QToolTip { background: %(bg3)s; color: %(text)s; border: 1px solid %(line2)s;
           padding: 5px 7px; border-radius: 6px; }
QStatusBar { background: %(bg2)s; border-top: 1px solid %(line)s;
             color: %(dim)s; }
QSlider::groove:horizontal { height: 4px; background: %(line)s;
                             border-radius: 2px; }
QSlider::handle:horizontal { background: %(accent)s; width: 14px;
    margin: -5px 0; border-radius: 7px; }
#DropZone { border: 2px dashed %(line2)s; border-radius: 12px;
            background: %(bg2)s; }
#DropZone[hot="true"] { border-color: %(accent)s; background: %(sel)s; }
#Canvas { background: %(canvas)s; }
"""


def stylesheet(dark: bool = True) -> str:
    return QSS % (DARK if dark else LIGHT)


def colors(dark: bool = True) -> dict:
    return DARK if dark else LIGHT
