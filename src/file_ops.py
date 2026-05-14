import re
import shutil
from pathlib import Path


def extract_appid(stem):
    m = re.match(r'^appmanifest_(\d+)$', stem)
    if m:
        return m.group(1)
    m = re.match(r'^(\d+)$', stem)
    if m:
        return m.group(1)
    return None


def sanitize_filename(name):
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = re.sub(r'\s+', ' ', safe).strip().rstrip('. ')
    return safe[:200] or 'unknown'


def rename_file(old_path, new_name):
    old = Path(old_path)
    new = old.with_name(new_name)
    if new.exists():
        return False, f"'{new.name}' already exists"
    shutil.move(str(old), str(new))
    return True, str(new)
