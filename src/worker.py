from PySide6.QtCore import QThread, Signal

from .steam_api import fetch_game_name, fetch_dlc_list


class LookupWorker(QThread):
    result_ready = Signal(int, str, object)
    all_done = Signal()

    def __init__(self, items):
        super().__init__()
        self.items = items

    def run(self):
        for row, appid in self.items:
            try:
                name = fetch_game_name(appid)
                if name:
                    self.result_ready.emit(row, name, None)
                else:
                    self.result_ready.emit(row, '', 'Not found on Steam')
            except Exception as e:
                self.result_ready.emit(row, '', str(e))
        self.all_done.emit()


class BulkAuditWorker(QThread):
    progress = Signal(int, int)
    zip_done = Signal(str, list)
    all_done = Signal()

    def __init__(self, zip_data_list):
        super().__init__()
        self.zip_data_list = zip_data_list

    def run(self):
        total = len(self.zip_data_list)
        for i, zd in enumerate(self.zip_data_list):
            base_appid = zd.get('base_appid')
            if not base_appid:
                self.zip_done.emit(zd['zip_path'], [])
                self.progress.emit(i + 1, total)
                continue

            info = fetch_dlc_list(base_appid)
            present = zd.get('manifest_ids', set()) | zd.get('depot_ids', set())
            simple = set(zd.get('simple_appids', []))

            missing = []
            if info and info.get('dlcs'):
                for dlc_id in info['dlcs']:
                    s = str(dlc_id)
                    if s not in present and s not in simple:
                        name = fetch_game_name(s) or f"AppID {s}"
                        missing.append({
                            'appid': s,
                            'name': name,
                            'parent_appid': base_appid,
                            'parent_name': info['name'],
                        })

            self.zip_done.emit(zd['zip_path'], missing)
            self.progress.emit(i + 1, total)

        self.all_done.emit()
