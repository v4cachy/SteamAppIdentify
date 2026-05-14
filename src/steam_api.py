import json
import urllib.error
import urllib.request

_cache = {}
_TIMEOUT = 10


def fetch_game_name(appid):
    if appid in _cache:
        return _cache[appid]
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'SteamManfiesto/1.0'})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
            entry = data.get(str(appid))
            if entry and entry.get('success'):
                name = entry['data']['name']
                _cache[appid] = name
                return name
    except urllib.error.HTTPError as e:
        raise ConnectionError(f"HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"Network error: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid response: {e}") from e
    return None
