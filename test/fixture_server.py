"""
Stdlib-only local HTTP fixture server for the Universal Tool Updater test
battery.

Serves deterministic synthetic content on 127.0.0.1:FIXTURE_PORT:
  - fake versioned "release" HTML pages, for from=web regex scraping
  - small generated .zip / .7z / (optionally) .rar downloads
  - a nested zip-inside-zip (Packer.unpack_nested)
  - a route that lies about its Content-Type (content-type rejection check)
  - a route with a deliberately tricky Content-Disposition header
    (filename= AND filename*=, plus a path-traversal attempt)

No third-party dependencies: only http.server / socketserver from the
stdlib. Range requests (single range) are supported so pypdl's
multi-segment downloader behaves realistically against it.

Usage:
    python fixture_server.py [--rar-exe PATH]

Prints "FIXTURE SERVER READY" once listening, then serves until killed.
"""

import argparse
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import fixtures


class Asset:
    __slots__ = ("content_type", "disposition", "body", "extra_headers", "delay")

    def __init__(self, content_type, body, disposition=None, extra_headers=None, delay=0):
        self.content_type = content_type
        self.body = body
        self.disposition = disposition
        self.extra_headers = extra_headers or {}
        self.delay = delay


def _html(body: str) -> bytes:
    return body.encode("utf-8")


def build_assets(rar_exe):
    """Build the full {path: Asset} registry served by this process."""
    assets = {}

    assets["/health"] = Asset("text/plain", b"OK")

    # ---- from=web smoke: basic zip -----------------------------------
    assets["/release/basic.html"] = Asset("text/html", _html(
        "<html><body><h1>FixtureWeb</h1>"
        "<p>FixtureWeb version 1.4.2</p>"
        '<a href="download/basic-v1.4.2.zip">Download</a>'
        "</body></html>"
    ))
    assets["/download/basic-v1.4.2.zip"] = Asset(
        "application/zip", fixtures.basic_zip_bytes(),
        disposition='attachment; filename="basic-v1.4.2.zip"',
    )

    # ---- zip-inside-zip (Packer.unpack_nested) ------------------------
    assets["/release/nested.html"] = Asset("text/html", _html(
        "<html><body><h1>FixtureNested</h1>"
        "<p>FixtureNested version 3.0.0</p>"
        '<a href="download/nested-v3.0.0.zip">Download</a>'
        "</body></html>"
    ))
    assets["/download/nested-v3.0.0.zip"] = Asset(
        "application/zip", fixtures.nested_outer_zip_bytes(),
        disposition='attachment; filename="nested-v3.0.0.zip"',
    )

    # ---- content-type rejection / disable_content_type_check ----------
    assets["/release/misreport.html"] = Asset("text/html", _html(
        "<html><body><h1>FixtureMisreport</h1>"
        "<p>FixtureMisreport version 1.0.0</p>"
        '<a href="download/misreported-v1.0.0.zip">Download</a>'
        "</body></html>"
    ))
    # Real zip bytes, but the server lies about the Content-Type header,
    # simulating a misconfigured host serving binaries as text/html.
    assets["/download/misreported-v1.0.0.zip"] = Asset(
        "text/html", fixtures.misreported_zip_bytes(),
        disposition='attachment; filename="misreported-v1.0.0.zip"',
    )

    # ---- merge=True: "new version" content -----------------------------
    assets["/release/merge.html"] = Asset("text/html", _html(
        "<html><body><h1>FixtureMerge</h1>"
        f"<p>FixtureMerge version {fixtures.MERGE_NEW_VERSION}</p>"
        f'<a href="download/merge-v{fixtures.MERGE_NEW_VERSION}.zip">Download</a>'
        "</body></html>"
    ))
    assets[f"/download/merge-v{fixtures.MERGE_NEW_VERSION}.zip"] = Asset(
        "application/zip", fixtures.merge_new_zip_bytes(),
        disposition=f'attachment; filename="merge-v{fixtures.MERGE_NEW_VERSION}.zip"',
    )

    # ---- update_file_pass: password-protected 7z -----------------------
    assets["/release/passwordzip.html"] = Asset("text/html", _html(
        "<html><body><h1>FixturePasswordProtected</h1>"
        "<p>FixturePasswordProtected version 5.5.5</p>"
        '<a href="download/protected-v5.5.5.7z">Download</a>'
        "</body></html>"
    ))
    assets["/download/protected-v5.5.5.7z"] = Asset(
        "application/x-7z-compressed", fixtures.password_protected_7z_bytes(),
        disposition='attachment; filename="protected-v5.5.5.7z"',
    )

    # ---- tricky Content-Disposition (filename= + filename*=, traversal) -
    assets["/download/tricky"] = Asset(
        "application/octet-stream", fixtures.tricky_disposition_zip_bytes(),
        disposition=(
            'attachment; filename="../../evil.zip"; '
            "filename*=UTF-8''good-name.zip"
        ),
    )

    # ---- shutdown/Ctrl+C scenario: slow-responding release pages --------
    # A plain GET on the release page sleeps before responding, giving the
    # shutdown scenario a deterministic window to send CTRL_C_EVENT while a
    # tool's scrape is still in flight (no reliance on real network timing).
    for n in (1, 2, 3):
        assets[f"/release/slow{n}.html"] = Asset(
            "text/html",
            _html(
                f"<html><body><h1>FixtureSlow{n}</h1>"
                f"<p>FixtureSlow{n} version 1.0.0</p>"
                f'<a href="download/slow{n}-v1.0.0.zip">Download</a>'
                "</body></html>"
            ),
            delay=fixtures.SLOW_ROUTE_DELAY_SECONDS,
        )
        assets[f"/download/slow{n}-v1.0.0.zip"] = Asset(
            "application/zip", fixtures.basic_zip_bytes(),
            disposition=f'attachment; filename="slow{n}-v1.0.0.zip"',
        )

    # ---- RAR fixture (only registered if a real Rar.exe is available) --
    assets["/release/rarfixture.html"] = Asset("text/html", _html(
        "<html><body><h1>FixtureRar</h1>"
        f"<p>FixtureRar version {fixtures.RAR_VERSION}</p>"
        f'<a href="download/rarfixture-v{fixtures.RAR_VERSION}.rar">Download</a>'
        "</body></html>"
    ))
    if rar_exe:
        assets[f"/download/rarfixture-v{fixtures.RAR_VERSION}.rar"] = Asset(
            "application/x-rar-compressed", fixtures.rar_fixture_bytes(rar_exe),
            disposition=f'attachment; filename="rarfixture-v{fixtures.RAR_VERSION}.rar"',
        )

    return assets


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        sys.stdout.write("[fixture-server] " + (format % args) + "\n")
        sys.stdout.flush()

    def _asset(self):
        path = urlsplit(self.path).path
        return self.server.assets.get(path)

    def _send_common_headers(self, asset, length, extra=None):
        self.send_header("Content-Type", asset.content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if asset.disposition:
            self.send_header("Content-Disposition", asset.disposition)
        for key, value in asset.extra_headers.items():
            self.send_header(key, value)
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()

    def do_HEAD(self):
        asset = self._asset()
        if asset is None:
            self.send_error(404, "Not Found")
            return
        self.send_response(200)
        self._send_common_headers(asset, len(asset.body))

    def do_GET(self):
        asset = self._asset()
        if asset is None:
            self.send_error(404, "Not Found")
            return

        if asset.delay:
            time.sleep(asset.delay)

        body = asset.body
        total = len(body)
        range_header = self.headers.get("Range")

        if range_header and range_header.startswith("bytes="):
            try:
                spec = range_header.split("=", 1)[1]
                start_s, end_s = spec.split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else total - 1
                end = min(end, total - 1)
                if start > end or start >= total:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total}")
                    self.end_headers()
                    return

                chunk = body[start:end + 1]
                self.send_response(206)
                self._send_common_headers(
                    asset, len(chunk),
                    extra={"Content-Range": f"bytes {start}-{end}/{total}"},
                )
                self.wfile.write(chunk)
                return
            except (ValueError, IndexError):
                pass  # fall through to a full 200 response

        self.send_response(200)
        self._send_common_headers(asset, total)
        self.wfile.write(body)


def serve(rar_exe=None, ready_event=None):
    assets = build_assets(rar_exe)
    server = ThreadingHTTPServer((fixtures.FIXTURE_HOST, fixtures.FIXTURE_PORT), FixtureHandler)
    server.assets = assets
    print(f"FIXTURE SERVER READY on {fixtures.FIXTURE_BASE_URL} "
          f"({len(assets)} routes, rar={'yes' if rar_exe else 'no'})")
    sys.stdout.flush()
    if ready_event is not None:
        ready_event.set()
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rar-exe", default=None, help="Path to a real Rar.exe to build the RAR fixture with")
    parser.add_argument("--auto-detect-rar", action="store_true", help="Auto-detect Rar.exe if --rar-exe not given")
    args = parser.parse_args()

    rar_exe = args.rar_exe
    if not rar_exe and args.auto_detect_rar:
        rar_exe = fixtures.find_rar_exe()

    serve(rar_exe=rar_exe)


if __name__ == "__main__":
    main()
