import os
import zipfile


def is_zip(path):
    return path.lower().endswith('.zip')


def list_contents(zip_path):
    lua_files = []
    manifest_files = []
    acf_files = []
    other = []

    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            basename = os.path.basename(name)
            if basename.endswith('.lua'):
                content = z.read(name).decode('utf-8', errors='replace')
                lua_files.append({'filename': basename, 'content': content})
            elif basename.endswith('.manifest'):
                manifest_files.append(basename)
            elif basename.startswith('appmanifest_') and basename.endswith('.acf'):
                content = z.read(name).decode('utf-8', errors='replace')
                acf_files.append({'filename': basename, 'content': content})
            else:
                other.append(basename)

    return lua_files, manifest_files, acf_files, other
