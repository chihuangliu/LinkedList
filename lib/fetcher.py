import re
import time
import requests


TRACKER_URL = "https://www.linkedin.com/jobs-tracker/"
POSTINGS_URL = "https://www.linkedin.com/voyager/api/jobs/jobPostings"
COMPANY_URL = "https://www.linkedin.com/voyager/api/entities/companies"


def fetch_tracker_html(session: requests.Session, stage: str = "saved") -> str:
    # The tracker page route sometimes 302-loops to itself (LinkedIn's
    # anti-automation gate / forced re-auth). Disable auto-redirects so we fail
    # fast with a clear message instead of raising TooManyRedirects.
    resp = session.get(f"{TRACKER_URL}?stage={stage}", allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        raise RuntimeError(
            f"Tracker page redirected (HTTP {resp.status_code}) — LinkedIn is "
            f"gating automated access (rate-limit / re-auth). Try again later "
            f"or refresh your cookies."
        )
    resp.raise_for_status()
    return resp.text


def extract_job_ids(html: str) -> list[str]:
    # Job IDs appear as bare 10-digit numbers repeated in the SSR state
    candidates = re.findall(r'\b(4\d{9})\b', html)
    seen, ordered = set(), []
    for jid in candidates:
        if jid not in seen:
            seen.add(jid)
            ordered.append(jid)
    return ordered


def fetch_postings(session: requests.Session, job_ids: list[str], delay: float = 1.0) -> list[dict]:
    results = []
    # Fetch in batches of 10
    for i in range(0, len(job_ids), 10):
        batch = job_ids[i:i+10]
        ids_param = f"List({','.join(batch)})"
        resp = session.get(POSTINGS_URL, params={
            "ids": ids_param,
            "decorationId": "com.linkedin.voyager.deco.jobs.web.shared.WebLightJobPosting-23",
        })
        if resp.status_code == 200:
            data = resp.json()
            for jid in batch:
                key = f"urn:li:fs_jobPosting:{jid}"
                posting = data.get("results", {}).get(key) or data.get(key)
                if posting:
                    results.append({"job_id": jid, "raw": posting})
        time.sleep(delay)
    return results


def fetch_posting_single(session: requests.Session, job_id: str) -> dict | None:
    resp = session.get(f"{POSTINGS_URL}/{job_id}")
    if resp.status_code == 200:
        return resp.json()
    return None


def fetch_companies(session: requests.Session, company_ids: list[str], delay: float = 1.0) -> dict[str, dict]:
    result = {}
    for cid in company_ids:
        resp = session.get(f"{COMPANY_URL}/{cid}")
        if resp.status_code == 200:
            result[cid] = resp.json()
        time.sleep(delay)
    return result


def parse_company_urn(urn: str) -> str | None:
    # urn:li:fs_normalized_company:24024765 -> "24024765"
    parts = urn.split(":")
    if len(parts) >= 4 and parts[-1].isdigit():
        return parts[-1]
    return None


def parse_job(job_id: str, posting: dict, company_data: dict | None) -> dict:
    title = posting.get("title", "")
    location = posting.get("formattedLocation", posting.get("country", ""))
    jd = posting.get("description", {}).get("text", "")

    # Company from posting
    company_details = posting.get("companyDetails", {})
    inner = company_details.get("com.linkedin.voyager.jobs.JobPostingCompany", {})
    company_urn = inner.get("company", "")
    company_id = parse_company_urn(company_urn) or ""

    company_name = ""
    staff_count = None
    company_type = ""
    founded_year = None
    company_url = ""

    if company_data:
        basic = company_data.get("basicCompanyInfo", {})
        mini = basic.get("miniCompany", {})
        company_name = mini.get("name", "")
        company_url = company_data.get("websiteUrl", "")
        company_type = company_data.get("companyType", "")
        founded_year = company_data.get("foundedDate", {}).get("year")
        count_range = company_data.get("employeeCountRange", "")
        # Store the range string; also try to get a midpoint for rough comparison
        staff_count = count_range

    job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"

    return {
        "job_id": job_id,
        "title": title,
        "company": company_name,
        "company_id": company_id,
        "location": location,
        "jd_text": jd,
        "url": job_url,
        "company_type": company_type,
        "staff_count": staff_count,
        "founded_year": founded_year,
        "company_url": company_url,
    }


def sync_jobs(
    session: requests.Session,
    delay: float = 1.0,
    cookies_path: str | None = None,
    stage: str = "saved",
    cdp_url: str | None = None,
) -> list[dict]:
    # Preferred path: drive the user's real Chrome via CDP. The live session
    # passes PerimeterX, so we can page through every job and fetch all details
    # through the browser's own fetch(). See lib/browser.py.
    if cdp_url:
        print(f"Syncing all '{stage}' jobs via Chrome (CDP {cdp_url})...")
        try:
            from lib import browser as browser_mod
            parsed = browser_mod.fetch_jobs_full_cdp(cdp_url=cdp_url, stage=stage)
            print(f"Parsed {len(parsed)} jobs via CDP.")
            return parsed
        except Exception as e:
            print(f"  CDP sync failed: {e}\n  Falling back to HTTP path...")

    job_ids = []
    if not job_ids:
        print("  Falling back to HTML scrape (first page only, ~10 jobs)...")
        try:
            html = fetch_tracker_html(session, stage=stage)
            job_ids = extract_job_ids(html)
        except RuntimeError as e:
            print(f"  HTML scrape failed: {e}")

    print(f"Found {len(job_ids)} job IDs: {job_ids}")

    print("Fetching job details...")
    jobs_raw = []
    for jid in job_ids:
        posting = fetch_posting_single(session, jid)
        if posting:
            jobs_raw.append({"job_id": jid, "raw": posting})
        else:
            print(f"  Warning: could not fetch job {jid}")
        time.sleep(delay)

    print("Fetching company details...")
    company_ids = []
    for j in jobs_raw:
        cd = j["raw"].get("companyDetails", {})
        inner = cd.get("com.linkedin.voyager.jobs.JobPostingCompany", {})
        urn = inner.get("company", "")
        cid = parse_company_urn(urn)
        if cid:
            company_ids.append(cid)

    companies = fetch_companies(session, list(set(company_ids)), delay=delay)

    print("Parsing jobs...")
    parsed = []
    for j in jobs_raw:
        cd = j["raw"].get("companyDetails", {})
        inner = cd.get("com.linkedin.voyager.jobs.JobPostingCompany", {})
        urn = inner.get("company", "")
        cid = parse_company_urn(urn)
        company_data = companies.get(cid) if cid else None
        parsed.append(parse_job(j["job_id"], j["raw"], company_data))

    return parsed
