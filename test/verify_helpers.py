"""
Small on-demand helpers used by run_pipeline.ps1 to inspect archive
contents during assertions ("extract and check the files are there").

Reuses only libraries already required by src/requirements.txt (py7zr,
rarfile) plus the stdlib (zipfile) - no new dependency is introduced for
the test harness itself.
"""

import configparser
import pathlib
import sys
import zipfile

import py7zr


def extract(archive_path: str, dest_dir: str, password: str = None):
    archive_path = pathlib.Path(archive_path)
    dest_dir = pathlib.Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = archive_path.suffix.lower()
    if suffix == ".7z":
        with py7zr.SevenZipFile(archive_path, "r", password=password) as archive:
            archive.extractall(dest_dir)
    elif suffix == ".zip":
        pwd = password.encode() if password else None
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(dest_dir, pwd=pwd)
    elif suffix == ".rar":
        import rarfile
        with rarfile.RarFile(archive_path, "r") as archive:
            archive.extractall(dest_dir, pwd=password)
    else:
        raise SystemExit(f"unsupported archive type: {suffix}")


def get_config(ini_path: str, section: str, key: str):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ini_path)
    return parser.get(section, key, fallback=None)


def main(argv):
    if len(argv) < 2:
        print("usage: verify_helpers.py <extract|get-config> ...", file=sys.stderr)
        return 2

    cmd = argv[1]
    if cmd == "extract":
        if len(argv) < 4:
            print("usage: verify_helpers.py extract <archive> <destdir> [password]", file=sys.stderr)
            return 2
        password = argv[4] if len(argv) > 4 else None
        extract(argv[2], argv[3], password)
        print("OK")
        return 0

    if cmd == "get-config":
        if len(argv) < 5:
            print("usage: verify_helpers.py get-config <ini> <section> <key>", file=sys.stderr)
            return 2
        value = get_config(argv[2], argv[3], argv[4])
        if value is None:
            print("")
            return 1
        print(value)
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
