import os
import io
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView, QMessageBox,
    QProgressBar, QFrame, QFileDialog, QApplication, QMenu, QLineEdit,
    QListWidget, QListWidgetItem, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer, QRect
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QColor, QPalette, QIcon, QPixmap,
    QAction, QPainter, QPen, QBrush, QFont as QPainterFont,
    QLinearGradient, QFont, QImage,
)

from .worker import LookupWorker
from .file_ops import extract_appid, sanitize_filename, rename_file
from .steam_api import search_games, fetch_game_details
from .manifest_gen import generate_lua


# ── Color Palette (dark) ───────────────────────────────────────────────────

C = {
    'bg': '#0a0a0f',
    'surface': 'rgba(255,255,255,0.04)',
    'surface_hover': 'rgba(255,255,255,0.08)',
    'border': 'rgba(255,255,255,0.08)',
    'border_focus': 'rgba(167,139,250,0.3)',
    'text': '#f3f4f6',
    'text_sec': '#6b7280',
    'text_muted': '#4b5563',
    'accent': '#a78bfa',
    'accent_hover': '#8b6cf7',
    'accent_dim': 'rgba(167,139,250,0.15)',
    'success': '#34d399',
    'warning': '#fbbf24',
    'error': '#f87171',
    'header_bg': 'rgba(10,10,15,0.7)',
}

# Blob colors for animated background
BLOBS = [
    ('#7c3aed', 0.12, -200, -200, 600),
    ('#0d9488', 0.10, '30%', -150, 500),
    ('#dc2626', 0.08, 0, 0, 400),
]


def _make_icon():
    px = QPixmap(64, 64)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 64, 64)
    g.setColorAt(0, QColor('#7c3aed'))
    g.setColorAt(1, QColor('#a78bfa'))
    p.setBrush(QBrush(g))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor('white'))
    f = QPainterFont()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(px.rect(), Qt.AlignCenter, 'S')
    p.end()
    return QIcon(px)


def _status_color(status):
    if status in ('Ready', 'Renamed'):
        return C['success']
    if status == 'Looking up...':
        return C['warning']
    if 'Error' in status or 'Not found' in status:
        return C['error']
    return C['text_sec']


def _new_name_preview(f):
    if not f['game_name']:
        return ''
    ext = os.path.splitext(f['path'])[1]
    return sanitize_filename(f['game_name']) + ext


# ── Glass Card ──────────────────────────────────────────────────────────────

class GlassCard(QFrame):
    def __init__(self, children_layout=QVBoxLayout):
        super().__init__()
        self.setStyleSheet(f"""
            GlassCard {{
                background: {C['surface']};
                border: 1px solid {C['border']};
                border-radius: 12px;
            }}
        """)
        layout = children_layout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        self.setLayout(layout)


# ── Drop Zone ───────────────────────────────────────────────────────────────

class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(100)
        self.setCursor(Qt.DragLinkCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        self.label = QLabel(
            '<div style="text-align:center;">'
            '<span style="font-size:14px; font-weight:600; color:#d1d5db;">'
            'Drop files here</span><br>'
            '<span style="font-size:12px; color:#6b7280;">'
            'or click to browse</span></div>'
        )
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self._set_idle()

    def _set_idle(self):
        self.setStyleSheet(f"""
            DropZone {{
                border: 2px dashed {C['border']};
                border-radius: 10px;
                background: {C['surface']};
            }}
            DropZone:hover {{
                border-color: {C['accent']};
                background: {C['accent_dim']};
            }}
        """)

    def _set_drag(self):
        self.setStyleSheet(f"""
            DropZone {{
                border: 2px dashed {C['accent']};
                border-radius: 10px;
                background: {C['accent_dim']};
            }}
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self._set_drag()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._set_idle()

    def dropEvent(self, event: QDropEvent):
        self._set_idle()
        files = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and os.path.isfile(path):
                files.append(path)
        if files:
            self.files_dropped.emit(files)

    def mousePressEvent(self, event):
        files, _ = QFileDialog.getOpenFileNames(self, "Select files")
        if files:
            self.files_dropped.emit(files)


# ── Status Badge ────────────────────────────────────────────────────────────

class StatusBadge(QLabel):
    def __init__(self, text, color_hex):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(24)
        self._color = color_hex
        self._apply()

    def _apply(self):
        c = self._color
        r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        self.setStyleSheet(
            f"background: rgba({r},{g},{b},0.15); color: {c};"
            f"border: 1px solid rgba({r},{g},{b},0.2);"
            f"border-radius: 6px; padding: 2px 10px;"
            f"font-size: 11px; font-weight: 600;"
        )


# ── Search Dropdown ─────────────────────────────────────────────────────────

class SearchDropdown(QFrame):
    game_selected = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SearchDropdown {{
                background: #1a1a2e;
                border: 1px solid {C['border']};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: transparent; border: none; outline: none;
                font-size: 13px; color: {C['text']};
            }}
            QListWidget::item {{
                padding: 8px 10px; border-radius: 6px;
            }}
            QListWidget::item:hover, QListWidget::item:selected {{
                background: {C['accent_dim']}; color: {C['text']};
            }}
        """)
        self.list_widget.itemClicked.connect(self._on_click)
        layout.addWidget(self.list_widget)

    def show_results(self, results, anchor_widget):
        self.list_widget.clear()
        if not results:
            return
        for r in results[:8]:
            name = r.get('name', 'Unknown')
            appid = r.get('id', '?')
            item = QListWidgetItem(f"{name}  ({appid})")
            item.setData(Qt.UserRole, r)
            self.list_widget.addItem(item)

        pos = anchor_widget.mapToGlobal(
            anchor_widget.rect().bottomLeft() + QRect(0, 4, 0, 0))
        self.setMinimumWidth(anchor_widget.width())
        self.move(pos)
        self.show()

    def _on_click(self, item):
        data = item.data(Qt.UserRole)
        if data:
            self.game_selected.emit(data)
        self.hide()


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SteamManfiesto")
        self.setWindowIcon(_make_icon())
        self.setMinimumSize(860, 680)
        self.resize(920, 720)

        self.files = []
        self.worker = None
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)

        self._build_ui()
        self._center()

    def _build_ui(self):
        # Root
        self.setStyleSheet(f"""
            QMainWindow, #body {{ background: {C['bg']}; }}
            QLabel {{ color: {C['text']}; background: transparent; }}
            QLineEdit {{
                background: rgba(255,255,255,0.05); color: {C['text']};
                border: 1px solid {C['border']}; border-radius: 8px;
                padding: 10px 14px; font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {C['accent']};
                background: rgba(255,255,255,0.08);
            }}
            QTableWidget {{
                border: 1px solid {C['border']}; border-radius: 8px;
                background: {C['surface']}; gridline-color: transparent;
                font-size: 13px; outline: none;
            }}
            QTableWidget::item {{
                padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.04);
                color: {C['text']};
            }}
            QTableWidget::item:selected {{
                background: {C['accent_dim']}; color: {C['text']};
            }}
            QHeaderView::section {{
                background: transparent; color: {C['text_sec']};
                font-weight: 700; font-size: 11px;
                padding: 10px 12px; border: none;
                border-bottom: 1px solid {C['border']};
            }}
            QProgressBar {{
                border: none; border-radius: 6px;
                background: rgba(255,255,255,0.06);
                height: 6px; text-align: center; font-size: 11px;
                color: {C['text_sec']};
            }}
            QProgressBar::chunk {{
                border-radius: 6px;
                background: qlineargradient(x1:0 y1:0, x2:1 y2:0,
                    stop:0 #7c3aed, stop:1 #a78bfa);
            }}
            QScrollBar:vertical {{
                background: transparent; width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.1); border-radius: 4px;
                min-height: 30px;
            }}
        """)

        central = QWidget()
        central.setObjectName('body')
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background: {C['header_bg']};
                border-bottom: 1px solid {C['border']};
            }}
        """)
        header.setFixedHeight(58)

        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(20, 0, 20, 0)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(_make_icon().pixmap(30, 30))
        hdr.addWidget(icon_lbl)
        hdr.addSpacing(10)

        t = QLabel("SteamManfiesto")
        t.setStyleSheet("font-size: 15px; font-weight: 700; color: #f3f4f6; border: none;")
        hdr.addWidget(t)
        hdr.addStretch()
        root.addWidget(header)

        # ── Body ─────────────────────────────────────────────────────
        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(16)

        # ── Search Card ──────────────────────────────────────────────
        search_card = GlassCard()
        sc = search_card.layout()

        title = QLabel("Search Game")
        title.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {C['text']}; border: none;")
        sc.addWidget(title)

        # Search input row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter App ID or search by game name…")
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._on_search_enter)
        search_row.addWidget(self.search_input, stretch=1)

        self.btn_generate = QPushButton("Generate Lua Manifest")
        self.btn_generate.setEnabled(False)
        self.btn_generate.setStyleSheet(f"""
            QPushButton {{
                background: {C['accent']}; color: #ffffff;
                border: none; border-radius: 8px;
                padding: 10px 20px; font-size: 13px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {C['accent_hover']}; }}
            QPushButton:disabled {{
                background: rgba(255,255,255,0.06); color: {C['text_muted']};
            }}
        """)
        self.btn_generate.clicked.connect(self._generate_manifest)
        search_row.addWidget(self.btn_generate)
        sc.addLayout(search_row)

        # Dropdown for search results
        self.dropdown = SearchDropdown()
        self.dropdown.game_selected.connect(self._on_game_selected)

        # Details panel (hidden initially)
        self.details_panel = QFrame()
        self.details_panel.setStyleSheet(f"""
            QFrame {{
                background: rgba(255,255,255,0.03);
                border: 1px solid {C['border']};
                border-radius: 10px;
            }}
        """)
        self.details_panel.setVisible(False)
        dp = QHBoxLayout(self.details_panel)
        dp.setContentsMargins(16, 16, 16, 16)
        dp.setSpacing(16)

        # Header image
        self.header_img = QLabel()
        self.header_img.setFixedSize(184, 86)
        self.header_img.setStyleSheet("border-radius: 6px; background: rgba(255,255,255,0.05);")
        self.header_img.setAlignment(Qt.AlignCenter)
        self.header_img.setText("")
        dp.addWidget(self.header_img)

        # Text details
        detail_col = QVBoxLayout()
        detail_col.setSpacing(4)

        self.detail_name = QLabel()
        self.detail_name.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {C['text']}; border: none;")
        detail_col.addWidget(self.detail_name)

        self.detail_appid = QLabel()
        self.detail_appid.setStyleSheet(f"font-size: 12px; color: {C['accent']}; border: none;")
        detail_col.addWidget(self.detail_appid)

        self.detail_genres = QLabel()
        self.detail_genres.setStyleSheet(f"font-size: 12px; color: {C['text_sec']}; border: none;")
        detail_col.addWidget(self.detail_genres)

        self.detail_release = QLabel()
        self.detail_release.setStyleSheet(f"font-size: 12px; color: {C['text_sec']}; border: none;")
        detail_col.addWidget(self.detail_release)

        detail_col.addStretch()
        dp.addLayout(detail_col, stretch=1)
        sc.addWidget(self.details_panel)

        # ── Divider ────────────────────────────────────────────────
        divider = QFrame()
        divider.setStyleSheet(f"background: {C['border']}; max-height: 1px;")
        divider.setFixedHeight(1)
        body.addWidget(search_card)

        # ── Files section ────────────────────────────────────────────
        files_section = QVBoxLayout()
        files_section.setSpacing(10)

        files_header = QHBoxLayout()
        lbl_files = QLabel("Files")
        lbl_files.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {C['text']}; border: none;")
        files_header.addWidget(lbl_files)
        files_header.addStretch()

        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet(f"font-size: 12px; color: {C['text_sec']}; border: none;")
        self.lbl_count.setVisible(False)
        files_header.addWidget(self.lbl_count)
        files_section.addLayout(files_header)

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_files)
        files_section.addWidget(self.drop_zone)

        self.progress = QProgressBar()
        self.progress.hide()
        files_section.addWidget(self.progress)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["File", "AppID", "Game Name", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(80)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.verticalHeader().setDefaultSectionSize(38)
        files_section.addWidget(self.table, stretch=1)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C['text_sec']};
                border: 1px solid {C['border']}; border-radius: 8px;
                padding: 9px 20px; font-size: 13px; font-weight: 500;
            }}
            QPushButton:hover {{
                background: {C['surface_hover']}; border-color: {C['text_muted']};
            }}
        """)
        self.btn_clear.clicked.connect(self.clear_files)
        bottom.addWidget(self.btn_clear)
        bottom.addStretch()

        self.btn_process = QPushButton("Rename All")
        self.btn_process.setEnabled(False)
        self.btn_process.setMinimumWidth(130)
        self.btn_process.setStyleSheet(f"""
            QPushButton {{
                background: {C['accent']}; color: #ffffff;
                border: none; border-radius: 8px;
                padding: 10px 24px; font-size: 13px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {C['accent_hover']}; }}
            QPushButton:disabled {{
                background: rgba(255,255,255,0.06); color: {C['text_muted']};
            }}
        """)
        self.btn_process.clicked.connect(self.process_renames)
        bottom.addWidget(self.btn_process)
        files_section.addLayout(bottom)
        body.addLayout(files_section, stretch=1)

        # Wrap body in a QWidget so stylesheet applies
        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, stretch=1)

        # Status bar
        self.status_label = QLabel("Search for a game or drop files to rename")
        self.status_label.setStyleSheet(f"color: {C['text_sec']}; font-size: 12px; padding: 2px 16px;")
        sb = self.statusBar()
        sb.setStyleSheet("background: rgba(255,255,255,0.02); border-top: 1px solid rgba(255,255,255,0.04);")
        sb.addWidget(self.status_label)

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

    # ── Search ──────────────────────────────────────────────────────

    def _on_search_changed(self, text):
        self._search_timer.stop()
        self.details_panel.setVisible(False)
        self.btn_generate.setEnabled(False)

        if len(text.strip()) < 2:
            self.dropdown.hide()
            return

        # Check if it's a numeric AppID
        if text.strip().isdigit():
            return

        self._search_timer.start(350)

    def _on_search_enter(self):
        self._search_timer.stop()
        text = self.search_input.text().strip()
        if not text:
            return

        if text.isdigit():
            self._lookup_appid(text)
        else:
            self._do_search()

    def _do_search(self):
        text = self.search_input.text().strip()
        if len(text) < 2:
            return
        results = search_games(text)
        if results:
            self.dropdown.show_results(results, self.search_input)

    def _lookup_appid(self, appid):
        self.status_label.setText(f"Looking up AppID {appid}…")
        details = fetch_game_details(appid)
        if details:
            self._show_details(details)
            self.status_label.setText(f"Found: {details['name']}")
        else:
            self.status_label.setText(f"AppID {appid} not found")

    def _on_game_selected(self, data):
        appid = str(data.get('id', ''))
        self.search_input.setText(appid)
        self._lookup_appid(appid)

    def _show_details(self, details):
        self.detail_name.setText(details.get('name', ''))
        self.detail_appid.setText(f"AppID: {details.get('appid', '')}")
        genres = details.get('genres', [])
        self.detail_genres.setText(f"Genres: {', '.join(genres) if genres else 'N/A'}")
        self.detail_release.setText(f"Released: {details.get('releaseDate', 'N/A')}")

        # Try to load header image
        header_url = details.get('headerImage', '')
        if header_url:
            try:
                import urllib.request
                req = urllib.request.Request(header_url,
                    headers={'User-Agent': 'SteamManfiesto/1.0'})
                with urllib.request.urlopen(req, timeout=5) as r:
                    img_data = r.read()
                img = QImage()
                img.loadFromData(img_data)
                if not img.isNull():
                    pix = QPixmap.fromImage(img).scaled(
                        184, 86, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.header_img.setPixmap(pix)
            except Exception:
                self.header_img.setText("No image")
        else:
            self.header_img.setText("No image")

        self.details_panel.setVisible(True)
        self._selected_details = details
        self.btn_generate.setEnabled(True)

    def _generate_manifest(self):
        if not hasattr(self, '_selected_details'):
            return
        d = self._selected_details
        appid = d.get('appid', '')
        name = d.get('name', '')
        if not appid or not name:
            return

        lua_content = generate_lua(appid, name)
        safe_name = sanitize_filename(name)
        default_name = f"{safe_name}.lua"

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Lua Manifest", default_name,
            "Lua files (*.lua)")
        if not path:
            return

        with open(path, 'w', encoding='utf-8') as f:
            f.write(lua_content)

        self.status_label.setText(f"Lua manifest saved: {os.path.basename(path)}")
        QMessageBox.information(self, "Saved",
            f"Lua manifest saved to:\n{path}\n\n"
            f"Place this file in:\nSteam/config/stplug-in/")

    # ── Events ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(2000)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            self._remove_selected()
        super().keyPressEvent(event)

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: #1a1a2e; border: 1px solid {C['border']};
                border-radius: 8px; padding: 4px;
            }}
            QMenu::item {{
                padding: 8px 28px 8px 16px; border-radius: 4px; font-size: 13px;
                color: {C['text']};
            }}
            QMenu::item:selected {{ background: {C['accent_dim']}; color: {C['accent']}; }}
        """)
        a = QAction("Remove from list", self)
        a.triggered.connect(lambda: self._remove_rows([row]))
        menu.addAction(a)
        a2 = QAction("Clear all", self)
        a2.triggered.connect(self.clear_files)
        menu.addAction(a2)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_selected(self):
        rows = sorted(set(i.row() for i in self.table.selectedIndexes()), reverse=True)
        self._remove_rows(rows)

    def _remove_rows(self, rows):
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(self.files):
                self.files.pop(r)
        self.refresh_table()
        self._update_buttons()

    # ── Files ────────────────────────────────────────────────────────────

    def add_files(self, paths):
        added = 0
        for path in paths:
            p = Path(path)
            if any(f['path'] == str(p) for f in self.files):
                continue
            stem = p.stem
            appid = extract_appid(stem)
            self.files.append({
                'path': str(p), 'stem': stem,
                'appid': appid or '', 'game_name': '',
                'status': 'Looking up...' if appid else 'No AppID found',
            })
            added += 1
        if added == 0:
            return
        self.refresh_table()
        self._update_buttons()
        self.lookup_all()

    def refresh_table(self):
        self.table.setRowCount(len(self.files))
        for i, f in enumerate(self.files):
            item_file = QTableWidgetItem(os.path.basename(f['path']))
            item_file.setToolTip(f['path'])
            self.table.setItem(i, 0, item_file)
            self.table.setItem(i, 1, QTableWidgetItem(f['appid']))

            game = f['game_name'] or ''
            item_game = QTableWidgetItem(game)
            if f['status'] == 'Ready' and game:
                item_game.setToolTip(f"→ {_new_name_preview(f)}")
            self.table.setItem(i, 2, item_game)

            c = _status_color(f['status'])
            self.table.setCellWidget(i, 3, StatusBadge(f['status'], c))

        n = len(self.files)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    def lookup_all(self):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()

        items = [(i, f['appid']) for i, f in enumerate(self.files)
                 if f['appid'] and not f['game_name']]
        if not items:
            self._on_lookup_done()
            return

        self.progress.setMaximum(len(items))
        self.progress.setValue(0)
        self.progress.show()
        self.btn_process.setEnabled(False)
        self.status_label.setText("Looking up games on Steam…")

        self.worker = LookupWorker(items)
        self.worker.result_ready.connect(self._on_lookup_result)
        self.worker.all_done.connect(self._on_lookup_done)
        self.worker.start()

    def _on_lookup_result(self, row, name, error):
        if error:
            self.files[row]['game_name'] = ''
            self.files[row]['status'] = f"Error: {error}"
        else:
            self.files[row]['game_name'] = name
            self.files[row]['status'] = 'Ready'
        self.refresh_table()
        self.progress.setValue(self.progress.value() + 1)

    def _on_lookup_done(self):
        self.progress.hide()
        ready = sum(1 for f in self.files if f['status'] == 'Ready')
        errors_n = sum(1 for f in self.files if f['status'].startswith('Error'))
        self.btn_process.setEnabled(ready > 0)
        parts = []
        if ready:
            parts.append(f"{ready} ready to rename")
        if errors_n:
            parts.append(f"{errors_n} failed")
        self.status_label.setText("Done — " + ", ".join(parts) if parts else "No lookups needed")
        QTimer.singleShot(4000, lambda: self.status_label.setText(
            "Drop more files or click Rename All" if ready else "Drop more files"))

    def process_renames(self):
        ready = [f for f in self.files if f['status'] == 'Ready']
        if not ready:
            return

        preview = "\n".join(
            f"  {os.path.basename(f['path'])}  →  {_new_name_preview(f)}"
            for f in ready[:20]
        ) + ("\n  …" if len(ready) > 20 else "")

        reply = QMessageBox.question(
            self, "Confirm Rename",
            f"Rename {len(ready)} file(s) to their game names?\n\n{preview}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        renamed = 0
        errors = []
        for f in ready:
            ext = os.path.splitext(f['path'])[1]
            new_name = sanitize_filename(f['game_name']) + ext
            ok, msg = rename_file(f['path'], new_name)
            if ok:
                f['status'] = 'Renamed'
                f['path'] = msg
                renamed += 1
            else:
                f['status'] = f'Error: {msg}'
                errors.append(f"{os.path.basename(f['path'])}: {msg}")

        self.refresh_table()
        self.btn_process.setEnabled(False)
        msg = f"Renamed {renamed} file(s)." if renamed else "No files renamed."
        if errors:
            msg += f"\nErrors:\n" + "\n".join(errors)
        QMessageBox.information(self, "Done", msg)
        self.status_label.setText(
            f"Renamed {renamed} file(s)" +
            (f", {len(errors)} error(s)" if errors else ""))

    def _update_buttons(self):
        ready = sum(1 for f in self.files if f['status'] == 'Ready')
        self.btn_process.setEnabled(ready > 0)
        n = len(self.files)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    def clear_files(self):
        if not self.files:
            return
        reply = QMessageBox.question(
            self, "Clear", "Remove all files from the list?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
        self.files.clear()
        self.table.setRowCount(0)
        self.btn_process.setEnabled(False)
        self.lbl_count.setText("")
        self.lbl_count.setVisible(False)
        self.status_label.setText("Search for a game or drop files to rename")


def main():
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("SteamManfiesto")
    app.setOrganizationName("SteamManfiesto")
    app.setStyle('Fusion')

    p = QPalette()
    p.setColor(QPalette.Window, QColor('#0a0a0f'))
    p.setColor(QPalette.WindowText, QColor('#f3f4f6'))
    p.setColor(QPalette.Base, QColor('rgba(255,255,255,0.04)'))
    p.setColor(QPalette.Text, QColor('#f3f4f6'))
    p.setColor(QPalette.Button, QColor('#a78bfa'))
    p.setColor(QPalette.ButtonText, QColor('#ffffff'))
    p.setColor(QPalette.Highlight, QColor('#a78bfa'))
    p.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    p.setColor(QPalette.ToolTipBase, QColor('#1a1a2e'))
    p.setColor(QPalette.ToolTipText, QColor('#f3f4f6'))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor('#4b5563'))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor('#4b5563'))
    app.setPalette(p)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
