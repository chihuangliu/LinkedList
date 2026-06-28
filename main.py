#!/usr/bin/env python3
import json
import sys

import click
from tabulate import tabulate

from lib import config as cfg_mod
from lib import cookies as cookies_mod
from lib import db as db_mod
from lib import fetcher as fetcher_mod


DB_PATH = "jobs.db"
CONFIG_PATH = "config.yaml"
LABEL_FIELDS = ["category", "visa", "type", "leetcode"]


def _conn():
    return db_mod.connect(DB_PATH)


def _cfg():
    return cfg_mod.load(CONFIG_PATH)


def _session():
    c = _cfg()
    cookies_path = c.get("linkedin", {}).get("cookies_path", "./www.linkedin.com_cookies.txt")
    return cookies_mod.build_session(cookies_path)


def _fmt_jobs(jobs: list[dict], verbose: bool = False) -> str:
    if not jobs:
        return "(no jobs found)"
    rows = []
    for j in jobs:
        classified = "✓" if j.get("category") else "—"
        rows.append([
            j["job_id"],
            (j.get("title") or "")[:42],
            (j.get("company") or "")[:22],
            j.get("category") or "—",
            j.get("visa") or "—",
            j.get("type") or "—",
            j.get("leetcode") or "—",
            classified,
        ])
    headers = ["ID", "Title", "Company", "Category", "Visa", "Type", "Leetcode", "✓"]
    return tabulate(rows, headers=headers, tablefmt="simple")


def _fmt_detail(job: dict) -> str:
    lines = [
        f"Job ID    : {job['job_id']}",
        f"Title     : {job.get('title')}",
        f"Company   : {job.get('company')} (ID: {job.get('company_id')})",
        f"Location  : {job.get('location')}",
        f"URL       : {job.get('url')}",
        f"Staff     : {job.get('staff_count')}  |  Founded: {job.get('founded_year')}",
        f"Co. type  : {job.get('company_type')}  |  Website: {job.get('company_url')}",
        "",
        f"Category  : {job.get('category') or '(unclassified)'}",
        f"Visa      : {job.get('visa') or '(unclassified)'}",
        f"Type      : {job.get('type') or '(unclassified)'}",
        f"Leetcode  : {job.get('leetcode') or '(unclassified)'}",
        f"Classified: {job.get('classified_at') or '—'}",
        "",
        "=== Job Description ===",
        job.get("jd_text") or "(empty)",
    ]
    return "\n".join(lines)


@click.group()
def cli():
    """LinkedIn Jobs Tracker — fetch, classify, and filter your saved jobs."""


@cli.command()
@click.option("--no-classify", is_flag=True, help="Fetch data only; skip classification output")
@click.option("--cdp", "cdp_url", default=None, is_flag=False, flag_value="http://localhost:9222",
              help="Drive a running Chrome via CDP (reliable; passes bot detection). "
                   "Launch Chrome with --remote-debugging-port=9222 first. "
                   "Optionally pass a custom URL: --cdp http://localhost:PORT")
@click.option("--stage", default="saved", help="Tracker stage: saved, applied, archived, ...")
def fetch(no_classify, cdp_url, stage):
    """Fetch all jobs from LinkedIn Jobs Tracker and save raw data to SQLite.

    Outputs unclassified jobs as JSON for Claude Code to classify.
    """
    c = _cfg()
    delay = c.get("linkedin", {}).get("request_delay_seconds", 1.0)
    cookies_path = c.get("linkedin", {}).get("cookies_path", "./www.linkedin.com_cookies.txt")
    session, _ = _session()
    jobs = fetcher_mod.sync_jobs(
        session, delay=delay, cookies_path=cookies_path, stage=stage, cdp_url=cdp_url
    )

    conn = _conn()
    # Only prune on a full CDP sync; a plain/fallback fetch may be partial.
    total, new_count, removed_count = db_mod.upsert_jobs(conn, jobs, prune=bool(cdp_url))
    msg = f"\nSync complete: {total} jobs fetched, {new_count} new"
    if removed_count:
        msg += f", {removed_count} no longer saved (marked removed)"
    print(msg + ".")

    if no_classify:
        return

    unclassified = db_mod.get_unclassified(conn)
    if not unclassified:
        print("All jobs already classified. Run `list` to see results.")
        return

    print(f"\n{len(unclassified)} job(s) need classification. Output for Claude Code:\n")
    print("=" * 60)
    for job in unclassified:
        print(json.dumps({
            "job_id": job["job_id"],
            "title": job["title"],
            "company": job["company"],
            "staff_count": job["staff_count"],
            "company_type": job["company_type"],
            "founded_year": job["founded_year"],
            "location": job["location"],
            "jd_text": job["jd_text"],
        }, ensure_ascii=False, indent=2))
        print("-" * 40)
    print("=" * 60)
    print("\nAfter classifying, run:")
    print("  python main.py save-labels --job-id JOB_ID --category X --visa X --type X --leetcode X")


@cli.command("save-labels")
@click.option("--job-id", required=True, help="Job ID to label")
@click.option("--category", type=click.Choice(["big_tech", "mid_size", "startup"]), required=True)
@click.option("--visa", type=click.Choice(["likely", "not_available", "maybe"]), required=True)
@click.option("--type", "job_type", type=click.Choice(["mle", "agentic_ai", "ml_scientist", "ai_ml_mixed", "data_scientist", "swe"]), required=True)
@click.option("--leetcode", type=click.Choice(["hard", "medium", "low"]), required=True)
def save_labels(job_id, category, visa, job_type, leetcode):
    """Save classification labels for a job."""
    conn = _conn()
    db_mod.save_labels(conn, job_id, {
        "category": category,
        "visa": visa,
        "type": job_type,
        "leetcode": leetcode,
    })
    print(f"Labels saved for job {job_id}.")


@cli.command("save-labels-batch")
@click.argument("json_input", default="-")
def save_labels_batch(json_input):
    """Save labels for multiple jobs from JSON (stdin or file path).

    JSON format: [{"job_id": "...", "category": "...", "visa": "...", "type": "...", "leetcode": "..."}, ...]
    """
    if json_input == "-":
        data = json.load(sys.stdin)
    else:
        with open(json_input) as f:
            data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    conn = _conn()
    for item in data:
        db_mod.save_labels(conn, item["job_id"], item)
        print(f"  Saved: {item['job_id']}")
    print(f"Done: {len(data)} job(s) labelled.")


def _parse_multi(value: tuple[str, ...]) -> list[str]:
    """Flatten comma-separated or repeated flag values: 'a,b' or ('a','b') → ['a','b']."""
    out = []
    for v in value:
        out.extend(x.strip() for x in v.split(",") if x.strip())
    return out


@cli.command("list")
@click.option("--category", multiple=True, help="Filter: big_tech,mid_size,startup (comma or repeated)")
@click.option("--visa", multiple=True, help="Filter: available,not_available,maybe")
@click.option("--type", "job_type", multiple=True, help="Filter: mle,agentic_ai,ml_scientist,ai_ml_mixed,data_scientist")
@click.option("--leetcode", multiple=True, help="Filter: hard,medium,low")
@click.option("--unclassified", is_flag=True, help="Show only unclassified jobs")
@click.option("--include-removed", is_flag=True, help="Also show jobs no longer in your saved list")
@click.option("--removed-only", is_flag=True, help="Show only removed (no longer saved) jobs")
def list_jobs(category, visa, job_type, leetcode, unclassified, include_removed, removed_only):
    """List jobs with optional filters. Removed (no longer saved) jobs are hidden by default.

    Accepts comma-separated values or repeated flags:

      python main.py list --visa likely,maybe --leetcode medium,low

      python main.py list --type mle --type agentic_ai --category big_tech
    """
    conn = _conn()
    if unclassified:
        jobs = db_mod.get_unclassified(conn)
    else:
        filters = {
            k: v for k, v in {
                "category": _parse_multi(category),
                "visa": _parse_multi(visa),
                "type": _parse_multi(job_type),
                "leetcode": _parse_multi(leetcode),
            }.items() if v
        }
        if removed_only:
            filters["status"] = ["removed"]
        jobs = db_mod.query_jobs(conn, filters, include_removed=include_removed or removed_only)
    print(_fmt_jobs(jobs))
    print(f"\n{len(jobs)} job(s)")


@cli.command("show")
@click.argument("job_id")
def show(job_id):
    """Show full details for a single job."""
    conn = _conn()
    rows = db_mod.query_jobs(conn, {}, include_removed=True)
    job = next((j for j in rows if j["job_id"] == job_id), None)
    if not job:
        print(f"Job {job_id} not found.")
        sys.exit(1)
    print(_fmt_detail(job))


@cli.command("clear-labels")
@click.argument("job_id")
def clear_labels(job_id):
    """Clear classification labels for a job (so it gets re-classified on next fetch)."""
    conn = _conn()
    conn.execute(
        "UPDATE jobs SET category=NULL, visa=NULL, type=NULL, leetcode=NULL, classified_at=NULL WHERE job_id=?",
        (job_id,),
    )
    conn.commit()
    print(f"Labels cleared for {job_id}.")


if __name__ == "__main__":
    cli()
