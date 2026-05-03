"""py2app build descriptor for PersoWhisper.

Build (alias mode — bundle uses the live venv, no copy of site-packages):
    ./whisperx-env/bin/python setup.py py2app -A

Why py2app: the bundle's launcher is a real Mach-O binary that embeds Python
in-process. TCC then attributes the running process to the bundle's identifier
(com.borisploix.persowhisper) instead of to Homebrew's framework Python — so a
single Accessibility grant on the .app actually applies.
"""

from setuptools import setup

APP = ["persowhisper_launcher.py"]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "AppIcon.icns",
    "plist": {
        "CFBundleName": "PersoWhisper",
        "CFBundleDisplayName": "PersoWhisper",
        "CFBundleIdentifier": "com.borisploix.persowhisper",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": False,
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "PersoWhisper records your voice to transcribe dictation.",
        "NSAppleEventsUsageDescription": "PersoWhisper uses System Events to paste transcribed text into the focused field.",
    },
}

setup(
    name="PersoWhisper",
    app=APP,
    setup_requires=["py2app"],
    options={"py2app": OPTIONS},
)
