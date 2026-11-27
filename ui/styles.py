from __future__ import annotations

from pathlib import Path


def load_app_css() -> str:
    css_path = Path(__file__).with_name("styles.css")
    return f"<style>\n{css_path.read_text(encoding='utf-8')}\n</style>"
