# AppIDentify

Audit game zip files and rename files by Steam AppID.

Drop a game zip (`.lua` + `.manifest` files), loose `appmanifest_*.acf` files, or regular files with an AppID in their name. The tool looks up game info on Steam and shows:

- **Audit mode** — parses `.lua` files inside zips, lists all game content (base game + DLCs), and shows which depots have manifests and which are missing
- **Rename mode** — renames files to their game name (e.g., `1245620.zip` → `Elden Ring.zip`)

## Download

Grab the latest binary from [Releases](https://github.com/v4cachy/AppIDentify/releases):

| Platform | File | How to run |
|----------|------|-----------|
| **Windows** | `AppIDentify.exe` | Double-click |
| **Linux** | `AppIDentify` | `chmod +x` then double-click or `./AppIDentify` |

## Usage

1. Launch the app
2. Drag & drop a game `.zip`, `appmanifest_*.acf`, or files with AppID
3. The tool parses the contents and looks up names on Steam
4. Review the table — missing manifests shown in red
5. Click **Rename All** to rename the zip/file to the game name

## Build from source

```bash
pip install -r requirements.txt
python3 main.py
```

## Build standalone binary

**Linux:**
```bash
bash scripts/build.sh
```

**Windows** (or cross-platform via GitHub Actions):
Push a tag and the [GitHub Actions workflow](.github/workflows/build.yml) builds both binaries automatically.
