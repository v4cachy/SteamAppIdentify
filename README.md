# SteamManfiesto

Identify and rename Steam files using their AppID. Drop files with a Steam AppID in their name (e.g. `2407270.zip`, `appmanifest_220.acf`) — the tool looks up the game name on Steam and renames the file for you.

## Install

**Normal users** — download the binary from [Releases](https://github.com/v4cachy/SteamManfiesto/releases):

```bash
chmod +x SteamManfiesto
./SteamManfiesto
```

**Developers** — run from source:

```bash
pip install -r requirements.txt
python3 main.py
```

## Build

```bash
bash scripts/build.sh
# Output: dist/SteamManfiesto
```

## Usage

1. Launch the app
2. Drag & drop files onto the window (or click to browse)
3. Wait for Steam to look up each game name
4. Click **Rename All**
