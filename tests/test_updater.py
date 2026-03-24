"""Tests for utils/updater.py."""
import json
from unittest.mock import MagicMock, patch, mock_open

import pytest


class TestParseBuildNumber:
    def test_beta_tag(self):
        from utils.updater import _parse_build_number
        assert _parse_build_number("v0.1.0-beta.42") == 42

    def test_plain_version(self):
        from utils.updater import _parse_build_number
        assert _parse_build_number("v1.0.0") == 0

    def test_empty(self):
        from utils.updater import _parse_build_number
        assert _parse_build_number("") == 0

    def test_high_build(self):
        from utils.updater import _parse_build_number
        assert _parse_build_number("v0.1.0-beta.999") == 999


class TestCheckForUpdate:
    @patch("utils.updater.BUILD_NUMBER", 10)
    @patch("utils.updater.urlopen")
    def test_update_available(self, mock_urlopen):
        # API returns a list of releases (newest first)
        response_data = json.dumps([{
            "tag_name": "v0.1.0-beta.20",
            "html_url": "https://github.com/test/releases/v0.1.0-beta.20",
            "body": "Release notes",
            "assets": [{"name": "PushkaVoice-macos-arm64.zip",
                        "browser_download_url": "https://example.com/download.zip"}],
        }]).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from utils.updater import check_for_update
        result = check_for_update()

        assert result["available"] is True
        assert result["tag"] == "v0.1.0-beta.20"
        assert result["build"] == 20
        assert result["download_url"] == "https://example.com/download.zip"
        assert result["error"] is None

    @patch("utils.updater.BUILD_NUMBER", 20)
    @patch("utils.updater.urlopen")
    def test_no_update_available(self, mock_urlopen):
        response_data = json.dumps([{
            "tag_name": "v0.1.0-beta.20",
            "html_url": "https://github.com/test/releases",
            "body": "",
            "assets": [{"name": "PushkaVoice-macos-arm64.zip",
                        "browser_download_url": "https://example.com/download.zip"}],
        }]).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from utils.updater import check_for_update
        result = check_for_update()

        assert result["available"] is False

    @patch("utils.updater.urlopen")
    def test_empty_releases(self, mock_urlopen):
        response_data = json.dumps([]).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from utils.updater import check_for_update
        result = check_for_update()

        assert result["available"] is False
        assert result["error"] == "No releases found"

    @patch("utils.updater.urlopen")
    def test_network_error(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")

        from utils.updater import check_for_update
        result = check_for_update()

        assert result["available"] is False
        assert result["error"] is not None
        assert "Network error" in result["error"]


class TestUpdater:
    def test_status_defaults(self):
        from utils.updater import Updater
        u = Updater()
        s = u.status
        assert s["progress"] == 0
        assert s["downloading"] is False
        assert s["done"] is False
        assert s["error"] is None

    def test_download_requires_frozen(self):
        from utils.updater import Updater
        u = Updater()
        u.download_and_install("https://example.com/download.zip")
        assert u.status["error"] is not None
        assert "bundled mode" in u.status["error"]


class TestVersion:
    def test_version_is_string(self):
        from utils.version import VERSION
        assert isinstance(VERSION, str)
        assert "." in VERSION

    def test_build_number_is_int(self):
        from utils.version import BUILD_NUMBER
        assert isinstance(BUILD_NUMBER, int)

    def test_github_repo_set(self):
        from utils.version import GITHUB_REPO
        assert "/" in GITHUB_REPO
