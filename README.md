# AppIDentify

Audit Steam appmanifest files to verify DLC completeness. Drop a zip or `appmanifest_*.acf` files — the tool looks up each game on Steam and reports which DLCs have manifests and which are missing.

## Download

Grab the latest binary from [Releases](https://github.com/v4cachy/AppIDentify/releases):

| Platform | File | How to run |
|----------|------|-----------|
| **Windows** | `AppIDentify.exe` | Double-click |
| **Linux** | `AppIDentify` | `chmod +x` then double-click or `./AppIDentify` |

## Usage

1. Launch the app
2. Drag & drop a `.zip` or `appmanifest_*.acf` files onto the window (or click to browse)
3. Click **Check DLCs** to query Steam
4. Review the table — missing DLCs are shown in red

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
