import requests


def load_netscape_cookies(path: str) -> dict[str, str]:
    cookies = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                cookies[name] = value.strip('"')
    return cookies


def build_session(cookies_path: str) -> tuple[requests.Session, str]:
    cookies = load_netscape_cookies(cookies_path)
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "x-restli-protocol-version": "2.0.0",
        "x-li-lang": "en_US",
    })
    csrf = cookies.get("JSESSIONID", "")
    session.headers["csrf-token"] = csrf
    return session, csrf
