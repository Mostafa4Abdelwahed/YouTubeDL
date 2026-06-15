import sqlite3
import os


DB_PATH = os.path.join(os.path.dirname(__file__), "history.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            video_id     TEXT PRIMARY KEY,
            title        TEXT,
            url          TEXT,
            output_format TEXT,
            output_path  TEXT,
            downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add output_path column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE downloads ADD COLUMN output_path TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


def already_downloaded(video_id: str) -> bool:
    """Return True only if in history AND the output file still exists on disk."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT output_path FROM downloads WHERE video_id = ?", (video_id,)
        ).fetchone()
    if row is None:
        return False
    output_path = row[0]
    # No path recorded means we can't verify — treat as not downloaded
    if not output_path:
        return False
    return os.path.isfile(output_path)


def mark_downloaded(video_id: str, title: str, url: str,
                    output_format: str, output_path: str = "") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO downloads "
            "(video_id, title, url, output_format, output_path) VALUES (?, ?, ?, ?, ?)",
            (video_id, title, url, output_format, output_path),
        )
        conn.commit()


def get_history(limit: int = 100) -> list:
    with _connect() as conn:
        return conn.execute(
            "SELECT video_id, title, url, output_format, output_path, downloaded_at "
            "FROM downloads ORDER BY downloaded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()


def clear_history() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM downloads")
        conn.commit()
