import re


def parse_game_lua(content):
    simple_appids = []
    depot_ids = set()

    for line in content.splitlines():
        line = line.strip()
        m = re.match(r'^addappid\((\d+)\)$', line)
        if m:
            simple_appids.append(m.group(1))
            continue
        m = re.match(r'^addappid\((\d+),\s*0,\s*"[^"]+"\)', line)
        if m:
            depot_ids.add(m.group(1))
            continue

    return simple_appids, depot_ids


def parse_manifest_filename(filename):
    m = re.match(r'^(\d+)_(\d+)\.manifest$', filename)
    if m:
        return m.group(1), m.group(2)
    return None, None
