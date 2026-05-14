def generate_lua(appid, name, depots=None):
    safe_name = name.replace('\\', '\\\\').replace('"', '\\"')
    depots = depots or {}

    lines = [
        'return {',
        f'    appid = {appid},',
        f'    name = "{safe_name}",',
    ]

    if depots:
        lines.append('    depots = {')
        for depot_id, manifest_id in depots.items():
            lines.append(f'        [{depot_id}] = "{manifest_id}",')
        lines.append('    },')

    lines.append('}')
    return '\n'.join(lines) + '\n'
