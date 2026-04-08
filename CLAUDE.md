# Universal Tool Updater

Windows utility that keeps a collection of tools automatically up-to-date by scraping versions from multiple sources and downloading/installing updates.

## Tech Stack

- Python 3, compiled to EXE with PyInstaller
- Key deps: `requests`, `colorama`, `pypdl`, `py7zr`, `rarfile`, `psutil`

## Project Structure

```
src/
├── UpdateManager.py                 # Entry point: CLI args, mutex, logging, parallel orchestration
└── universal_updater/
    ├── Updater.py                   # Core orchestrator per tool: scrape → download → unpack → install
    ├── ConfigManager.py             # Thread-safe tools.ini parser (configparser)
    ├── Scraper.py                   # Version/URL detection: web, github, http, scoop strategies
    ├── Downloader.py                # Multi-segment downloads (pypdl), Content-Type validation
    ├── Packer.py                    # Unpack ZIP/RAR/7z, repack to 7z, merge support
    ├── FileManager.py               # Tool install paths, folder cleanup, file copy
    ├── ScriptExecutor.py            # Pre/post update script execution
    ├── Helpers.py                   # Static utils: folder ops, URL parsing
    └── ColoredFormatter.py          # Colored log output
tools.ini                           # Tool definitions (one [section] per tool)
```

## Data Flow

```
UpdateManager → ThreadPoolExecutor → Updater.update(tool_name)
  1. ConfigManager.get_tool_config() → dict with all tool settings
  2. Scraper.scrape_step() → {download_version, download_url}
  3. Downloader.download_from_web() → file path
  4. Packer.unpack_step() → unpacked folder
  5. FileManager.save() or Packer.repack_step() → install to tool folder
  6. ConfigManager.update_local_version()
```

## Config (tools.ini)

Each tool is a section with key-value pairs. Main fields:
- `folder` (required), `url` (required), `from` (web|github|http|scoop)
- `re_version`, `re_download`, `update_url` - scraping config
- `local_version` - auto-updated after each successful run
- Per-tool flags: `disable_repack`, `disable_content_type_check`, `merge`, `update_file_pass`
- Scripts: `pre_update`, `post_update`, `post_unpack`
- Architecture overrides: `re_download_x64/x86`, `update_url_x64/x86`

## Conventions

- Classes: PascalCase, Methods: snake_case, Constants: UPPER_CASE
- CLI args parsed in UpdateManager via argparse, passed as `updater_setup` dict
- Per-tool config flags read via `self.tool_config.get('flag_name', default)`
- Errors use `colorama.Fore.RED/YELLOW` + raise Exception
- Thread safety via `threading.Lock()` in ConfigManager
- No test framework; use `--dry-run` for safe testing

## Build

```bash
cd src
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile UpdateManager.py --icon=../assets/appicon.ico --collect-all aiohttp --collect-all aiofiles
```
