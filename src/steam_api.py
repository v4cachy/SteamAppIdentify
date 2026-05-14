import json
import urllib.request

_TIMEOUT = 10
_HEADERS = {'User-Agent': 'SteamAppIdentify/1.0'}
_cache = {}

_DETAILS_URL = 'https://store.steampowered.com/api/appdetails?appids={}'


def _get_data(appid):
    if appid in _cache:
        return _cache[appid]
    try:
        url = _DETAILS_URL.format(appid)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
            entry = data.get(str(appid))
            if entry and entry.get('success'):
                _cache[appid] = entry['data']
                return entry['data']
    except Exception:
        pass
    return None


def fetch_game_type(appid):
    data = _get_data(appid)
    return data.get('type', 'unknown') if data else 'unknown'


def fetch_game_name(appid):
    data = _get_data(appid)
    return data.get('name', '') if data else None


def fetch_dlc_list(appid):
    data = _get_data(appid)
    if data:
        return {
            'type': data.get('type', ''),
            'name': data.get('name', ''),
            'dlcs': data.get('dlc', []),
        }
    return None
