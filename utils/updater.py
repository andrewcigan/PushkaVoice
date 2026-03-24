"""Auto-updater: check GitHub Releases for new versions, download and install."""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from utils.version import VERSION, BUILD_NUMBER, GITHUB_REPO

logger = logging.getLogger(__name__)

# Use /releases (not /releases/latest) because all our releases are
# marked as prerelease, and GitHub's /latest endpoint skips prereleases.
# Fetch enough releases to find the highest build number — GitHub sorts
# prereleases lexicographically (beta.9 > beta.26), not numerically.
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=50"
ASSET_NAME = "PushkaVoice-macos-arm64.zip"


def _parse_build_number(tag_name: str) -> int:
    """Extract build number from tag like 'v0.1.0-beta.42'."""
    try:
        # v0.1.0-beta.42 → 42
        if "." in tag_name.split("-")[-1]:
            return int(tag_name.rsplit(".", 1)[-1])
    except (ValueError, IndexError):
        pass
    return 0


def check_for_update() -> dict:
    """Check GitHub Releases for a newer version.

    Returns dict with keys:
        available (bool), tag (str), build (int), current_build (int),
        download_url (str), release_url (str), body (str), error (str|None)
    """
    result = {
        "available": False,
        "tag": "",
        "build": 0,
        "current_build": BUILD_NUMBER,
        "current_version": VERSION,
        "download_url": "",
        "release_url": "",
        "body": "",
        "error": None,
    }

    try:
        req = Request(GITHUB_API, headers={"Accept": "application/vnd.github.v3+json"})
        with urlopen(req, timeout=10) as resp:
            releases = json.loads(resp.read().decode("utf-8"))

        if not releases:
            result["error"] = "No releases found"
            return result

        # GitHub sorts prerelease tags lexicographically, not numerically
        # (beta.9 appears before beta.26).  Find the release with the
        # highest build number ourselves.
        if not isinstance(releases, list):
            releases = [releases]

        best = None
        best_build = 0
        for rel in releases:
            tag = rel.get("tag_name", "")
            build = _parse_build_number(tag)
            if build > best_build:
                best_build = build
                best = rel

        if best is None:
            result["error"] = "No valid releases found"
            return result

        data = best
        tag = data.get("tag_name", "")
        remote_build = best_build
        result["tag"] = tag
        result["build"] = remote_build
        result["release_url"] = data.get("html_url", "")
        result["body"] = data.get("body", "")

        # Find the macOS ZIP asset
        for asset in data.get("assets", []):
            if asset.get("name") == ASSET_NAME:
                result["download_url"] = asset.get("browser_download_url", "")
                break

        # Compare: update available if remote build > current build
        # During dev (BUILD_NUMBER=0), always show update if remote > 0
        if remote_build > BUILD_NUMBER and result["download_url"]:
            result["available"] = True
            logger.info(f"Update available: {tag} (build {remote_build}) > current build {BUILD_NUMBER}")
        else:
            logger.info(f"No update: remote={tag} (build {remote_build}), current build {BUILD_NUMBER}")

    except URLError as e:
        result["error"] = f"Network error: {e.reason}"
        logger.warning(f"Update check failed: {e}")
    except Exception as e:
        result["error"] = str(e)
        logger.warning(f"Update check failed: {e}")

    return result


class Updater:
    """Downloads and installs updates."""

    def __init__(self):
        self._progress = 0  # 0-100
        self._status = ""
        self._error = None
        self._downloading = False
        self._done = False

    @property
    def status(self) -> dict:
        return {
            "progress": self._progress,
            "status": self._status,
            "error": self._error,
            "downloading": self._downloading,
            "done": self._done,
        }

    def download_and_install(self, download_url: str):
        """Download ZIP, extract, and replace current app bundle.

        Must be called in a background thread.
        """
        self._downloading = True
        self._progress = 0
        self._error = None
        self._done = False

        try:
            self._do_update(download_url)
        except Exception as e:
            self._error = str(e)
            logger.error(f"Update failed: {e}", exc_info=True)
        finally:
            self._downloading = False

    def _do_update(self, download_url: str):
        # Step 1: Find current app location
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller bundle: sys.executable is inside .app
            # e.g. /Applications/PushkaVoice.app/Contents/MacOS/PushkaVoice
            app_path = Path(sys.executable).resolve()
            # Walk up to find .app directory
            for parent in app_path.parents:
                if parent.suffix == '.app':
                    app_bundle = parent
                    break
            else:
                raise RuntimeError("Cannot find .app bundle path")
        else:
            raise RuntimeError("Auto-update only works in bundled mode (PyInstaller .app)")

        logger.info(f"Current app bundle: {app_bundle}")
        install_dir = app_bundle.parent  # e.g. /Applications/

        # Step 2: Download ZIP to temp
        self._status = "Downloading update..."
        logger.info(f"Downloading: {download_url}")

        tmp_dir = Path(tempfile.mkdtemp(prefix="pushkavoice_update_"))
        zip_path = tmp_dir / ASSET_NAME

        try:
            req = Request(download_url)
            with urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 256 * 1024  # 256 KB

                with open(zip_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self._progress = int(downloaded * 80 / total)  # 0-80% for download
                        self._status = f"Downloading... {downloaded // (1024*1024)} MB"

            logger.info(f"Downloaded {downloaded} bytes to {zip_path}")

            # Step 3: Extract ZIP
            self._status = "Extracting..."
            self._progress = 85
            extract_dir = tmp_dir / "extracted"
            extract_dir.mkdir()

            # Use ditto on macOS for proper extraction (preserves code signatures)
            result = subprocess.run(
                ["ditto", "-x", "-k", str(zip_path), str(extract_dir)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Extraction failed: {result.stderr}")

            # Find the .app in extracted contents
            new_app = None
            for item in extract_dir.rglob("*.app"):
                if item.is_dir():
                    new_app = item
                    break
            if not new_app:
                raise RuntimeError("No .app found in downloaded archive")

            logger.info(f"Extracted new app: {new_app}")

            # Step 4: Swap app bundles
            self._status = "Installing..."
            self._progress = 90

            backup_path = app_bundle.parent / f"{app_bundle.stem}.backup.app"

            # Remove old backup if exists
            if backup_path.exists():
                shutil.rmtree(backup_path)

            # Move current → backup
            logger.info(f"Backing up: {app_bundle} → {backup_path}")
            shutil.move(str(app_bundle), str(backup_path))

            # Move new → install location
            dest = install_dir / app_bundle.name
            logger.info(f"Installing: {new_app} → {dest}")
            shutil.move(str(new_app), str(dest))

            # Step 5: Remove quarantine attribute (macOS Gatekeeper)
            subprocess.run(
                ["xattr", "-rd", "com.apple.quarantine", str(dest)],
                capture_output=True,
            )

            self._progress = 100
            self._status = "Update installed! Restart the app to use the new version."
            self._done = True
            logger.info("Update installed successfully")

        finally:
            # Clean up temp dir (but not the backup)
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def restart_app():
        """Restart the application by launching the new bundle and quitting.

        Resets Accessibility TCC entries before restart so the new binary
        (which has a different ad-hoc code signature) gets a clean slate.
        """
        if not getattr(sys, 'frozen', False):
            logger.warning("Cannot restart in dev mode")
            return

        app_path = Path(sys.executable).resolve()
        for parent in app_path.parents:
            if parent.suffix == '.app':
                app_bundle = parent
                break
        else:
            logger.error("Cannot find .app bundle for restart")
            return

        # Pre-clear stale TCC entries so the new binary can get fresh permission
        try:
            from utils.accessibility import reset_all_permissions
            logger.info("Resetting all TCC entries before restart...")
            reset_all_permissions()
        except Exception as e:
            logger.warning("TCC reset before restart failed: %s", e)

        logger.info(f"Restarting app: {app_bundle}")
        subprocess.Popen(["open", "-n", str(app_bundle)])
        os._exit(0)
