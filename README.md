# AppIDentify

Identify and rename Steam files using their AppID. Drop files with a Steam AppID in their name (e.g. `2407270.zip`, `appmanifest_220.acf`) — the tool looks up the game name on Steam and renames the file for you.

## Download

Grab the latest binary from [Releases](https://github.com/v4cachy/AppIDentify/releases):

| Platform | File | How to run |
|----------|------|-----------|
| **Windows** | `AppIDentify.exe` | Double-click |
| **Linux** | `AppIDentify` | `chmod +x` then double-click or `./AppIDentify` |

## Usage

1. Launch the app
2. Drag & drop files onto the window (or click to browse)
3. Wait for Steam to look up each game name
4. Click **Rename All**

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
