"""Tests for core/clipboard.py."""
from unittest.mock import MagicMock, patch, call

import pytest


class TestCopyToClipboard:
    @patch("core.clipboard.subprocess.Popen")
    def test_copies_text_via_pbcopy(self, mock_popen):
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        from core.clipboard import copy_to_clipboard
        copy_to_clipboard("Привет мир")

        mock_popen.assert_called_once_with(["pbcopy"], stdin=-1)  # subprocess.PIPE = -1
        mock_proc.communicate.assert_called_once_with("Привет мир".encode("utf-8"))

    @patch("core.clipboard.subprocess.Popen")
    def test_handles_empty_string(self, mock_popen):
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc

        from core.clipboard import copy_to_clipboard
        copy_to_clipboard("")

        mock_proc.communicate.assert_called_once_with(b"")


class TestPasteAtCursor:
    @patch("core.clipboard.subprocess.run")
    def test_fallback_to_osascript(self, mock_run):
        """When Quartz import fails, falls back to osascript."""
        import sys
        # Ensure Quartz raises on import inside paste_at_cursor
        original = sys.modules.get("Quartz")
        sys.modules["Quartz"] = None  # will cause ImportError on attribute access

        mock_run.return_value = MagicMock(returncode=0)

        from core.clipboard import paste_at_cursor
        paste_at_cursor()

        # Should have called osascript
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "osascript" in call_args

        # Restore
        if original is not None:
            sys.modules["Quartz"] = original

    @patch("core.clipboard.subprocess.run")
    def test_osascript_failure_logged(self, mock_run):
        import sys
        sys.modules["Quartz"] = None

        mock_run.return_value = MagicMock(returncode=1, stderr="permission denied")

        from core.clipboard import paste_at_cursor
        paste_at_cursor()  # should not raise


class TestCopyAndPaste:
    @patch("core.clipboard.paste_at_cursor")
    @patch("core.clipboard.copy_to_clipboard")
    @patch("core.clipboard.time.sleep")
    def test_copies_then_pastes_with_delay(self, mock_sleep, mock_copy, mock_paste):
        from core.clipboard import copy_and_paste
        copy_and_paste("тест")

        mock_copy.assert_called_once_with("тест")
        mock_sleep.assert_called_once_with(0.3)
        mock_paste.assert_called_once()
