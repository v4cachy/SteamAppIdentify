import os
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

from .lua_parser import parse_game_lua, parse_manifest_filename
from .zip_ops import is_zip, list_contents
from .acf_parser import parse_appmanifest
from .file_ops import extract_appid, sanitize_filename, rename_file
from .worker import LookupWorker, BulkAuditWorker


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
    if '✓' in status or 'Renamed' in status:
        return C['success']
    if '✗' in status or 'Missing' in status or 'Error' in status:
        return C['error']
    if 'Looking' in status or '...' in status or 'Pending' in status:
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
        self.lookup_worker = None
        self.audit_worker = None
        self.zip_data = {}
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
        s = QLabel("Audit game files & rename by AppID")
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

        self.btn_rename = QPushButton("Rename All")
        self.btn_rename.setEnabled(False)
        self.btn_rename.setMinimumWidth(120)
        self.btn_rename.setStyleSheet(f"""
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
        self.btn_rename.clicked.connect(self.process_renames)
        bottom.addWidget(self.btn_rename)

        self.btn_check = QPushButton("Check DLCs")
        self.btn_check.setEnabled(False)
        self.btn_check.setMinimumWidth(120)
        self.btn_check.setStyleSheet(f"""
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
        self.btn_check.clicked.connect(self.start_audit)
        bottom.addWidget(self.btn_check)

        body.addLayout(bottom)

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, stretch=1)

        self.status_label = QLabel("Drop zips or files to audit / rename")
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
        for w in (self.lookup_worker, self.audit_worker):
            if w and w.isRunning():
                w.quit()
                w.wait(2000)
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
        a2.triggered.connect(self.clear_all)
        menu.addAction(a2)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_selected(self):
        rows = sorted(set(i.row() for i in self.table.selectedIndexes()), reverse=True)
        self._remove_rows(rows)

    def _remove_rows(self, rows):
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(self.items):
                item = self.items[r]
                if item.get('source_zip') and item['source_zip'] in self.zip_data:
                    src = item['source_zip']
                    self.zip_data[src]['item_indices'].discard(r)
                self.items.pop(r)
        self._rebuild_item_indices()
        self.refresh_table()
        self._update_buttons()

    def _rebuild_item_indices(self):
        for src, zd in self.zip_data.items():
            zd['item_indices'] = {i for i, it in enumerate(self.items)
                                  if it.get('source_zip') == src}

    # ── Drop handling ─────────────────────────────────────────────────────

    def on_files_dropped(self, paths):
        zips = [p for p in paths if is_zip(p)]
        others = [p for p in paths if not is_zip(p)]

        if zips:
            for zp in zips:
                self._load_zip(zp)
            self._process_pending_zips()

        if others:
            self._load_files(others)

    # ── Zip handling ──────────────────────────────────────────────────────

    def _load_zip(self, zip_path):
        self.zip_data[zip_path] = {'pending': True, 'zip_path': zip_path}

    def _process_pending_zips(self):
        for zp in list(self.zip_data.keys()):
            if self.zip_data[zp].get('pending'):
                self._process_single_zip(zp)

    def _process_single_zip(self, zip_path):
        try:
            lua_files, manifest_files, acf_files, _ = list_contents(zip_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read zip:\n{zip_path}\n{e}")
            self.zip_data.pop(zip_path, None)
            return

        if not lua_files and not acf_files:
            QMessageBox.information(self, "No Game Data",
                                    f"No .lua or .acf files in:\n{os.path.basename(zip_path)}")
            self.zip_data.pop(zip_path, None)
            return

        depot_ids_with_manifests = set()
        manifest_ids = set()
        for mf in manifest_files:
            depot_id, mid = parse_manifest_filename(mf)
            if depot_id:
                depot_ids_with_manifests.add(depot_id)
                manifest_ids.add(mf)

        self.zip_data[zip_path] = {
            'zip_path': zip_path,
            'pending': False,
            'simple_appids': [],
            'depot_ids': depot_ids_with_manifests,
            'manifest_ids': manifest_ids,
            'base_appid': None,
            'item_indices': set(),
        }
        zd = self.zip_data[zip_path]

        if lua_files:
            lf = lua_files[0]
            base_appid = os.path.splitext(lf['filename'])[0]
            zd['base_appid'] = base_appid
            simple_appids, lua_depot_ids = parse_game_lua(lf['content'])
            zd['simple_appids'] = simple_appids

            for appid in simple_appids:
                is_base = (appid == base_appid)
                appid_in_depots = appid in depot_ids_with_manifests or appid in lua_depot_ids
                idx = len(self.items)
                self.items.append({
                    'file': lf['filename'],
                    'appid': appid,
                    'name': '',
                    'type': 'Base Game' if is_base else '',
                    'status': 'Has manifest' if appid_in_depots else 'No manifest',
                    'row_type': 'game_content',
                    'path': '',
                    'source_zip': zip_path,
                    'is_base': is_base,
                    'has_manifest': appid_in_depots,
                })
                zd['item_indices'].add(idx)

        if acf_files:
            for af in acf_files:
                appid, name = parse_appmanifest(af['content'])
                idx = len(self.items)
                self.items.append({
                    'file': af['filename'],
                    'appid': appid or '?',
                    'name': name or '?',
                    'type': '',
                    'status': 'Pending',
                    'row_type': 'manifest',
                    'path': '',
                    'source_zip': zip_path,
                    'is_base': False,
                    'has_manifest': True,
                })
                zd['item_indices'].add(idx)

        total_items = len(zd['item_indices'])
        self.refresh_table()
        self._update_buttons()
        self.status_label.setText(
            f"Loaded {os.path.basename(zip_path)} — "
            f"{len(lua_files)} .lua, {len(manifest_files)} .manifest, "
            f"{len(acf_files)} .acf")

        self._lookup_zip_names(zip_path)

    def _lookup_zip_names(self, zip_path):
        zd = self.zip_data.get(zip_path)
        if not zd:
            return
        appids = []
        for idx in zd['item_indices']:
            item = self.items[idx]
            if item['appid'] and item['appid'] not in ('?', '—'):
                appids.append((idx, item['appid']))
                item['status'] = 'Looking up...'

        if not appids:
            return

        self.refresh_table()
        self.btn_check.setEnabled(False)
        self.btn_rename.setEnabled(False)
        self.progress.setMaximum(len(appids))
        self.progress.setValue(0)
        self.progress.show()

        self.lookup_worker = LookupWorker(appids)
        self.lookup_worker.result_ready.connect(self._on_lookup_result)
        self.lookup_worker.all_done.connect(self._on_lookup_batch_done)
        self.lookup_worker.start()

    def _on_lookup_result(self, row, name, error):
        if error:
            self.items[row]['name'] = ''
            self.items[row]['status'] = f"Lookup failed: {error}"
        else:
            self.items[row]['name'] = name
            status = self.items[row].get('status', '')
            if status == 'Looking up...':
                self.items[row]['status'] = 'Has manifest' if self.items[row].get('has_manifest') else 'No manifest'
        self.refresh_table()
        self.progress.setValue(self.progress.value() + 1)

    def _on_lookup_batch_done(self):
        self.progress.hide()
        can_rename = any(i['status'] == 'Ready' and i['path'] for i in self.items)
        can_rename_zip = any(
            any(i.get('is_base') and i['name'] for i in self.items if i.get('source_zip') == zp)
            for zp in self.zip_data
        )
        can_audit = bool(self.zip_data)
        self.btn_rename.setEnabled(can_rename or can_rename_zip)
        self.btn_check.setEnabled(can_audit)
        self.status_label.setText(
            f"Names looked up. Click 'Check DLCs' to audit {len(self.zip_data)} zip(s).")

    # ── Loose file handling ───────────────────────────────────────────────

    def _load_files(self, paths):
        for path in paths:
            p = Path(path)
            if p.suffix == '.acf' and p.stem.startswith('appmanifest_'):
                try:
                    content = p.read_text(encoding='utf-8', errors='replace')
                    appid, name = parse_appmanifest(content)
                    self.items.append({
                        'file': p.name, 'appid': appid or '?', 'name': name or '?',
                        'type': '', 'status': 'Pending', 'row_type': 'manifest',
                        'path': '', 'source_zip': None, 'is_base': False, 'has_manifest': True,
                    })
                except Exception as e:
                    self.items.append({
                        'file': p.name, 'appid': '—', 'name': f"Error: {e}",
                        'type': '', 'status': 'Error', 'row_type': 'error',
                        'path': '', 'source_zip': None, 'is_base': False, 'has_manifest': False,
                    })
            else:
                stem = p.stem
                appid = extract_appid(stem)
                self.items.append({
                    'file': p.name, 'appid': appid or '—', 'name': '',
                    'type': '', 'status': 'Looking up...' if appid else 'No AppID found',
                    'row_type': 'rename_file' if appid else 'other',
                    'path': str(p), 'source_zip': None, 'is_base': False, 'has_manifest': bool(appid),
                })

        self.refresh_table()
        self._update_buttons()
        rename_items = [(i, item) for i, item in enumerate(self.items)
                        if item['row_type'] == 'rename_file']
        if rename_items:
            self._start_rename_lookups(rename_items)

    # ── Audit Flow ────────────────────────────────────────────────────────

    def start_audit(self):
        zip_list = [zd for zd in self.zip_data.values()
                    if zd.get('base_appid') and not zd.get('pending')]
        if not zip_list:
            self.status_label.setText("No zips with base games to audit")
            return

        for zd in zip_list:
            for idx in zd['item_indices']:
                if idx < len(self.items) and self.items[idx]['row_type'] == 'game_content':
                    self.items[idx]['type'] = ''
                    self.items[idx]['status'] = 'Looking up...'

        self.refresh_table()
        self.btn_check.setEnabled(False)
        self.progress.setMaximum(len(zip_list))
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("Checking DLCs on Steam...")

        self.audit_worker = BulkAuditWorker(zip_list)
        self.audit_worker.zip_done.connect(self._on_zip_audit_done)
        self.audit_worker.all_done.connect(self._on_audit_all_done)
        self.audit_worker.progress.connect(self._on_audit_progress)
        self.audit_worker.start()

    def _on_audit_progress(self, current, total):
        self.progress.setValue(current)

    def _on_zip_audit_done(self, zip_path, missing):
        zd = self.zip_data.get(zip_path)
        if not zd:
            return

        total_dlc = 0
        found_dlc = 0

        for idx in zd['item_indices']:
            if idx >= len(self.items):
                continue
            item = self.items[idx]
            if item['row_type'] == 'game_content':
                if item['is_base'] and item['appid'] == zd.get('base_appid'):
                    total_dlc_from_api = len(missing) + sum(
                        1 for i in zd['item_indices'] if i < len(self.items)
                        and self.items[i]['row_type'] == 'game_content'
                        and not self.items[i]['is_base']
                        and self.items[i].get('has_manifest')
                    )
                    found = sum(
                        1 for i in zd['item_indices'] if i < len(self.items)
                        and self.items[i]['row_type'] == 'game_content'
                        and not self.items[i]['is_base']
                        and self.items[i].get('has_manifest')
                    )
                    total_in_zip = sum(
                        1 for i in zd['item_indices'] if i < len(self.items)
                        and self.items[i]['row_type'] == 'game_content'
                        and not self.items[i]['is_base']
                    )
                    item['type'] = 'Base Game'
                    if missing:
                        item['status'] = f"✓ {found}/{found + len(missing)} DLCs"
                    else:
                        item['status'] = '✓ All DLCs' if found else '✓ No DLCs'
                else:
                    if item.get('has_manifest'):
                        item['status'] = '✓ Present'
                        item['type'] = 'DLC'
                        found_dlc += 1
                    else:
                        item['status'] = 'No manifest'
                        item['type'] = ''

        for m in missing:
            idx = len(self.items)
            self.items.append({
                'file': '—',
                'appid': m['appid'],
                'name': m['name'],
                'type': 'Missing DLC',
                'status': '✗ Missing',
                'row_type': 'missing_dlc',
                'path': '',
                'source_zip': zip_path,
                'is_base': False,
                'has_manifest': False,
            })
            zd['item_indices'].add(idx)

        self.refresh_table()
        if missing:
            self.status_label.setText(
                f"⚠️ {os.path.basename(zip_path)}: {len(missing)} DLC(s) missing")

    def _on_audit_all_done(self):
        self.progress.hide()
        self.btn_check.setEnabled(True)
        total_missing = sum(
            1 for i in self.items if i['row_type'] == 'missing_dlc'
        )
        if total_missing:
            self.status_label.setText(
                f"⚠️ {total_missing} DLC(s) missing across {len(self.zip_data)} zip(s)")
        else:
            self.status_label.setText("✓ All DLCs accounted for")

    # ── Table ─────────────────────────────────────────────────────────────

    def refresh_table(self):
        self.table.setRowCount(len(self.items))
        for i, item in enumerate(self.items):
            emoji = QTableWidgetItem('')
            rt = item.get('row_type', '')
            if rt == 'game_content':
                emoji.setText('🎮' if item.get('is_base') else '📦')
            elif rt == 'depot':
                emoji.setText('🗄️')
            elif rt == 'manifest':
                emoji.setText('📄')
            elif rt == 'missing_dlc':
                emoji.setText('⚠️')
            elif rt == 'rename_file':
                emoji.setText('📄')
            else:
                emoji.setText('📁')
            emoji.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, emoji)

            display_file = item['file']
            if item.get('source_zip') and not item['row_type'] == 'missing_dlc':
                display_file = f"[{os.path.basename(item['source_zip'])}] {item['file']}"
            self.table.setItem(i, 1, QTableWidgetItem(display_file))
            self.table.setItem(i, 2, QTableWidgetItem(str(item['appid'])))

            name_item = QTableWidgetItem(item['name'])
            if rt == 'rename_file' and item['status'] in ('Ready', 'Renamed') and item['name']:
                name_item.setToolTip(f"→ {sanitize_filename(item['name'])}{os.path.splitext(item['file'])[1]}")
            self.table.setItem(i, 3, name_item)

            t_item = QTableWidgetItem(item['type'])
            if item['type'] in ('Base Game',):
                t_item.setForeground(QColor(C['accent']))
            elif item['type'] in ('DLC',):
                t_item.setForeground(QColor(C['success']))
            elif item['type'] in ('Missing DLC',):
                t_item.setForeground(QColor(C['error']))
            self.table.setItem(i, 4, t_item)

            c = _status_color(item['status'])
            self.table.setCellWidget(i, 5, StatusBadge(item['status'], c))

        n = len(self.items)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    def _update_buttons(self):
        ready = sum(1 for i in self.items if i['status'] == 'Ready' and i['path'])
        can_rename_zip = any(
            any(i.get('is_base') and i['name'] for i in self.items if i.get('source_zip') == zp)
            for zp in self.zip_data
        )
        has_zips = bool(self.zip_data)
        self.btn_rename.setEnabled(ready > 0 or can_rename_zip)
        self.btn_check.setEnabled(has_zips)

    # ── Rename Flow ───────────────────────────────────────────────────────

    def _start_rename_lookups(self, items):
        self.progress.setMaximum(len(items))
        self.progress.setValue(0)
        self.progress.show()
        self.btn_rename.setEnabled(False)

        self.lookup_worker = LookupWorker(items)
        self.lookup_worker.result_ready.connect(self._on_lookup_result)
        self.lookup_worker.all_done.connect(self._on_rename_lookup_done)
        self.lookup_worker.start()

    def _on_rename_lookup_done(self):
        ready = sum(1 for i in self.items if i['status'] == 'Ready' and i['path'])
        can_rename_zip = any(
            any(i.get('is_base') and i['name'] for i in self.items if i.get('source_zip') == zp)
            for zp in self.zip_data
        )
        self.btn_rename.setEnabled(ready > 0 or can_rename_zip)
        self.status_label.setText(f"{ready} file(s) ready to rename")

    def process_renames(self):
        if self.zip_data:
            for zip_path in list(self.zip_data.keys()):
                base_items = [i for i in self.items
                              if i.get('source_zip') == zip_path and i.get('is_base') and i['name']]
                if not base_items:
                    continue
                base = base_items[0]
                new_name = sanitize_filename(base['name']) + '.zip'
                old_basename = os.path.basename(zip_path)
                reply = QMessageBox.question(
                    self, "Confirm Rename",
                    f"Rename zip file?\n\n  {old_basename}  →  {new_name}",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    continue
                ok, msg = rename_file(zip_path, new_name)
                if ok:
                    new_path = msg
                    self.zip_data[new_path] = self.zip_data.pop(zip_path)
                    self.zip_data[new_path]['zip_path'] = new_path
                    for item in self.items:
                        if item.get('source_zip') == zip_path:
                            item['source_zip'] = new_path
                    self.status_label.setText(f"✓ Renamed to {new_name}")
                    QMessageBox.information(self, "Done", f"Renamed to:\n{new_name}")
                else:
                    self.status_label.setText(f"✗ Rename failed: {msg}")
                    QMessageBox.critical(self, "Error", f"Failed to rename:\n{msg}")
            self.refresh_table()
            return

        ready = [(i, item) for i, item in enumerate(self.items)
                 if item['status'] == 'Ready' and item['path']]
        if not ready:
            return

        preview = "\n".join(
            f"  {item['file']}  →  {sanitize_filename(item['name'])}{os.path.splitext(item['file'])[1]}"
            for _, item in ready[:20]
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
        for _, item in ready:
            ext = os.path.splitext(item['file'])[1]
            new_name = sanitize_filename(item['name']) + ext
            ok, msg = rename_file(item['path'], new_name)
            if ok:
                item['status'] = 'Renamed'
                item['file'] = os.path.basename(msg)
                item['path'] = msg
                renamed += 1
            else:
                item['status'] = f'Error: {msg}'
                errors.append(f"{item['file']}: {msg}")

        self.refresh_table()
        self.btn_rename.setEnabled(False)
        msg = f"Renamed {renamed} file(s)." if renamed else "No files renamed."
        if errors:
            msg += f"\nErrors:\n" + "\n".join(errors)
        QMessageBox.information(self, "Done", msg)
        self.status_label.setText(
            f"Renamed {renamed} file(s)" +
            (f", {len(errors)} error(s)" if errors else ""))

    # ── Common ────────────────────────────────────────────────────────────

    def clear_all(self):
        if not self.items and not self.zip_data:
            return
        for w in (self.lookup_worker, self.audit_worker):
            if w and w.isRunning():
                w.quit()
                w.wait()
        self.lookup_worker = None
        self.audit_worker = None
        self.items.clear()
        self.zip_data.clear()
        self.table.setRowCount(0)
        self.btn_rename.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.lbl_count.setText("")
        self.lbl_count.setVisible(False)
        self.progress.hide()
        self.status_label.setText("Drop zips or files to audit / rename")


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
