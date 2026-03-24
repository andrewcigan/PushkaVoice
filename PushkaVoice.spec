# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PushkaVoice macOS app."""

import os
import sys
from pathlib import Path

block_cipher = None

# Read version from version.py
_version_vars = {}
with open('utils/version.py') as f:
    exec(f.read(), _version_vars)
APP_VERSION = _version_vars.get('VERSION', '0.1.0')
APP_BUILD = str(_version_vars.get('BUILD_NUMBER', 0))

# Include certifi CA bundle so HTTPS works in bundled app
try:
    import certifi
    certifi_data = [(certifi.where(), 'certifi')]
except ImportError:
    certifi_data = []

# Collect all data files
datas = [
    ('ui/web', 'ui/web'),
    ('config/settings.example.json', 'config'),
] + certifi_data

# Hidden imports that PyInstaller can't detect automatically
hiddenimports = [
    'gigaam',
    'gigaam.model',
    'gigaam.encoder',
    'gigaam.decoder',
    'gigaam.decoding',
    'gigaam.preprocess',
    'gigaam.utils',
    'gigaam.onnx_utils',
    'gigaam.vad_utils',
    'torch',
    'torchaudio',
    'torchaudio.functional',
    'torchaudio.transforms',
    'sounddevice',
    'numpy',
    'pynput',
    'pynput.keyboard',
    'pynput.keyboard._darwin',
    'webview',
    'dotenv',
    'certifi',
    'sentencepiece',
    'hydra',
    'hydra.core',
    'hydra.core.config_store',
    'hydra._internal',
    'hydra._internal.utils',
    'hydra._internal.instantiate',
    'hydra._internal.instantiate._instantiate2',
    'omegaconf',
    'AppKit',
    'Foundation',
    'Cocoa',
    'objc',
    'PyObjCTools',
    'PyObjCTools.Conversion',
    'Quartz',
    'Quartz.CoreGraphics',
    'ApplicationServices',
    '_sounddevice_data',
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'scipy',
        'pandas',
        'pytest',
        'pytest_cov',
        '_pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PushkaVoice',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PushkaVoice',
)

app = BUNDLE(
    coll,
    name='PushkaVoice.app',
    icon=None,
    bundle_identifier='com.pushkavoice.app',
    info_plist={
        'CFBundleName': 'PushkaVoice',
        'CFBundleDisplayName': 'PushkaVoice',
        'CFBundleVersion': f'{APP_VERSION}.{APP_BUILD}',
        'CFBundleShortVersionString': APP_VERSION,
        'NSMicrophoneUsageDescription': 'PushkaVoice needs microphone access for speech dictation.',
        'NSAppleEventsUsageDescription': 'PushkaVoice needs automation access for auto-paste functionality.',
        'LSMultipleInstancesProhibited': True,
    },
)
