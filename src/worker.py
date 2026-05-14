from PySide6.QtCore import QThread, Signal

from .steam_api import fetch_game_name


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
