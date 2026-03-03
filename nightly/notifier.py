"""
nightly/notifier.py — Notification macOS via osascript
"""

import subprocess


def notify(title: str, message: str):
    """Affiche une notification macOS."""
    script = (
        f'display notification "{message}" '
        f'with title "{title}" '
        f'sound name "Ping"'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10)
    except Exception as e:
        print(f"  [notifier] Erreur osascript: {e}")
