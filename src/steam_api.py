import json
import urllib.error
import urllib.request

_TIMEOUT = 10
_HEADERS = {'User-Agent': 'SteamManfiesto/1.0'}
_cache = {}

_DETAILS_URL = 'https://lua.tools/api/steam/details?appid={}'
_FALLBACK_URL = 'https://store.steampowered.com/api/appdetails?appids={}'


def fetch_game_name(appid):
    if appid in _cache:
        return _cache[appid]

    # Try lua.tools API first
    try:
        url = _DETAILS_URL.format(appid)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
            name = data.get('name')
            if name:
                _cache[appid] = name
                return name
    except Exception:
        pass

    # Fallback to Steam Storefront
    try:
        url = _FALLBACK_URL.format(appid)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
            entry = data.get(str(appid))
            if entry and entry.get('success'):
                name = entry['data']['name']
                _cache[appid] = name
                return name
    except Exception:
        pass

    return None
