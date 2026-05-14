import os
import zipfile


def is_zip(path):
    return path.lower().endswith('.zip')


def list_manifests_in_zip(zip_path):
    results = []
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            basename = os.path.basename(name)
            if basename.startswith('appmanifest_') and basename.endswith('.acf'):
                content = z.read(name).decode('utf-8', errors='replace')
                results.append({'filename': basename, 'content': content, 'path_in_zip': name})
    return results


def list_all_files(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as z:
        return [os.path.basename(n) for n in z.namelist()]
