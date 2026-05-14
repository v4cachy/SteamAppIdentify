# SteamAppIdentify

Let's be real — I made this because I pirate games. Every time I download a Steam manifest dump, I'd end up with a bunch of files named `1245620.zip` or app manifest files with just numbers, and I'd have to look up each AppID, rename them one by one, and figure out whether the DLCs were even in there. That got old fast.

So I built **SteamAppIdentify** — it drops a game zip (`.lua` + `.manifest`), `appmanifest_*.acf`, or any file with an AppID in its name, looks up the names on Steam automatically, and:

- **Audit mode** — parses `.lua` files inside zips, cross-references every DLC against Steam, and shows you exactly which depots have manifests and which are missing
- **Rename mode** — batch renames everything from numeric junk to actual game names (`1245620.zip` → `Elden Ring.zip`)

No more manual renaming. No more second-guessing if the DLCs are complete.

## Download

Grab the latest binary from [Releases](https://github.com/v4cachy/SteamAppIdentify/releases):

| Platform | File | How to run |
|----------|------|-----------|
| **Windows** | `SteamAppIdentify.exe` | Double-click |
| **Linux** | `SteamAppIdentify` | `chmod +x` then double-click or `./SteamAppIdentify` |

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
