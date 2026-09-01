"""
Deterministic fixture assets for the Universal Tool Updater test battery.

This module builds every synthetic archive/page used by fixture_server.py
and by run_pipeline.ps1's scratch-directory seeding step. It is
intentionally dependency-light: only the stdlib plus libraries already
required by src/requirements.txt (py7zr) are used - no new pip dependency
is introduced for the test harness.

It also doubles as a tiny CLI so run_pipeline.ps1 (PowerShell) can reach
into it without needing its own zip/7z-writing code:

    python fixtures.py seed-merge <dest_7z_path>
    python fixtures.py has-rar
"""

import io
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

import py7zr

# Fixed local port the fixture HTTP server binds to. Kept as a constant
# (rather than dynamically chosen) because tools.ini is a static file and
# UpdateManager.py has no way to receive a discovered port at runtime.
FIXTURE_PORT = 18971
FIXTURE_HOST = "127.0.0.1"
FIXTURE_BASE_URL = f"http://{FIXTURE_HOST}:{FIXTURE_PORT}"

# Version/password constants shared between the server, tools.ini and
# run_pipeline.ps1's assertions.
MERGE_OLD_VERSION = "1.0.0"
MERGE_NEW_VERSION = "2.0.0"
PASSWORD_PROTECTED_PASSWORD = "fixturepw"
RAR_VERSION = "9.9.9"


# ---------------------------------------------------------------------------
# Low level archive builders
# ---------------------------------------------------------------------------

def zip_bytes(entries: dict) -> bytes:
    """Build an in-memory ZIP file from {name: bytes} entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def sevenzip_bytes(entries: dict, password: str = None) -> bytes:
    """Build an in-memory 7z archive from {name: bytes} entries.

    py7zr can only write from real files on disk, so this stages the
    entries in a temp directory first.
    """
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        out_path = tdp / "out.7z"
        with py7zr.SevenZipFile(out_path, "w", password=password) as archive:
            if password:
                archive.set_encrypted_header(True)
            for name, data in entries.items():
                src = tdp / "stage" / name
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(data)
                archive.write(src, name)
        return out_path.read_bytes()


def find_rar_exe():
    """Locate a real Rar.exe (WinRAR, archive-creation capable) on this
    machine, if any. Returns the path, or None. Used to decide whether the
    RAR fixture/scenario can be exercised for real, or must be skipped."""
    candidates = [
        r"C:\Program Files\WinRAR\Rar.exe",
        r"C:\Program Files (x86)\WinRAR\Rar.exe",
    ]
    for candidate in candidates:
        if pathlib.Path(candidate).exists():
            return candidate

    for name in ("Rar.exe", "rar.exe", "rar"):
        found = shutil.which(name)
        if found:
            return found

    return None


def rar_bytes(entries: dict, rar_exe: str) -> bytes:
    """Build a real RAR archive using a real Rar.exe (WinRAR) install.
    Raises if rar_exe is falsy/invalid - callers should gate on
    find_rar_exe() first."""
    if not rar_exe:
        raise RuntimeError("no rar.exe available")

    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        names = []
        for name, data in entries.items():
            p = tdp / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            names.append(name)

        archive_path = tdp / "out.rar"
        subprocess.run(
            [rar_exe, "a", "-ep1", "-inul", str(archive_path), *names],
            cwd=str(tdp),
            check=True,
            capture_output=True,
        )
        return archive_path.read_bytes()


# ---------------------------------------------------------------------------
# Named fixture assets
# ---------------------------------------------------------------------------

def basic_zip_bytes() -> bytes:
    """Payload for the plain from=web smoke tool. Two entries so the
    "single wrapping folder" flatten logic in FileManager does NOT engage,
    keeping the resulting archive layout simple to assert on."""
    return zip_bytes({
        "readme.txt": b"FixtureWeb readme payload\n",
        "bin/tool.exe": b"not a real PE, just fixture bytes\n",
    })


def nested_outer_zip_bytes() -> bytes:
    """Outer zip containing exactly one entry (inner.zip), which is itself
    a zip. Exercises Packer.unpack_nested (zip-inside-zip)."""
    inner = zip_bytes({
        "data.txt": b"nested payload data\n",
        "notes/readme.txt": b"nested payload notes\n",
    })
    return zip_bytes({"inner.zip": inner})


def misreported_zip_bytes() -> bytes:
    """A perfectly valid zip; the HTTP route serving it lies about its
    Content-Type (text/html) to exercise the content-type rejection check
    and its disable_content_type_check escape hatch."""
    return zip_bytes({
        "content.txt": b"this is a real zip served with a fake Content-Type\n",
    })


def merge_new_zip_bytes() -> bytes:
    """"New version" payload for the merge=True regression test."""
    return zip_bytes({"new_marker.txt": b"new version payload\n"})


def merge_old_7z_bytes() -> bytes:
    """"Old version" archive, seeded directly into the tool's install
    folder (not served over HTTP) before the very first run, matching the
    filename Packer.repack_save_compress_name would have produced for it:
    "FixtureMerge - 1.0.0.7z"."""
    return sevenzip_bytes({"old_marker.txt": b"old version payload\n"})


def password_protected_7z_bytes() -> bytes:
    """A real AES-encrypted 7z archive, built with py7zr (already a
    project dependency) - no pyminizip / new dependency required."""
    return sevenzip_bytes(
        {"secret.txt": b"top secret payload only readable with the password\n"},
        password=PASSWORD_PROTECTED_PASSWORD,
    )


def tricky_disposition_zip_bytes() -> bytes:
    """Reuses the basic payload; what matters for this fixture is the
    Content-Disposition header the server sends alongside it, not the
    body."""
    return basic_zip_bytes()


def rar_fixture_bytes(rar_exe: str) -> bytes:
    return rar_bytes({"rar_marker.txt": b"hello from a real rar archive\n"}, rar_exe)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_seed_merge(dest: str):
    dest_path = pathlib.Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(merge_old_7z_bytes())
    print(f"seeded {dest_path}")


def _cmd_has_rar():
    exe = find_rar_exe()
    if exe:
        print(f"yes {exe}")
        return 0
    print("no")
    return 1


def main(argv):
    if len(argv) < 2:
        print("usage: fixtures.py <seed-merge DEST | has-rar>", file=sys.stderr)
        return 2

    cmd = argv[1]
    if cmd == "seed-merge":
        if len(argv) < 3:
            print("usage: fixtures.py seed-merge DEST", file=sys.stderr)
            return 2
        _cmd_seed_merge(argv[2])
        return 0
    elif cmd == "has-rar":
        return _cmd_has_rar()

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
