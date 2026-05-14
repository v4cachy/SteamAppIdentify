import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel, QHeaderView, QMessageBox,
    QProgressBar, QFrame, QFileDialog, QApplication, QMenu,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QColor, QPalette, QIcon, QPixmap,
    QAction, QPainter, QBrush, QFont as QPainterFont,
    QLinearGradient,
)

from .acf_parser import parse_appmanifest
from .zip_ops import is_zip, list_manifests_in_zip, list_all_files
from .worker import AuditWorker


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
    p.drawText(px.rect(), Qt.AlignCenter, 'A')
    p.end()
    return QIcon(px)


def _status_color(status):
    if '✓' in status:
        return C['success']
    if '✗' in status or 'Missing' in status:
        return C['error']
    if 'Looking' in status or '...' in status:
        return C['warning']
    return C['text_sec']


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
            'Drop a zip or manifest files here</span><br>'
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
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select files",
            filter="Zip files (*.zip);;Manifest files (appmanifest_*.acf);;All files (*)"
        )
        if files:
            self.files_dropped.emit(files)


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


class AppIDentify(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AppIDentify")
        self.setWindowIcon(_make_icon())
        self.setMinimumSize(800, 560)
        self.resize(880, 620)

        self.items = []
        self.worker = None
        self.zip_path = None
        self.other_files = []

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
        t = QLabel("AppIDentify")
        t.setStyleSheet("font-size: 15px; font-weight: 700; color: #f3f4f6; border: none;")
        title_col.addWidget(t)
        s = QLabel("Audit Steam DLC completeness")
        s.setStyleSheet("font-size: 11px; color: #6b7280; border: none;")
        title_col.addWidget(s)
        hdr.addLayout(title_col)
        hdr.addStretch()

        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet("font-size: 12px; color: #6b7280; border: none;")
        self.lbl_count.setVisible(False)
        hdr.addWidget(self.lbl_count)
        root.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(12)

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.on_files_dropped)
        body.addWidget(self.drop_zone)

        self.progress = QProgressBar()
        self.progress.hide()
        body.addWidget(self.progress)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["", "File", "AppID", "Name", "Type", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 36)
        self.table.horizontalHeader().setMinimumSectionSize(60)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.verticalHeader().setDefaultSectionSize(38)
        body.addWidget(self.table, stretch=1)

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
        self.btn_clear.clicked.connect(self.clear_all)
        bottom.addWidget(self.btn_clear)
        bottom.addStretch()

        self.btn_check = QPushButton("Check DLCs")
        self.btn_check.setEnabled(False)
        self.btn_check.setMinimumWidth(130)
        self.btn_check.setStyleSheet(f"""
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
        self.btn_check.clicked.connect(self.start_audit)
        bottom.addWidget(self.btn_check)

        body.addLayout(bottom)

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, stretch=1)

        self.status_label = QLabel("Drop a zip or appmanifest files to audit DLCs")
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
        a.triggered.connect(lambda: self._remove_row(row))
        menu.addAction(a)
        a2 = QAction("Clear all", self)
        a2.triggered.connect(self.clear_all)
        menu.addAction(a2)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_row(self, row):
        if 0 <= row < len(self.items):
            self.items.pop(row)
        self.refresh_table()
        self._update_buttons()

    def on_files_dropped(self, paths):
        self.clear_all()
        if not paths:
            return

        for path in paths:
            if is_zip(path):
                self._load_zip(path)
                return

        self._load_manifests(paths)

    def _load_zip(self, path):
        self.zip_path = path
        self.status_label.setText("Reading zip file...")
        QTimer.singleShot(50, self._process_zip)

    def _process_zip(self):
        try:
            manifests = list_manifests_in_zip(self.zip_path)
            self.other_files = [f for f in list_all_files(self.zip_path)
                                if not f.startswith('appmanifest_') or not f.endswith('.acf')]
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read zip:\n{e}")
            self.status_label.setText("Failed to read zip")
            return

        if not manifests:
            QMessageBox.information(self, "No Manifests",
                                    "No appmanifest_*.acf files found in this zip.")
            self.status_label.setText("No manifests found in zip")
            return

        self.items = []
        for m in manifests:
            appid, name = parse_appmanifest(m['content'])
            self.items.append({
                'file': m['filename'],
                'appid': appid or '?',
                'manifest_name': name or '?',
                'type': '',
                'status': 'Pending',
                'row_type': 'manifest',
            })

        self.refresh_table()
        self._update_buttons()
        self.status_label.setText(
            f"Found {len(manifests)} manifest(s) in zip"
            + (f" + {len(self.other_files)} other file(s)" if self.other_files else "")
        )

        if self.items:
            self.start_audit()

    def _load_manifests(self, paths):
        self.items = []
        for path in paths:
            p = Path(path)
            if p.suffix == '.acf' and p.stem.startswith('appmanifest_'):
                try:
                    content = p.read_text(encoding='utf-8', errors='replace')
                    appid, name = parse_appmanifest(content)
                    self.items.append({
                        'file': p.name,
                        'appid': appid or '?',
                        'manifest_name': name or '?',
                        'type': '',
                        'status': 'Pending',
                        'row_type': 'manifest',
                    })
                except Exception as e:
                    self.items.append({
                        'file': p.name,
                        'appid': '—',
                        'manifest_name': f"Error: {e}",
                        'type': '',
                        'status': 'Error',
                        'row_type': 'error',
                    })
            else:
                self.items.append({
                    'file': p.name,
                    'appid': '—',
                    'manifest_name': 'Not a manifest file',
                    'type': '',
                    'status': 'Skipped',
                    'row_type': 'other',
                })

        if not self.items:
            return

        self.refresh_table()
        self._update_buttons()
        self.status_label.setText(f"Loaded {len(self.items)} file(s). Click 'Check DLCs' to audit.")
        self.btn_check.setEnabled(
            any(i['row_type'] == 'manifest' for i in self.items)
        )

    def refresh_table(self):
        self.table.setRowCount(len(self.items))
        for i, item in enumerate(self.items):
            emoji_item = QTableWidgetItem('')
            if item['row_type'] == 'manifest':
                emoji_item.setText('📄')
            elif item['row_type'] == 'missing_dlc':
                emoji_item.setText('⚠️')
            elif item['row_type'] == 'base_game':
                emoji_item.setText('🎮')
            else:
                emoji_item.setText('📁')
            emoji_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, emoji_item)

            self.table.setItem(i, 1, QTableWidgetItem(item['file']))
            self.table.setItem(i, 2, QTableWidgetItem(str(item['appid'])))
            self.table.setItem(i, 3, QTableWidgetItem(item['manifest_name']))

            t_item = QTableWidgetItem(item['type'])
            if item['type'] == 'Base Game':
                t_item.setForeground(QColor(C['accent']))
            elif item['type'] == 'DLC':
                t_item.setForeground(QColor(C['success']))
            elif item['type'] == 'Missing DLC':
                t_item.setForeground(QColor(C['error']))
            self.table.setItem(i, 4, t_item)

            c = _status_color(item['status'])
            self.table.setCellWidget(i, 5, StatusBadge(item['status'], c))

        n = len(self.items)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    def start_audit(self):
        appids = []
        for item in self.items:
            if item['row_type'] == 'manifest' and item['appid'] and item['appid'] != '?':
                appids.append(item['appid'])

        appids = list(dict.fromkeys(appids))
        if not appids:
            self.status_label.setText("No valid AppIDs found to check")
            return

        for item in self.items:
            if item['row_type'] == 'manifest':
                item['status'] = 'Looking up...'

        self.refresh_table()
        self.btn_check.setEnabled(False)
        self.progress.setMaximum(len(appids))
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("Querying Steam for DLC information...")

        self.worker = AuditWorker(appids)
        self.worker.appid_done.connect(self._on_appid_done)
        self.worker.all_done.connect(self._on_audit_done)
        self.worker.progress.connect(self._on_progress)
        self.worker.start()

    def _on_progress(self, current, total):
        self.progress.setValue(current)

    def _on_appid_done(self, appid, info):
        for item in self.items:
            if item['row_type'] == 'manifest' and item['appid'] == appid:
                if info:
                    item['type'] = info['type'].title()
                    item['manifest_name'] = info['name']
                    if info['dlcs']:
                        total = len(info['dlcs'])
                        found = sum(
                            1 for d in info['dlcs']
                            if str(d) in {i['appid'] for i in self.items if i['row_type'] == 'manifest'}
                        )
                        item['status'] = f"✓ {found}/{total} DLCs"
                    else:
                        item['status'] = '✓ No DLCs'
                else:
                    item['status'] = '✗ Lookup failed'
        self.refresh_table()

    def _on_audit_done(self, missing):
        self.progress.hide()
        self.btn_check.setEnabled(True)

        for m in missing:
            self.items.append({
                'file': '—',
                'appid': m['appid'],
                'manifest_name': m['name'],
                'type': 'Missing DLC',
                'status': '✗ Missing',
                'row_type': 'missing_dlc',
                'parent_name': m['parent_name'],
            })

        self.refresh_table()

        total_dlc = sum(
            1 for i in self.items if i['row_type'] == 'missing_dlc' or
            (i['row_type'] == 'manifest' and 'DLC' in i.get('type', ''))
        )
        missing_count = len(missing)

        if missing_count:
            self.status_label.setText(
                f"⚠️ {missing_count} DLC(s) missing — "
                + ", ".join(f"{m['name']} ({m['appid']})" for m in missing[:3])
                + ("..." if len(missing) > 3 else "")
            )
        else:
            manifests = [i for i in self.items if i['row_type'] == 'manifest']
            base_games = [i for i in manifests if 'DLCs' in i['status']]
            if base_games:
                self.status_label.setText(f"✓ All DLCs accounted for in {len(base_games)} base game(s)")
            else:
                self.status_label.setText("✓ No base games with DLCs found")

    def _update_buttons(self):
        has_manifests = any(i['row_type'] == 'manifest' for i in self.items)
        self.btn_check.setEnabled(has_manifests and not self.worker)

        n = len(self.items)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    def clear_all(self):
        if not self.items:
            return
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
            self.worker = None
        self.items.clear()
        self.zip_path = None
        self.other_files = []
        self.table.setRowCount(0)
        self.btn_check.setEnabled(False)
        self.lbl_count.setText("")
        self.lbl_count.setVisible(False)
        self.progress.hide()
        self.status_label.setText("Drop a zip or appmanifest files to audit DLCs")


def main():
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("AppIDentify")
    app.setOrganizationName("AppIDentify")
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

    window = AppIDentify()
    window.show()
    sys.exit(app.exec())
