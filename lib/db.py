import json
import sqlite3
from datetime import datetime, timezone


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    title         TEXT,
    company       TEXT,
    company_id    TEXT,
    location      TEXT,
    jd_text       TEXT,
    url           TEXT,
    company_type  TEXT,
    staff_count   TEXT,
    founded_year  INTEGER,
    company_url   TEXT,
    category      TEXT,
    visa          TEXT,
    type          TEXT,
    leetcode      TEXT,
    classified_at TEXT,
    synced_at     TEXT NOT NULL,
    extra_labels  TEXT DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'active'
);
"""


def connect(db_path: str = "jobs.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Migration: add `status` to pre-existing tables (defaults existing rows to 'active').
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "status" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    conn.commit()
    return conn


def upsert_jobs(
    conn: sqlite3.Connection, jobs: list[dict], prune: bool = False
) -> tuple[int, int, int]:
    """Insert/update jobs, preserving classification labels.

    Re-activates any fetched job (status='active'). If ``prune`` is set and the
    fetch returned results, any currently-active job NOT in this fetch is marked
    status='removed' (soft delete — labels are kept). Returns
    (total_fetched, new_count, removed_count).
    """
    now = datetime.now(timezone.utc).isoformat()
    active_before = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='active'"
    ).fetchone()[0]
    new_count = 0
    for job in jobs:
        existing = conn.execute(
            "SELECT job_id FROM jobs WHERE job_id = ?", (job["job_id"],)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE jobs SET title=?, company=?, company_id=?, location=?,
                   jd_text=?, url=?, company_type=?, staff_count=?, founded_year=?,
                   company_url=?, synced_at=?, status='active' WHERE job_id=?""",
                (
                    job["title"], job["company"], job["company_id"], job["location"],
                    job["jd_text"], job["url"], job["company_type"], job["staff_count"],
                    job["founded_year"], job["company_url"], now, job["job_id"],
                ),
            )
        else:
            conn.execute(
                """INSERT INTO jobs (job_id, title, company, company_id, location,
                   jd_text, url, company_type, staff_count, founded_year, company_url,
                   synced_at, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'active')""",
                (
                    job["job_id"], job["title"], job["company"], job["company_id"],
                    job["location"], job["jd_text"], job["url"], job["company_type"],
                    job["staff_count"], job["founded_year"], job["company_url"], now,
                ),
            )
            new_count += 1

    removed_count = 0
    if prune and jobs:
        # Safety: a healthy full fetch is roughly the size of the active set.
        # If it's drastically smaller, it's probably a partial/failed fetch —
        # skip pruning so we don't wrongly mark everything removed.
        if active_before and len(jobs) < 0.5 * active_before:
            print(
                f"  Skipping prune: fetch returned {len(jobs)} jobs but "
                f"{active_before} are active — looks partial, not pruning."
            )
        else:
            ids = [j["job_id"] for j in jobs]
            placeholders = ",".join("?" * len(ids))
            cur = conn.execute(
                f"UPDATE jobs SET status='removed' "
                f"WHERE status='active' AND job_id NOT IN ({placeholders})",
                ids,
            )
            removed_count = cur.rowcount

    conn.commit()
    return len(jobs), new_count, removed_count


def save_labels(conn: sqlite3.Connection, job_id: str, labels: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    extra = {k: v for k, v in labels.items() if k not in {"category", "visa", "type", "leetcode"}}
    conn.execute(
        """UPDATE jobs SET category=?, visa=?, type=?, leetcode=?,
           classified_at=?, extra_labels=? WHERE job_id=?""",
        (
            labels.get("category"), labels.get("visa"),
            labels.get("type"), labels.get("leetcode"),
            now, json.dumps(extra), job_id,
        ),
    )
    conn.commit()


def get_unclassified(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE category IS NULL AND status='active' "
        "ORDER BY synced_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM jobs ORDER BY synced_at DESC").fetchall()
    return [dict(r) for r in rows]


def query_jobs(conn: sqlite3.Connection, filters: dict, include_removed: bool = False) -> list[dict]:
    clauses, params = [], []
    if not include_removed:
        clauses.append("status='active'")
    for field, values in filters.items():
        if not values:
            continue
        placeholders = ",".join("?" * len(values))
        clauses.append(f"{field} IN ({placeholders})")
        params.extend(values)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY synced_at DESC", params
    ).fetchall()
    return [dict(r) for r in rows]
