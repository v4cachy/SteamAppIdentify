import json
import urllib.error
import urllib.request

_TIMEOUT = 10
_HEADERS = {'User-Agent': 'SteamManfiesto/1.0'}
_details_cache = {}

_SEARCH_URL = 'https://store.steampowered.com/api/storesearch?term={}&l=en&cc=US'
_LUA_DETAILS_URL = 'https://lua.tools/api/steam/details?appid={}'
_STEAM_DETAILS_URL = 'https://store.steampowered.com/api/appdetails?appids={}'


def search_games(query):
    if not query or len(query.strip()) < 2:
        return []
    url = _SEARCH_URL.format(urllib.request.quote(query.strip()))
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
            return data.get('items', [])
    except Exception:
        return []


def fetch_game_details(appid):
    if appid in _details_cache:
        return _details_cache[appid]

    # Try lua.tools API first
    try:
        url = _LUA_DETAILS_URL.format(appid)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
            if data.get('name'):
                _details_cache[appid] = data
                return data
    except Exception:
        pass

    # Fallback to Steam Storefront API
    try:
        url = _STEAM_DETAILS_URL.format(appid)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
            entry = data.get(str(appid))
            if entry and entry.get('success'):
                d = entry['data']
                result = {
                    'name': d.get('name', ''),
                    'appid': appid,
                    'type': d.get('type', ''),
                    'genres': [g['description'] for g in d.get('genres', [])],
                    'headerImage': d.get('header_image', ''),
                    'releaseDate': d.get('release_date', {}).get('date', ''),
                }
                _details_cache[appid] = result
                return result
    except Exception:
        pass

    return None


def fetch_game_name(appid):
    details = fetch_game_details(appid)
    return details['name'] if details else None
