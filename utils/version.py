"""Single source of truth for the app version.

The build number is injected by CI (see .github/workflows/build-macos.yml).
During development, BUILD_NUMBER is 0.
"""

VERSION = "0.1.0"
BUILD_NUMBER = 0  # Replaced by CI: sed -i "s/BUILD_NUMBER = 0/BUILD_NUMBER = N/"

GITHUB_REPO = "andrewcigan/PushkaVoice"
