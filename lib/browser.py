"""Browser-based fetching for the LinkedIn jobs tracker.

The tracker page is server-driven (SDUI) and only renders the first ~10 jobs
in its initial HTML. The rest load lazily as the user scrolls, and there is no
stable public pagination endpoint. So to collect *all* saved jobs we drive a
real headless browser, scroll the list to the bottom, and harvest the job IDs
that get rendered along the way.
"""

import re


def load_cookies_for_playwright(cookies_path: str) -> list[dict]:
    """Read a Netscape cookie file into Playwright cookie dicts.

    LinkedIn's auth cookie (``li_at``) is often stored on ``.www.linkedin.com``
    in exported cookie files. The ``requests`` library ignores cookie domains
    entirely, so it works regardless — but a real browser enforces domain
    matching. We normalise everything onto ``.linkedin.com`` (which covers every
    LinkedIn host) so the session is recognised. JSESSIONID must keep its quotes.
    """
    cookies = []
    seen = set()
    with open(cookies_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            name, value = parts[5], parts[6]
            if name in seen:
                continue
            seen.add(name)
            if name != "JSESSIONID":
                value = value.strip('"')
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".linkedin.com",
                "path": "/",
                "secure": True,
                "sameSite": "None",
            })
    return cookies


def _extract_ids(text: str) -> list[str]:
    seen, ordered = set(), []
    for jid in re.findall(r"\b(4\d{9})\b", text):
        if jid not in seen:
            seen.add(jid)
            ordered.append(jid)
    return ordered


def fetch_saved_job_ids(
    cookies_path: str,
    stage: str = "saved",
    headless: bool = True,
    max_pages: int = 50,
    settle_ms: int = 2000,
    nav_retries: int = 6,
) -> list[str]:
    """Open the jobs tracker in a browser and page through the list.

    The tracker uses traditional pagination (1, 2, 3, … Next), so we load the
    first page, harvest job IDs, click "Next", and repeat until there is no
    enabled Next button left.

    Returns the ordered list of job IDs for the given stage. Raises RuntimeError
    if the page can't be loaded (expired cookies, anti-bot gate, rate limit).
    """
    from playwright.sync_api import sync_playwright

    url = f"https://www.linkedin.com/jobs-tracker/?stage={stage}"
    cookies = load_cookies_for_playwright(cookies_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        # The tracker page route intermittently 302-loops (anti-automation gate);
        # retry a few times before giving up.
        last_err = None
        loaded = False
        for attempt in range(nav_retries):
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                last_err = e
                page.wait_for_timeout(2500)
                continue
            if resp and resp.status >= 400:
                last_err = RuntimeError(f"HTTP {resp.status}")
                page.wait_for_timeout(2500)
                continue
            if "/jobs-tracker" in page.url:
                loaded = True
                break
            last_err = RuntimeError(f"redirected to {page.url}")
            page.wait_for_timeout(2500)

        if not loaded:
            browser.close()
            raise RuntimeError(
                f"Could not load tracker page after {nav_retries} tries "
                f"(last: {last_err}). LinkedIn is gating automated access — "
                f"wait and retry, or use headless=False."
            )

        ids = _collect_ids_from_pages(page, max_pages=max_pages, settle_ms=settle_ms)
        browser.close()
        return ids


def fetch_saved_job_ids_cdp(
    cdp_url: str = "http://localhost:9222",
    stage: str = "saved",
    max_pages: int = 50,
    settle_ms: int = 2500,
) -> list[str]:
    """Collect all job IDs by driving an already-running real Chrome via CDP.

    The user launches Chrome with --remote-debugging-port and logs into
    LinkedIn; that live session already passes PerimeterX bot detection, so the
    tracker loads normally and we can page through it. Returns ordered job IDs.
    """
    from playwright.sync_api import sync_playwright

    url = f"https://www.linkedin.com/jobs-tracker/?stage={stage}"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if "/jobs-tracker" not in page.url:
                raise RuntimeError(
                    f"Redirected to {page.url} — is this Chrome logged into LinkedIn?"
                )
            page.wait_for_timeout(settle_ms)
            ids = _collect_ids_from_pages(page, max_pages=max_pages, settle_ms=settle_ms)
        finally:
            page.close()
            browser.close()
        return ids


def fetch_jobs_full_cdp(
    cdp_url: str = "http://localhost:9222",
    stage: str = "saved",
    max_pages: int = 50,
    settle_ms: int = 2500,
) -> list[dict]:
    """Full sync via a running Chrome (CDP): all job IDs + job/company details.

    Everything is fetched through the real browser's own ``fetch()`` so it passes
    PerimeterX. Returns parsed job dicts ready for the DB (same shape as
    ``fetcher.parse_job``).
    """
    from playwright.sync_api import sync_playwright
    from lib import fetcher as fetcher_mod

    url = f"https://www.linkedin.com/jobs-tracker/?stage={stage}"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if "/jobs-tracker" not in page.url:
                raise RuntimeError(
                    f"Redirected to {page.url} — is this Chrome logged into LinkedIn?"
                )
            page.wait_for_timeout(settle_ms)

            ids = _collect_ids_from_pages(page, max_pages=max_pages, settle_ms=settle_ms)
            print(f"  Collected {len(ids)} job IDs. Fetching job details...")

            csrf = next(
                (c["value"] for c in ctx.cookies() if c["name"] == "JSESSIONID"), ""
            ).strip('"')

            postings = _fetch_json_batch(page, csrf, [
                f"https://www.linkedin.com/voyager/api/jobs/jobPostings/{jid}" for jid in ids
            ])

            # Map job_id -> raw posting; collect company IDs to fetch.
            raw_by_id = {}
            company_ids = set()
            for jid, raw in zip(ids, postings):
                if not raw:
                    continue
                raw_by_id[jid] = raw
                cd = raw.get("companyDetails", {})
                inner = cd.get("com.linkedin.voyager.jobs.JobPostingCompany", {})
                cid = fetcher_mod.parse_company_urn(inner.get("company", ""))
                if cid:
                    company_ids.add(cid)

            print(f"  Got {len(raw_by_id)}/{len(ids)} postings. "
                  f"Fetching {len(company_ids)} companies...")

            company_ids = list(company_ids)
            company_raw = _fetch_json_batch(page, csrf, [
                f"https://www.linkedin.com/voyager/api/entities/companies/{cid}"
                for cid in company_ids
            ])
            companies = {cid: raw for cid, raw in zip(company_ids, company_raw) if raw}

            parsed = []
            for jid in ids:
                raw = raw_by_id.get(jid)
                if not raw:
                    continue
                cd = raw.get("companyDetails", {})
                inner = cd.get("com.linkedin.voyager.jobs.JobPostingCompany", {})
                cid = fetcher_mod.parse_company_urn(inner.get("company", ""))
                parsed.append(fetcher_mod.parse_job(jid, raw, companies.get(cid)))
            return parsed
        finally:
            page.close()
            browser.close()


def _fetch_json_batch(page, csrf: str, urls: list[str], delay_ms: int = 120) -> list:
    """Fetch many URLs via the page's own fetch(); returns parsed JSON or None each."""
    return page.evaluate(
        """async ([urls, csrf, delayMs]) => {
            const out = [];
            for (const u of urls) {
                try {
                    const r = await fetch(u, {
                        headers: {
                            "accept": "application/json",
                            "csrf-token": csrf,
                            "x-restli-protocol-version": "2.0.0",
                        },
                        credentials: "include",
                    });
                    out.push(r.ok ? await r.json() : null);
                } catch (e) { out.push(null); }
                await new Promise(res => setTimeout(res, delayMs));
            }
            return out;
        }""",
        [urls, csrf, delay_ms],
    )


def _collect_ids_from_pages(page, max_pages: int = 50, settle_ms: int = 2500) -> list[str]:
    """Page through the tracker, clicking 'Next', collecting job IDs in order."""
    ids = []
    for page_num in range(1, max_pages + 1):
        page.wait_for_timeout(settle_ms)
        before = len(ids)
        for jid in _extract_ids(page.content()):
            if jid not in ids:
                ids.append(jid)
        print(f"    page {page_num}: {len(ids)} jobs collected so far")

        nxt = _find_next_button(page)
        if nxt is None:
            break
        try:
            nxt.scroll_into_view_if_needed(timeout=5000)
            nxt.click(timeout=5000)
        except Exception:
            break
        page.wait_for_timeout(settle_ms)
        # Stop if a page reveals nothing new (avoids spinning on a stuck Next).
        if len(ids) == before and not (set(_extract_ids(page.content())) - set(ids)):
            break
    return ids


def _find_next_button(page):
    """Return a clickable, enabled pagination 'Next' button, or None."""
    selectors = [
        "button:has-text('Next')",
        "a:has-text('Next')",
        "button[aria-label*='Next' i]",
        "[aria-label='Next']",
    ]
    for sel in selectors:
        loc = page.locator(sel).last
        try:
            if loc.count() and loc.is_visible() and loc.is_enabled():
                return loc
        except Exception:
            continue
    return None
