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


class AuditWorker(QThread):
    appid_done = Signal(str, object)
    all_done = Signal(list)
    progress = Signal(int, int)

    def __init__(self, manifest_appids):
        super().__init__()
        self.manifest_appids = manifest_appids

    def run(self):
        total = len(self.manifest_appids)
        base_games = {}

        for i, appid in enumerate(self.manifest_appids):
            info = fetch_dlc_list(appid)
            self.appid_done.emit(appid, info)
            self.progress.emit(i + 1, total)
            if info and info['type'] == 'game' and info['dlcs']:
                base_games[appid] = info

        manifest_set = set(self.manifest_appids)
        missing = []
        for base_id, info in base_games.items():
            for dlc_id in info['dlcs']:
                s_dlc = str(dlc_id)
                if s_dlc not in manifest_set:
                    name = fetch_game_name(s_dlc) or f"AppID {s_dlc}"
                    missing.append({
                        'appid': s_dlc,
                        'name': name,
                        'parent_appid': base_id,
                        'parent_name': info['name'],
                    })

        self.all_done.emit(missing)
