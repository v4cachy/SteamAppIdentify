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
from .worker import LookupWorker, AuditWorker


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
        self.zip_path = None

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

        body.addLayout(bottom)

        body_widget = QWidget()
        body_widget.setLayout(body)
        root.addWidget(body_widget, stretch=1)

        self.status_label = QLabel("Drop a zip or files to audit / rename")
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
                self.items.pop(r)
        self.refresh_table()
        self._update_buttons()

    # ── Drop handling ─────────────────────────────────────────────────────

    def on_files_dropped(self, paths):
        self.clear_all()
        if not paths:
            return

        has_zip = any(is_zip(p) for p in paths)
        if has_zip:
            zip_path = next(p for p in paths if is_zip(p))
            self._load_zip(zip_path)
            return

        self._load_files(paths)

    def _load_zip(self, zip_path):
        self.zip_path = zip_path
        self.status_label.setText("Reading zip...")
        QTimer.singleShot(50, self._process_zip)

    def _process_zip(self):
        try:
            lua_files, manifest_files, acf_files, other = list_contents(self.zip_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read zip:\n{e}")
            self.status_label.setText("Failed to read zip")
            return

        if not lua_files and not acf_files:
            QMessageBox.information(self, "No Game Data",
                                    "No .lua or appmanifest_*.acf files found in this zip.")
            self.status_label.setText("No game data found in zip")
            return

        depot_ids_with_manifests = set()
        for mf in manifest_files:
            depot_id, _ = parse_manifest_filename(mf)
            if depot_id:
                depot_ids_with_manifests.add(depot_id)

        self.items = []

        if lua_files:
            lf = lua_files[0]
            base_appid = os.path.splitext(lf['filename'])[0]
            simple_appids, lua_depot_ids = parse_game_lua(lf['content'])

            for appid in simple_appids:
                is_base = (appid == base_appid)
                has_manifest = appid in depot_ids_with_manifests or appid in lua_depot_ids
                self.items.append({
                    'file': lf['filename'],
                    'appid': appid,
                    'name': '',
                    'type': 'Base Game' if is_base else '',
                    'status': 'Has manifest' if has_manifest else 'No manifest',
                    'row_type': 'game_content',
                    'path': '',
                    'has_manifest': has_manifest,
                    'is_base': is_base,
                })

            for depot_id in sorted(depot_ids_with_manifests):
                if depot_id not in simple_appids:
                    self.items.append({
                        'file': f"{depot_id}_*.manifest",
                        'appid': depot_id,
                        'name': '',
                        'type': 'Depot',
                        'status': 'Has manifest',
                        'row_type': 'depot',
                        'path': '',
                        'has_manifest': True,
                        'is_base': False,
                    })

        if acf_files:
            for af in acf_files:
                appid, name = parse_appmanifest(af['content'])
                self.items.append({
                    'file': af['filename'],
                    'appid': appid or '?',
                    'name': name or '?',
                    'type': '',
                    'status': 'Pending',
                    'row_type': 'manifest',
                    'path': '',
                    'has_manifest': True,
                    'is_base': False,
                })

        self.refresh_table()
        self._update_buttons()

        if manifest_files:
            self.status_label.setText(
                f"{len(lua_files)} .lua, {len(manifest_files)} .manifest, {len(acf_files)} .acf — "
                f"looking up names..." if lua_files else f"{len(acf_files)} .acf files")
        else:
            self.status_label.setText(
                f"{len(lua_files)} .lua, {len(acf_files)} .acf files — looking up names...")

        self._lookup_all_appids()

    def _load_files(self, paths):
        self.items = []
        for path in paths:
            p = Path(path)
            if p.suffix == '.acf' and p.stem.startswith('appmanifest_'):
                try:
                    content = p.read_text(encoding='utf-8', errors='replace')
                    appid, name = parse_appmanifest(content)
                    self.items.append({
                        'file': p.name, 'appid': appid or '?', 'name': name or '?',
                        'type': '', 'status': 'Pending', 'row_type': 'manifest',
                        'path': '', 'has_manifest': True, 'is_base': False,
                    })
                except Exception as e:
                    self.items.append({
                        'file': p.name, 'appid': '—', 'name': f"Error: {e}",
                        'type': '', 'status': 'Error', 'row_type': 'error',
                        'path': '', 'has_manifest': False, 'is_base': False,
                    })
            else:
                stem = p.stem
                appid = extract_appid(stem)
                self.items.append({
                    'file': p.name, 'appid': appid or '—', 'name': '',
                    'type': '', 'status': 'Looking up...' if appid else 'No AppID found',
                    'row_type': 'rename_file' if appid else 'other',
                    'path': str(p), 'has_manifest': bool(appid), 'is_base': False,
                })

        if not self.items:
            return

        self.refresh_table()
        self._update_buttons()

        rename_items = [(i, item) for i, item in enumerate(self.items)
                        if item['row_type'] == 'rename_file']
        if rename_items:
            self._start_rename_lookups(rename_items)

    def _lookup_all_appids(self):
        appids = []
        for i, item in enumerate(self.items):
            if item['appid'] and item['appid'] not in ('?', '—') and item['row_type'] in ('game_content', 'depot', 'manifest'):
                appids.append((i, item['appid']))
                item['status'] = 'Looking up...'

        if not appids:
            return

        self.refresh_table()
        self.btn_rename.setEnabled(False)
        self.progress.setMaximum(len(appids))
        self.progress.setValue(0)
        self.progress.show()

        self.lookup_worker = LookupWorker(appids)
        self.lookup_worker.result_ready.connect(self._on_lookup_result)
        self.lookup_worker.all_done.connect(self._on_zip_lookup_done)
        self.lookup_worker.start()

    def _on_lookup_result(self, row, name, error):
        if error:
            self.items[row]['name'] = ''
            self.items[row]['status'] = f"Lookup failed: {error}"
        else:
            self.items[row]['name'] = name
            self.items[row]['status'] = self.items[row].get('status', 'Ready')
            if self.items[row]['status'] == 'Looking up...':
                self.items[row]['status'] = 'Ready'
        self.refresh_table()
        self.progress.setValue(self.progress.value() + 1)

    def _on_zip_lookup_done(self):
        self.progress.hide()
        has_game_content = any(i['row_type'] == 'game_content' for i in self.items)
        if has_game_content:
            found = sum(1 for i in self.items if i.get('has_manifest') and i['name'])
            total = sum(1 for i in self.items if i['row_type'] == 'game_content')
            missing = sum(1 for i in self.items
                          if i['row_type'] == 'game_content' and not i.get('has_manifest'))
            if missing:
                self.status_label.setText(
                    f"⚠️ {missing}/{total} content items missing manifests — "
                    f"{found} present")
            else:
                self.status_label.setText(f"✓ All {total} content items have manifests")

        has_rename = any(i['row_type'] == 'rename_file' for i in self.items)
        can_rename_zip = self.zip_path and any(i.get('is_base') and i['name'] for i in self.items)
        can_rename = has_rename or can_rename_zip
        self.btn_rename.setEnabled(can_rename)

    def refresh_table(self):
        self.table.setRowCount(len(self.items))
        for i, item in enumerate(self.items):
            emoji = QTableWidgetItem('')
            if item['row_type'] == 'game_content':
                emoji.setText('🎮' if item.get('is_base') else '📦')
            elif item['row_type'] == 'depot':
                emoji.setText('🗄️')
            elif item['row_type'] == 'manifest':
                emoji.setText('📄')
            elif item['row_type'] == 'missing_dlc':
                emoji.setText('⚠️')
            elif item['row_type'] == 'rename_file':
                emoji.setText('📄')
            else:
                emoji.setText('📁')
            emoji.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, emoji)

            self.table.setItem(i, 1, QTableWidgetItem(item['file']))
            self.table.setItem(i, 2, QTableWidgetItem(str(item['appid'])))

            name_item = QTableWidgetItem(item['name'])
            if item['row_type'] == 'rename_file' and item['status'] in ('Ready', 'Renamed') and item['name']:
                name_item.setToolTip(f"→ {sanitize_filename(item['name'])}{os.path.splitext(item['file'])[1]}")
            self.table.setItem(i, 3, name_item)

            t_item = QTableWidgetItem(item['type'])
            if item['type'] in ('Base Game',):
                t_item.setForeground(QColor(C['accent']))
            elif item['type'] in ('DLC', 'Missing DLC'):
                t_item.setForeground(QColor(C['error']) if item['type'] == 'Missing DLC' else QColor(C['success']))
            self.table.setItem(i, 4, t_item)

            c = _status_color(item['status'])
            self.table.setCellWidget(i, 5, StatusBadge(item['status'], c))

        n = len(self.items)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    def _update_buttons(self):
        ready = sum(1 for i in self.items if i['status'] == 'Ready')
        self.btn_rename.setEnabled(ready > 0)
        n = len(self.items)
        self.lbl_count.setText(f"{n} file{'s' if n != 1 else ''}")
        self.lbl_count.setVisible(n > 0)

    # ── Rename Flow ───────────────────────────────────────────────────────

    def _start_rename_lookups(self, items):
        self.progress.setMaximum(len(items))
        self.progress.setValue(0)
        self.progress.show()
        self.btn_rename.setEnabled(False)

        self.lookup_worker = LookupWorker(items)
        self.lookup_worker.result_ready.connect(self._on_lookup_result)
        self.lookup_worker.all_done.connect(self._on_lookup_done)
        self.lookup_worker.start()

    def _on_lookup_done(self):
        ready = sum(1 for i in self.items if i['status'] == 'Ready')
        errors_n = sum(1 for i in self.items if i['status'].startswith('Error'))
        self.btn_rename.setEnabled(ready > 0)
        parts = []
        if ready:
            parts.append(f"{ready} ready to rename")
        if errors_n:
            parts.append(f"{errors_n} failed")
        self.status_label.setText("Done — " + ", ".join(parts) if parts else "No lookups needed")

    def process_renames(self):
        if self.zip_path:
            base_items = [i for i in self.items if i.get('is_base') and i['name']]
            if not base_items:
                return
            base = base_items[0]
            new_name = sanitize_filename(base['name']) + '.zip'
            old_basename = os.path.basename(self.zip_path)
            reply = QMessageBox.question(
                self, "Confirm Rename",
                f"Rename the zip file?\n\n  {old_basename}  →  {new_name}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return
            ok, msg = rename_file(self.zip_path, new_name)
            if ok:
                self.zip_path = msg
                for item in self.items:
                    item['status'] = 'Renamed'
                self.status_label.setText(f"✓ Renamed to {new_name}")
                QMessageBox.information(self, "Done", f"Renamed to:\n{new_name}")
            else:
                self.status_label.setText(f"✗ Rename failed: {msg}")
                QMessageBox.critical(self, "Error", f"Failed to rename:\n{msg}")
            self.refresh_table()
            self.btn_rename.setEnabled(False)
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
        if not self.items:
            return
        for w in (self.lookup_worker, self.audit_worker):
            if w and w.isRunning():
                w.quit()
                w.wait()
        self.lookup_worker = None
        self.audit_worker = None
        self.items.clear()
        self.zip_path = None
        self.table.setRowCount(0)
        self.btn_rename.setEnabled(False)
        self.lbl_count.setText("")
        self.lbl_count.setVisible(False)
        self.progress.hide()
        self.status_label.setText("Drop a zip or files to audit / rename")


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
