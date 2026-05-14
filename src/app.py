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


# ── Color Palette (dark) ───────────────────────────────────────────────────

C = {
    'bg': '#0a0a0f',
    'surface': 'rgba(255,255,255,0.04)',
    'surface_hover': 'rgba(255,255,255,0.08)',
    'border': 'rgba(255,255,255,0.08)',
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


# ── Main Window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SteamManfiesto")
        self.setWindowIcon(_make_icon())
        self.setMinimumSize(800, 560)
        self.resize(880, 620)

        self.files = []
        self.worker = None

        self._build_ui()
        self._center()

    def _build_ui(self):
        self.setStyleSheet(f"""
            QMainWindow, #body {{ background: {C['bg']}; }}
            QLabel {{ color: {C['text']}; background: transparent; }}
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
        header.setFixedHeight(56)

        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(20, 0, 20, 0)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(_make_icon().pixmap(28, 28))
        hdr.addWidget(icon_lbl)
        hdr.addSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        t = QLabel("SteamManfiesto")
        t.setStyleSheet("font-size: 15px; font-weight: 700; color: #f3f4f6; border: none;")
        title_col.addWidget(t)
        s = QLabel("Rename Steam files by their AppID")
        s.setStyleSheet("font-size: 11px; color: #6b7280; border: none;")
        title_col.addWidget(s)
        hdr.addLayout(title_col)
        hdr.addStretch()

        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet("font-size: 12px; color: #6b7280; border: none;")
        self.lbl_count.setVisible(False)
        hdr.addWidget(self.lbl_count)
        root.addWidget(header)

        # ── Body ─────────────────────────────────────────────────────
        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(12)

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_files)
        body.addWidget(self.drop_zone)

        self.progress = QProgressBar()
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
        self.table.verticalHeader().setDefaultSectionSize(38)
        body.addWidget(self.table, stretch=1)

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
        body.addLayout(bottom)

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, stretch=1)

        # Status bar
        self.status_label = QLabel("Drop files with Steam AppID to rename them")
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
        self.status_label.setText("Drop files with Steam AppID to rename them")


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
