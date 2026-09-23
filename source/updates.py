"""GitHub Releases updater: bounded downloads, SHA-256 and publisher verification.

No token is embedded: the update feed is a public GitHub repository. Unsigned
development releases can be downloaded, but never launched automatically.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from appmeta import VERSION, UPDATE_REPOSITORY

MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_METADATA = 2 * 1024 * 1024
ALLOWED_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                 "objects.githubusercontent.com"}


class UpdateError(Exception):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise UpdateError("The release version is not a supported stable version.")
    return tuple(map(int, value.lstrip("v").split(".")))


def safe_url(url):
    p = urlparse(url)
    if (p.scheme != "https" or p.hostname not in ALLOWED_HOSTS or p.username or p.password
            or p.port not in (None, 443)):
        raise UpdateError("The update download has an unexpected destination.")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    request = Request(safe_url(url), headers={"Accept": "application/vnd.github+json",
        "User-Agent": "TitleVisionAssistant/" + VERSION, "X-GitHub-Api-Version": "2022-11-28"})
    try:
        return build_opener(SafeRedirect()).open(request, timeout=25)
    except HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No published release was found. The repository must be public and have a published release.") from exc
        if exc.code in (403, 429):
            raise UpdateError("GitHub has temporarily limited update checks. Try again later.") from exc
        raise UpdateError("GitHub could not serve this update. Try again later.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Could not connect to GitHub. Check your connection and try again.") from exc


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    download_url: str
    filename: str
    size: int
    sha256: str


def parse_release(data, current=VERSION, repository=UPDATE_REPOSITORY):
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise UpdateError("Only published stable releases are supported.")
    tag = data.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.lstrip("v")
    page_url = f"https://github.com/{repository}/releases/tag/{tag}"
    filename = f"TitleVisionAssistant-Setup-{version}.exe"
    assets = [a for a in data.get("assets", []) if isinstance(a, dict) and a.get("name") == filename]
    if len(assets) != 1:
        raise UpdateError("This release does not contain exactly one compatible Windows installer.")
    asset = assets[0]
    expected_url = f"https://github.com/{repository}/releases/download/{tag}/{filename}"
    digest = asset.get("digest") or ""
    size = asset.get("size")
    if asset.get("browser_download_url") != expected_url:
        raise UpdateError("The installer is not hosted in the configured GitHub release.")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise UpdateError("GitHub has not supplied the installer's SHA-256 digest. Try again later.")
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD:
        raise UpdateError("The installer size is outside the allowed limit.")
    return Release(version, page_url, expected_url, filename, size, digest[7:].lower())


def check_update(opener=open_url):
    with opener(f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest") as response:
        raw = response.read(MAX_METADATA + 1)
    if len(raw) > MAX_METADATA:
        raise UpdateError("The update response is too large.")
    try:
        return parse_release(json.loads(raw))
    except (ValueError, TypeError, KeyError) as exc:
        raise UpdateError("GitHub returned invalid release information.") from exc


def download_update(release, directory, opener=open_url, progress=lambda n, total: None, cancelled=lambda: False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Release metadata is validated again before using it as a local filename.
    expected = f"TitleVisionAssistant-Setup-{release.version}.exe"
    version_tuple(release.version)
    if release.filename != expected or not re.fullmatch(r"[0-9a-f]{64}", release.sha256):
        raise UpdateError("Invalid installer metadata.")
    if release.download_url != f"https://github.com/{UPDATE_REPOSITORY}/releases/download/v{release.version}/{expected}":
        # Stable tags without the optional v prefix are supported too.
        if release.download_url != f"https://github.com/{UPDATE_REPOSITORY}/releases/download/{release.version}/{expected}":
            raise UpdateError("Unexpected installer URL.")
    if type(release.size) is not int or not 0 < release.size <= MAX_DOWNLOAD:
        raise UpdateError("Invalid installer size.")
    fd, partial = tempfile.mkstemp(prefix="download-", suffix=".part", dir=directory)
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as output, opener(release.download_url) as response:
            while True:
                if cancelled():
                    raise UpdateError("Update download cancelled. Your installed app was not changed.")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > release.size:
                    raise UpdateError("The download exceeded its declared size.")
                output.write(chunk)
                digest.update(chunk)
                progress(size, release.size)
        if size != release.size or digest.hexdigest() != release.sha256:
            raise UpdateError("The installer failed its integrity check. Nothing was installed.")
        destination = directory / release.filename
        os.replace(partial, destination)
        return destination
    finally:
        Path(partial).unlink(missing_ok=True)


def signature(path):
    """Read Windows trust status. File path travels via environment, not shell code."""
    if sys.platform != "win32":
        return {}
    ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = "$s=Get-AuthenticodeSignature -LiteralPath $env:TV_SIGNATURE_PATH; @{status=[string]$s.Status; thumbprint=[string]$s.SignerCertificate.Thumbprint} | ConvertTo-Json -Compress"
    try:
        result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "TV_SIGNATURE_PATH": str(Path(path).resolve())},
            capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def trusted_installer(path, release, installed=None, signature_reader=signature):
    path = Path(path)
    if path.stat().st_size != release.size or hashlib.sha256(path.read_bytes()).hexdigest() != release.sha256:
        raise UpdateError("The downloaded installer changed. Download it again.")
    if installed is None:
        if not getattr(sys, "frozen", False):
            return False
        installed = sys.executable
    current, incoming = signature_reader(installed), signature_reader(path)
    return (current.get("status") == incoming.get("status") == "Valid"
            and bool(current.get("thumbprint"))
            and current["thumbprint"] == incoming.get("thumbprint"))


def launch_installer(path, release):
    if not trusted_installer(path, release):
        raise UpdateError("Automatic installation requires a valid signature from the same publisher as this app.")
    # Interactive installer: no elevation, silent flags, or forced termination.
    subprocess.Popen([str(Path(path).resolve())], close_fds=True)
