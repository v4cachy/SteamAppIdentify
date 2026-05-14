import os
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView, QMessageBox,
    QProgressBar, QFrame, QFileDialog, QApplication, QMenu,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QColor, QPalette, QIcon, QPixmap,
    QAction, QPainter, QPen, QBrush, QFont as QPainterFont,
    QLinearGradient,
)

from .worker import LookupWorker
from .file_ops import extract_appid, sanitize_filename, rename_file


def _make_palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor('#f4f5f7'))
    p.setColor(QPalette.WindowText, QColor('#111827'))
    p.setColor(QPalette.Base, QColor('#ffffff'))
    p.setColor(QPalette.AlternateBase, QColor('#f9fafb'))
    p.setColor(QPalette.Text, QColor('#111827'))
    p.setColor(QPalette.Button, QColor('#5b6abf'))
    p.setColor(QPalette.ButtonText, QColor('#ffffff'))
    p.setColor(QPalette.Highlight, QColor('#5b6abf'))
    p.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    p.setColor(QPalette.ToolTipBase, QColor('#ffffff'))
    p.setColor(QPalette.ToolTipText, QColor('#111827'))
    p.setColor(QPalette.PlaceholderText, QColor('#9ca3af'))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor('#d1d5db'))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor('#d1d5db'))
    p.setColor(QPalette.Disabled, QPalette.Button, QColor('#e5e7eb'))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor('#d1d5db'))
    return p


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
    p.setPen(QPen(QColor('#6b7280'), 2.5))
    p.drawLine(size // 2, size - 10, size // 2, 14)
    p.drawLine(size // 2, 14, size // 2 - 10, 26)
    p.drawLine(size // 2, 14, size // 2 + 10, 26)
    p.drawLine(6, size - 10, size - 6, size - 10)
    p.end()
    return px


def _status_color(status):
    if status in ('Ready', 'Renamed'):
        return '#059669'
    if status == 'Looking up...':
        return '#d97706'
    if 'Error' in status or 'Not found' in status:
        return '#dc2626'
    return '#6b7280'


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
        self.setMinimumHeight(130)
        self.setCursor(Qt.DragLinkCursor)
        self.setObjectName('dropZone')

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)

        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(_draw_upload_icon().scaled(
            36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_lbl)

        self.text_lbl = QLabel(
            '<div style="text-align:center;">'
            '<span style="font-size:15px; font-weight:600;">Drop files here</span><br>'
            '<span style="font-size:12px; color:#6b7280;">'
            'or click to browse  •  any file with Steam AppID</span></div>'
        )
        self.text_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.text_lbl)

        self._set_idle()

    def _set_idle(self):
        self.setStyleSheet("""
            #dropZone {
                border: 2.5px dashed #d1d5db; border-radius: 12px;
                background: #ffffff;
            }
            #dropZone:hover {
                border-color: #5b6abf; background: #eef0fa;
            }
        """)

    def _set_drag(self):
        self.setStyleSheet("""
            #dropZone {
                border: 2.5px dashed #5b6abf; border-radius: 12px;
                background: #eef0fa;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self._set_drag()
            self.icon_lbl.setPixmap(_draw_upload_icon().scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._set_idle()
        self.icon_lbl.setPixmap(_draw_upload_icon().scaled(
            36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def dropEvent(self, event: QDropEvent):
        self._set_idle()
        self.icon_lbl.setPixmap(_draw_upload_icon().scaled(
            36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
        self.setFixedHeight(26)
        self._color = color_hex
        self._apply()

    def set_text_and_color(self, text, color_hex):
        self.setText(text)
        self._color = color_hex
        self._apply()

    def _apply(self):
        c = self._color
        self.setStyleSheet(
            f"background: {c}18; color: {c}; border: 1px solid {c}30;"
            f"border-radius: 6px; padding: 2px 10px;"
            f"font-size: 12px; font-weight: 600;"
        )


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
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName('header')
        header.setStyleSheet("""
            #header { background: #ffffff; border-bottom: 1px solid #e5e7eb; }
        """)
        header.setFixedHeight(60)

        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(20, 0, 20, 0)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(_make_icon().pixmap(32, 32))
        hdr.addWidget(icon_lbl)
        hdr.addSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        t = QLabel("SteamManfiesto")
        t.setStyleSheet("font-size: 16px; font-weight: 700; color: #111827; border: none;")
        title_col.addWidget(t)
        s = QLabel("Identify and rename your Steam files")
        s.setStyleSheet("font-size: 11px; color: #6b7280; border: none;")
        title_col.addWidget(s)
        hdr.addLayout(title_col)
        hdr.addStretch()

        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet("font-size: 13px; color: #6b7280; font-weight: 500; border: none;")
        self.lbl_count.setVisible(False)
        hdr.addWidget(self.lbl_count)
        root.addWidget(header)

        # ── Body ─────────────────────────────────────────────────────
        body_widget = QWidget()
        body_widget.setObjectName('body')
        body_widget.setStyleSheet("#body { background: #f4f5f7; }")
        body = QVBoxLayout(body_widget)
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(12)

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_files)
        body.addWidget(self.drop_zone)

        self.progress = QProgressBar()
        self.progress.setObjectName('progress')
        self.progress.setStyleSheet("""
            #progress {
                border: none; border-radius: 6px; background: #e5e7eb;
                height: 8px; text-align: center; font-size: 11px; color: #6b7280;
            }
            #progress::chunk {
                border-radius: 6px;
                background: qlineargradient(x1:0 y1:0, x2:1 y2:0,
                    stop:0 #5b6abf, stop:1 #7c8bdf);
            }
        """)
        self.progress.hide()
        body.addWidget(self.progress)

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
        self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #e5e7eb; border-radius: 8px;
                background: #ffffff; gridline-color: transparent;
                font-size: 13px; outline: none;
            }
            QTableWidget::item {
                padding: 8px 12px; border-bottom: 1px solid #f3f4f6;
            }
            QTableWidget::item:selected {
                background: #eef0fa; color: #111827;
            }
            QHeaderView::section {
                background: #ffffff; color: #6b7280;
                font-weight: 700; font-size: 11px;
                padding: 10px 12px; border: none;
                border-bottom: 2px solid #e5e7eb;
            }
        """)
        body.addWidget(self.table, stretch=1)

        # bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setObjectName('btn_clear')
        self.btn_clear.setStyleSheet("""
            QPushButton#btn_clear {
                background: transparent; color: #6b7280;
                border: 1px solid #d1d5db; border-radius: 8px;
                padding: 9px 20px; font-size: 13px; font-weight: 500;
            }
            QPushButton#btn_clear:hover {
                background: #f3f4f6; border-color: #9ca3af;
            }
        """)
        self.btn_clear.clicked.connect(self.clear_files)
        bottom.addWidget(self.btn_clear)
        bottom.addStretch()

        self.btn_process = QPushButton("Rename All")
        self.btn_process.setObjectName('btn_process')
        self.btn_process.setEnabled(False)
        self.btn_process.setMinimumWidth(140)
        self.btn_process.setStyleSheet("""
            QPushButton#btn_process {
                background: #5b6abf; color: #ffffff;
                border: none; border-radius: 8px;
                padding: 10px 28px; font-size: 14px; font-weight: 600;
            }
            QPushButton#btn_process:hover { background: #4a59b0; }
            QPushButton#btn_process:pressed { background: #3d4a9e; }
            QPushButton#btn_process:disabled {
                background: #e5e7eb; color: #d1d5db;
            }
        """)
        self.btn_process.clicked.connect(self.process_renames)
        bottom.addWidget(self.btn_process)
        body.addLayout(bottom)
        root.addWidget(body_widget, stretch=1)

        # status bar
        self.status_label = QLabel("Drop files to get started")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 12px; padding: 2px 16px;")
        self.status_bar = self.statusBar()
        self.status_bar.setStyleSheet("background: transparent; border: none;")
        self.status_bar.addWidget(self.status_label)

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

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
        menu.setStyleSheet("""
            QMenu { background: #ffffff; border: 1px solid #e5e7eb;
                    border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 8px 28px 8px 16px; border-radius: 4px; font-size: 13px; }
            QMenu::item:selected { background: #eef0fa; color: #5b6abf; }
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
            badge = StatusBadge(f['status'], c)
            self.table.setCellWidget(i, 3, badge)

        n = len(self.files)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    # ── Steam Lookup ────────────────────────────────────────────────────

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
        self.lbl_count.setText("")
        self.lbl_count.setVisible(False)
        self.status_label.setText("Drop files to get started")


def main():
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("SteamManfiesto")
    app.setOrganizationName("SteamManfiesto")
    app.setStyle('Fusion')
    app.setPalette(_make_palette())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
