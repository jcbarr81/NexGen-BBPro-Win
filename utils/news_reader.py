from pathlib import Path

from utils.path_utils import resolve_app_path
from utils.news_logger import sanitize_news_text


def read_latest_news(n: int = 10, file_path: str | Path = "data/news_feed.txt"):
    """Return the latest ``n`` news items (most recent first)."""

    path = resolve_app_path(file_path)
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [sanitize_news_text(line.rstrip("\n")) for line in f]
        return list(reversed(lines[-n:]))
    except FileNotFoundError:
        return []
