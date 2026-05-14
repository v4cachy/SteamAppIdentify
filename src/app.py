import os
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView, QMessageBox,
    QProgressBar, QFrame, QFileDialog, QApplication, QMenu, QStatusBar,
    QSplitter, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QColor, QPalette, QFont, QIcon, QPixmap,
    QAction, QPainter, QPen, QBrush, QFont as QPainterFont, 
    QLinearGradient,
)

from .worker import LookupWorker
from .file_ops import extract_appid, sanitize_filename, rename_file

# ── Color Palette ──────────────────────────────────────────────────────────

C = {
    'primary': '#5b6abf',
    'primary_hover': '#4a59b0',
    'primary_pressed': '#3d4a9e',
    'primary_light': '#eef0fa',
    'bg': '#f4f5f7',
    'surface': '#ffffff',
    'border': '#e2e4e8',
    'text': '#1e2028',
    'text_secondary': '#6b7280',
    'text_muted': '#9ca3af',
    'success': '#10b981',
    'warning': '#f59e0b',
    'error': '#ef4444',
    'header_bg': '#ffffff',
}

# ── Global Stylesheet ──────────────────────────────────────────────────────

FUSION_QSS = f"""
QMainWindow {{ background: {C['bg']}; }}
QLabel {{ color: {C['text']}; }}

QPushButton {{
    padding: 9px 24px; border-radius: 8px; font-size: 13px;
    font-weight: 600; border: none; color: white;
    background: {C['primary']};
}}
QPushButton:hover {{ background: {C['primary_hover']}; }}
QPushButton:pressed {{ background: {C['primary_pressed']}; }}
QPushButton:disabled {{ background: #d1d5db; color: #f3f4f6; }}

QPushButton#btn_clear {{
    background: transparent; color: {C['text_secondary']};
    border: 1px solid {C['border']};
}}
QPushButton#btn_clear:hover {{ background: #f3f4f6; border-color: #c4c8ce; }}

QProgressBar {{
    border: none; border-radius: 6px; background: {C['border']};
    height: 8px; text-align: center; font-size: 11px; color: {C['text_muted']};
}}
QProgressBar::chunk {{
    border-radius: 6px; background: qlineargradient(
        x1:0 y1:0, x2:1 y2:0,
        stop:0 {C['primary']}, stop:1 #7c8bdf
    );
}}

QTableWidget {{
    border: 1px solid {C['border']}; border-radius: 8px;
    background: {C['surface']}; gridline-color: transparent;
    font-size: 13px; outline: none;
}}
QTableWidget::item {{
    padding: 8px 12px; border-bottom: 1px solid #f0f1f3;
}}
QTableWidget::item:selected {{
    background: {C['primary_light']}; color: {C['text']};
}}
QTableWidget::item:hover {{
    background: #f8f9fc;
}}
QHeaderView::section {{
    background: {C['surface']}; color: {C['text_secondary']};
    font-weight: 700; font-size: 11px; letter-spacing: 0.5px;
    padding: 10px 12px; border: none; border-bottom: 2px solid {C['border']};
    text-transform: uppercase;
}}

QMenu {{
    background: {C['surface']}; border: 1px solid {C['border']};
    border-radius: 8px; padding: 4px;
}}
QMenu::item {{
    padding: 8px 28px 8px 16px; border-radius: 4px; font-size: 13px;
}}
QMenu::item:selected {{ background: {C['primary_light']}; color: {C['primary']}; }}

QStatusBar {{
    background: transparent; border: none; color: {C['text_secondary']};
    font-size: 12px; padding: 2px 8px;
}}
"""

# ── Helpers ────────────────────────────────────────────────────────────────

def _make_icon():
    px = QPixmap(64, 64)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 64, 64)
    g.setColorAt(0, QColor('#5b6abf'))
    g.setColorAt(1, QColor('#7c8bdf'))
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


def _draw_upload_icon(size=48):
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(C['text_muted'])
    p.setPen(QPen(c, 2.5))
    # arrow shaft
    p.drawLine(size // 2, size - 10, size // 2, 14)
    # arrow head
    p.drawLine(size // 2, 14, size // 2 - 10, 26)
    p.drawLine(size // 2, 14, size // 2 + 10, 26)
    # tray
    p.drawLine(6, size - 10, size - 6, size - 10)
    p.end()
    return px


def _status_badge_color(status):
    if status in ('Ready', 'Renamed'):
        return C['success']
    if status == 'Looking up...':
        return C['warning']
    if 'Error' in status or 'Not found' in status:
        return C['error']
    return C['text_muted']


def _new_name_preview(f):
    if not f['game_name']:
        return ''
    ext = os.path.splitext(f['path'])[1]
    return sanitize_filename(f['game_name']) + ext


# ── Drop Zone ───────────────────────────────────────────────────────────────

class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setCursor(Qt.DragLinkCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)

        self.icon_label = QLabel()
        self.icon_label.setPixmap(_draw_upload_icon().scaled(
            40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.icon_label)

        self.text_label = QLabel(
            '<span style="font-size:15px; font-weight:600; color:'
            f'{C["text_secondary"]};">Drop files here</span><br>'
            '<span style="font-size:12px; color:'
            f'{C["text_muted"]};">or click to browse  •  any file with Steam AppID</span>'
        )
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.text_label)

        self._set_idle()

    def _set_idle(self):
        self.setStyleSheet(f"""
            DropZone {{
                border: 2.5px dashed {C['border']};
                border-radius: 12px;
                background: {C['surface']};
            }}
            DropZone:hover {{
                border-color: {C['primary']};
                background: {C['primary_light']};
            }}
        """)

    def _set_drag(self):
        self.setStyleSheet(f"""
            DropZone {{
                border: 2.5px dashed {C['primary']};
                border-radius: 12px;
                background: {C['primary_light']};
            }}
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self._set_drag()
            self.icon_label.setPixmap(_draw_upload_icon().scaled(
                44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._set_idle()
        self.icon_label.setPixmap(_draw_upload_icon().scaled(
            40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def dropEvent(self, event: QDropEvent):
        self._set_idle()
        self.icon_label.setPixmap(_draw_upload_icon().scaled(
            40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
    def __init__(self, text, color):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(26)
        self.set_color(color)

    def set_color(self, color):
        self.setStyleSheet(f"""
            background: {color}18; color: {color};
            border: 1px solid {color}30;
            border-radius: 6px; padding: 2px 10px;
            font-size: 12px; font-weight: 600;
        """)


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SteamManfiesto")
        self.setWindowIcon(_make_icon())
        self.setMinimumSize(840, 580)
        self.resize(900, 640)

        self.files = []
        self.worker = None

        self._build_ui()
        self._center()

    def _build_ui(self):
        self.setStyleSheet(FUSION_QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{ background: {C['header_bg']}; border-bottom: 1px solid {C['border']}; }}
        """)
        header.setFixedHeight(64)

        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(24, 0, 24, 0)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(_make_icon().pixmap(36, 36))
        hdr.addWidget(icon_lbl)
        hdr.addSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        t = QLabel("SteamManfiesto")
        t.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {C['text']}; border: none;")
        title_col.addWidget(t)
        s = QLabel("Identify and rename your Steam files")
        s.setStyleSheet(f"font-size: 12px; color: {C['text_muted']}; border: none;")
        title_col.addWidget(s)
        hdr.addLayout(title_col)
        hdr.addStretch()

        self.lbl_count = QLabel("No files")
        self.lbl_count.setStyleSheet(
            f"font-size: 13px; color: {C['text_secondary']}; font-weight: 500; border: none;")
        hdr.addWidget(self.lbl_count)
        root.addWidget(header)

        # ── Content ──────────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet(f"background: {C['bg']};")
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(14)

        # drop zone
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_files)
        body.addWidget(self.drop_zone)

        # progress
        self.progress = QProgressBar()
        self.progress.hide()
        body.addWidget(self.progress)

        # table
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
        self.table.verticalHeader().setDefaultSectionSize(40)
        body.addWidget(self.table, stretch=1)

        # bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setObjectName("btn_clear")
        self.btn_clear.clicked.connect(self.clear_files)

        bottom.addWidget(self.btn_clear)
        bottom.addStretch()

        self.btn_process = QPushButton("Rename All")
        self.btn_process.setEnabled(False)
        self.btn_process.setMinimumWidth(140)
        self.btn_process.clicked.connect(self.process_renames)
        bottom.addWidget(self.btn_process)

        body.addLayout(bottom)
        root.addWidget(content, stretch=1)

        # status bar
        self.status_bar = QStatusBar()
        self.status_bar.setFixedHeight(32)
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Drop files to get started")
        self.status_label.setStyleSheet(f"color: {C['text_muted']};")
        self.status_bar.addWidget(self.status_label)

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

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

    # ── Context menu ────────────────────────────────────────────────────

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
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

    # ── Data ────────────────────────────────────────────────────────────

    def add_files(self, paths):
        added = 0
        for path in paths:
            p = Path(path)
            if any(f['path'] == str(p) for f in self.files):
                continue
            stem = p.stem
            appid = extract_appid(stem)
            self.files.append({
                'path': str(p),
                'stem': stem,
                'appid': appid or '',
                'game_name': '',
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

            c = _status_badge_color(f['status'])
            badge = StatusBadge(f['status'], c)
            self.table.setCellWidget(i, 3, badge)

        self.lbl_count.setText(f"{len(self.files)} file{'s' if len(self.files) != 1 else ''}")
        self.lbl_count.setVisible(len(self.files) > 0)

    # ── Steam Lookup ────────────────────────────────────────────────────

    def lookup_all(self):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()

        items = [(i, f['appid']) for i, f in enumerate(self.files)
                 if f['appid'] and not f['game_name']]
        if not items:
            self.on_lookup_done()
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
        QTimer.singleShot(3000, lambda: self.status_label.setText(
            "Drop more files or click Rename All" if ready else "Drop more files"))

    # ── Rename ──────────────────────────────────────────────────────────

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

    # ── Clear / helpers ─────────────────────────────────────────────────

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
        self.lbl_count.setText("No files")
        self.lbl_count.setVisible(False)
        self.status_label.setText("Drop files to get started")


def main():
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("SteamManfiesto")
    app.setOrganizationName("SteamManfiesto")
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
