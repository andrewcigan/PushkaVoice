import os
import subprocess
import sys
from pathlib import Path

PLIST_NAME = "com.dictation.gigaam.plist"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def get_plist_path() -> Path:
    return LAUNCH_AGENTS_DIR / PLIST_NAME


def get_plist_content() -> str:
    python_path = sys.executable
    app_path = str(Path(__file__).parent.parent / "app.py")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dictation.gigaam</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>"""


def is_installed() -> bool:
    return get_plist_path().exists()


def install():
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plist_path = get_plist_path()
    plist_path.write_text(get_plist_content())
    subprocess.run(["launchctl", "load", str(plist_path)], check=False)


def uninstall():
    plist_path = get_plist_path()
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        plist_path.unlink()
