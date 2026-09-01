# Test battery

This is a **functional/smoke test battery**, not a unit test suite. There is
no pytest, no unittest, and nothing here imports `universal_updater` code
directly. Instead it drives the real `src/UpdateManager.py` exactly the way
the maintainer already does: a `tools.ini` plus CLI flags, run from a
working directory, and asserts on real end-to-end outcomes - files on disk,
exit codes, and log output.

It is modeled on the two things that already validate this tool today: the
repo's own root `tools.ini`, and the real deployment at
`toolkit/bin/updater/tools.ini` (+ its `scripts\*.bat` hooks). This battery
does not modify either of those.

## Running it

```powershell
.\test\run_pipeline.ps1
```

from the repo root (or `pwsh -File test\run_pipeline.ps1` from anywhere).
It is self-contained: no arguments, no pip installs beyond what
`src/requirements.txt` already lists. It takes about a minute, most of
which is real network I/O in scenario 3.

What it does, at a high level:

1. Builds a clean scratch working directory at `test/.run/` containing a
   **copy** of `src/UpdateManager.py`, `src/universal_updater/`,
   `src/pypdl_extend/`, this directory's `tools.ini` and `scripts/`, and
   `unrar.exe` from the repo root.
2. Starts `test/fixture_server.py`, a stdlib-only local HTTP server on
   `127.0.0.1:18971`, serving deterministic synthetic content.
3. Seeds an "old version" `.7z` into the `FixtureMerge` tool's folder so the
   `merge=True` path is forced to fire on its very first real run.
4. Runs the real `UpdateManager.py` several times with different flag
   combinations (see below), asserting concrete outcomes after each run.
5. Prints a `PASS`/`FAIL` line per assertion, a final summary, and exits
   non-zero if anything failed. The fixture server is always stopped
   before exiting. The scratch dir is wiped at the *start* of each
   invocation (so every run starts fresh) but is deliberately **left in
   place** if a run fails, for inspection - look under `test/.run/tools/`
   for install folders and `test/.run/logs/` for full stdout/stderr per
   scenario plus the fixture server's own log.

### Why the source tree gets copied into the scratch dir

`UpdateManager.py` hardcodes `tools.ini` relative to the current working
directory, and there is no `--config` flag - so isolation has to come from
running the real script with a scratch CWD. That alone isn't quite enough,
though: `UpdateManager.change_current_directory()` does
`os.chdir(os.path.dirname(sys.argv[0]))` (to make relative paths work in a
PyInstaller onefile build). If you launched it as
`python I:\...\src\UpdateManager.py` from inside the scratch dir, that
`chdir` would immediately move the process **out of** the scratch dir and
back into the real `src\` folder, defeating the isolation entirely.

The fix `run_pipeline.ps1` uses: copy `UpdateManager.py` (+ its two local
packages) into the scratch dir itself, then invoke it as a **bare**
filename (`python UpdateManager.py`, no path prefix) with the scratch dir
already set as the working directory. `os.path.dirname("UpdateManager.py")`
is `""`, which is falsy, so the `chdir` becomes a no-op and the scratch dir
stays authoritative for `tools.ini`, `mutex.lock`, `updates\`, and every
tool's install folder.

## Scenarios

| # | Flags | Covers |
|---|-------|--------|
| 1 | `--dry-run` (all tools) | Fast smoke pass: scraping only, no downloads, for every `from=` type at once (web/github/http/scoop, local fixtures + real internet). Asserts `updates\` and tool folders are never created, and that `pre_update` hooks fire even in dry-run while `post_update`/`post_unpack`/`global_post_update` do not (they're downstream of the dry-run early return). |
| 2 | `-u <fixture tools>` (default flags) | The deterministic core: from=web relative-link resolution, zip-in-zip (`Packer.unpack_nested`), the Content-Type rejection check and its `disable_content_type_check` escape hatch, the tricky `Content-Disposition` (`filename=` + `filename*=` + `../../evil.zip` traversal) regression, `merge=True` forced on a first run, `update_file_pass` against a real encrypted 7z, the per-tool `disable_repack` override, a real `.rar` archive (if a real Rar.exe was found - see below), and all five hook scripts (`.bat`/`.ps1`, bare `.ps1` path, multi-word command string, `global_post_update`). |
| 3 | `-u Portmon malunpack OUI` (default flags) | **Requires network.** A real `from=web` (Portmon/sysinternals), a real `from=github` with `re_download_x64`/`re_download_x86` arch overrides (malunpack), and a real `from=http` (OUI, IEEE OUI list) - full download + unpack + repack against the real internet, copied in spirit from the repo's own root `tools.ini`. |
| 4 | `-u FixtureWeb -f -sft {full,version,name}` × 3 | `save_format_type` variants: `<name> - <version>.7z`, `<version>.7z`, `<name>.7z`. |
| 5 | `-u FixtureWeb FixtureNested -dr -f` | Global `--disable-repack`: raw folder saved instead of a `.7z`, even for tools whose own config doesn't set `disable_repack`. |
| 6 | `-u <6 fixture tools> -pw 4 -f` | `--parallel-workers` concurrency regression: several tools repacking simultaneously, exercising the per-tool temp-dir naming fix so concurrent `repack_step` calls (which all build under the shared `updates\` root) don't collide. |
| 7 | corrupt `mutex.lock`, then `--dry-run` | A `mutex.lock` containing garbage (not a PID) must be treated as stale and regenerated, not crash the run. |
| 8 | `-udp -pw 2 -sft name --dry-run` | `--update-default-params` persistence: asserts `[UpdaterConfig]` in `tools.ini` is rewritten with the new values. |

Scenario 1 also touches `mitmproxy` (`from=scoop`) - dry-run only, see gaps
below.

## Fixture server

`test/fixture_server.py` is stdlib-only (`http.server` /
`socketserver`, no new pip dependency) and serves, on
`http://127.0.0.1:18971`:

- `/release/*.html` - fake versioned release pages for `re_version` /
  `re_download` regex scraping.
- `/download/basic-v1.4.2.zip` - a small real zip.
- `/download/nested-v3.0.0.zip` - a zip containing a single nested zip
  (`inner.zip`), which itself contains the real payload -
  `Packer.unpack_nested`.
- `/download/misreported-v1.0.0.zip` - a **real, valid** zip served with
  `Content-Type: text/html` (a misconfigured-host simulation), for the
  content-type rejection check and its disable flag.
- `/download/tricky` - `Content-Disposition: attachment;
  filename="../../evil.zip"; filename*=UTF-8''good-name.zip` over real zip
  bytes. `email.message.Message.get_filename()` returns the plain
  `filename` parameter (`../../evil.zip`) regardless of the `filename*=`
  variant or its ordering; `Downloader.resolve_filename()` then takes only
  `pathlib.Path(...).name`, which is what actually strips the traversal.
  Confirmed with a standalone interpreter check before wiring this up.
- `/download/protected-v5.5.5.7z` - a real AES-encrypted 7z (see
  `update_file_pass` below).
- `/download/rarfixture-v9.9.9.rar` - a real RAR archive, present only if a
  real `Rar.exe` was found on the machine running the battery.

All download routes support HTTP Range requests (206 Partial Content) so
pypdl's multi-segment downloader behaves realistically against it, not
just a degenerate single-segment fallback.

`test/fixtures.py` is the pure asset-building module behind the server (zip
and 7z builders, RAR-archive builder, Rar.exe auto-detection) and also
serves as a tiny CLI so `run_pipeline.ps1` can seed the merge fixture
without needing its own archive-writing code:
`python fixtures.py seed-merge <dest>` / `python fixtures.py has-rar`.

`test/verify_helpers.py` is the assertion-side counterpart: extracts an
archive (`.zip`/`.7z`/`.rar`, optionally password-protected) or reads a
single `tools.ini` value, so `run_pipeline.ps1` doesn't need its own
archive-reading or ini-parsing code. Both scripts reuse only the stdlib
plus libraries already required by `src/requirements.txt` (`py7zr`,
`rarfile`) - no new dependency is introduced for the harness.

## `update_file_pass`: why a 7z instead of a password-protected zip

The task's starting point was to build the password-protected fixture with
stdlib `zipfile` using `pwd`/`setpassword` - but stdlib `zipfile` can only
**read** an encrypted zip (`pwd=`), it cannot **write** one (no encryption
support on write at all). `pyminizip` could, but it's not a project
dependency and the instructions were to avoid adding one for the harness.

Instead, `FixturePasswordProtected` uses a real AES-encrypted **7z**
archive, built with `py7zr` - already a required dependency
(`src/requirements.txt`) and already exercised by `Packer.unpack_7z`, which
takes the exact same `update_file_pass` value from `tools.ini` and passes
it straight through to `py7zr.SevenZipFile(..., password=...)`. This was
verified directly (write with a password, confirm reading without it
raises `PasswordRequired`, confirm reading with it succeeds) before wiring
it into the battery. It exercises the real code path faithfully without
adding a dependency or reaching for a real third-party password-protected
download (the way `ProcDOT` does in the real `tools.ini`).

## RAR

The task asked to check whether a real `rar.exe`/WinRAR is actually
available before giving up on a RAR fixture. On the machine this battery
was built and run on, `C:\Program Files\WinRAR\Rar.exe` **is** available,
so `fixtures.py` uses it to build a real `.rar` archive
(`fixtures.find_rar_exe()` also checks `Program Files (x86)` and `PATH`).
`FixtureRar` is then included in scenario 2's real run and asserted like
every other fixture tool, exercising `Packer.unpack_rar` /
`rarfile.RarFile` against the `unrar.exe` copied into the scratch dir from
the repo root (matching the README's requirement that `unrar.exe` sit next
to the running script).

If no `Rar.exe`/WinRAR is found on the machine running this battery,
`run_pipeline.ps1` detects that (`fixtures.py has-rar`) and skips the RAR
fixture/tool for the real run, printing `SKIP` instead of failing - the
`[FixtureRar]` section still exists in `tools.ini` and its release page is
still served, so scenario 1's `--dry-run` pass (which never downloads
anything) still smoke-tests its `from=web` scraping either way.

## Honest gaps (untested by this battery, even with network available)

- **GitHub API mode** (`-uga`/`use_github_api`, `Scraper.scrape_github_api`)
  - would need a real personal access token; not exercised. `from=github`
    without the API (scraping the releases page/atom feed) is exercised
    via `malunpack` in scenario 3.
- **Scoop full download** - `mitmproxy` is dry-run only (scrape/manifest
  parsing only); the actual multi-hundred-MB download is skipped on
  purpose to keep this battery small/stable/fast. `force_x86` is not
  exercised either.
- **`-dmc`/`--disable-mutex-check`** - not exercised; every scenario here
  runs with the mutex check on (including the corrupted-`mutex.lock`
  regression in scenario 7).
- **Signal handling** (`SIGINT`/`SIGTERM` graceful exit /
  `exit_handler`/mutex cleanup mid-run) - not exercised; would need to kill
  the process mid-flight in a way that's reliable across environments.
  `-dsu`/self-update (`[UpdaterAutoUpdater]`) is not configured in this
  battery's `tools.ini` either, so `handle_auto_update()`'s branch is
  simply skipped (not present) rather than actively tested - though it
  goes through the exact same `Updater.run()` path already exercised
  by every other tool here.
- **The compiled PyInstaller onefile EXE** - this battery runs
  `python UpdateManager.py` directly (deliberately, see "Why the source
  tree gets copied" above) and does not build/run `updater.exe`. The
  `os.chdir(dirname(sys.argv[0]))` behavior that fix targets is understood
  and worked around, not exercised in its original EXE-argv0 form.
- **A RAR archive protected with `update_file_pass`** - the RAR fixture
  built here is unencrypted; only the zip/7z password paths are tested
  against a real password.
- **Nesting deeper than one level**, or a nested archive of a different
  type than its parent (e.g. a `.rar` inside a `.zip`) - only a
  zip-inside-zip is exercised (`Packer.unpack_nested`).
- Explicit CLI-flag exercise of `-dfc`, `-dic`, `-dpb`, `-rt`, `-dre` -
  these settings ARE exercised throughout the battery (their effects are
  real and asserted on), but via `[UpdaterConfig]` defaults in `tools.ini`
  rather than by passing the corresponding CLI flag on an invocation. The
  code path each flag feeds into (`updater_setup` dict key) is identical
  either way.

## A note on `tools.ini` comments

`configparser` does not preserve comments across a write, and
`UpdateManager` rewrites `tools.ini` (`local_version`, `[UpdaterConfig]`)
after almost every successful tool update. The comments in the source
`test/tools.ini` are documentation for a human reading it before the
battery runs; they will not survive into `test/.run/tools.ini` once the
pipeline starts updating tools. This is expected, not a bug in the
battery.

## Unit tests

`test/unit/` is a second, complementary test layer - a **pure-unit-test
suite** using `pytest`, separate from everything described above. Where
`run_pipeline.ps1` drives the real compiled-equivalent CLI end-to-end
(subprocess, real HTTP server, some real network calls, ~a minute to run),
`test/unit/` imports `universal_updater`/`pypdl_extend`/`UpdateManager` code
directly and calls specific functions/methods in-process: no subprocess, no
HTTP server, no network, no `test/.run/` scratch directory. The whole suite
runs in well under a second.

It targets the specific bug-fix logic from a later code review pass -
things like `ConfigManager`'s atomic-write behavior, `Scraper`'s per-host
cookie scoping, `ScriptExecutor`'s command-line quoting/`.ps1` detection,
`Downloader`'s stale pypdl state cleanup and `Content-Disposition` parsing,
`pypdl_extend.fatal_state`'s per-session isolation, the `Packer.repack_merge`
/ `repack_step` regressions around archives with no single wrapping folder,
`Helpers.cleanup_folder`'s read-only-file handling, and
`UpdateManager.check_single_instance`'s mutex-file parsing - each exercised
directly rather than through a full CLI run. It does not replace
`run_pipeline.ps1`'s end-to-end coverage and does not touch any file used by
it.

### Running it

```powershell
pip install -r test/requirements-test.txt
pytest test/unit -v
```

from the repo root. `test/unit/conftest.py` adds `src/` to `sys.path` so the
tests can `import universal_updater...`/`import pypdl_extend...`/
`import UpdateManager` the same way the real application does.
`test/requirements-test.txt` pins `pytest` as a dev/test-only dependency; it
is intentionally not part of `src/requirements.txt`, which lists only the
shipped runtime dependencies.

One test (`test_downloader.py::test_resolve_filename_raises_on_empty_resolved_filename`)
is marked `xfail`: it documents a real, still-open gap found while writing
this suite - `Downloader.resolve_filename` sanitizes a `Content-Disposition`
filename with `pathlib.Path(filename).name` but never checks the result for
emptiness (e.g. a raw filename of `"/"` or `"."` collapses to `""`), so it
silently returns `""` instead of raising. It's left unfixed here since this
suite is test-only and does not modify `src/`.
