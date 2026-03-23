# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PushkaVoice macOS app."""

import os
import sys
from pathlib import Path

block_cipher = None

# Collect all data files
datas = [
    ('ui/web', 'ui/web'),
    ('config/settings.example.json', 'config'),
]

# Hidden imports that PyInstaller can't detect automatically
hiddenimports = [
    'gigaam',
    'gigaam.model',
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
    'sentencepiece',
    'hydra',
    'omegaconf',
    'AppKit',
    'Foundation',
    'Cocoa',
    'objc',
    'PyObjCTools',
    'PyObjCTools.Conversion',
    'Quartz',
    'Quartz.CoreGraphics',
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
    argv_emulation=True,
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
        'CFBundleVersion': '0.1.0',
        'CFBundleShortVersionString': '0.1.0',
        'NSMicrophoneUsageDescription': 'PushkaVoice needs microphone access for speech dictation.',
        'NSAppleEventsUsageDescription': 'PushkaVoice needs automation access for auto-paste functionality.',
    },
)
