import re


def parse_appmanifest(content):
    appid = None
    name = None
    for line in content.splitlines():
        line = line.strip()
        m = re.match(r'^"appid"\s+"(\d+)"', line)
        if m:
            appid = m.group(1)
        m = re.match(r'^"name"\s+"(.+)"', line)
        if m:
            name = m.group(1)
        if appid and name:
            break
    return appid, name
