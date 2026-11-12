"""Optional Playwright research bridge for local/cloud LLM context.

This is controlled retrieval, not an autonomous agent browser. The app performs
bounded searches and passes extracted page text to the model as untrusted context.
Catalog APIs and JAR metadata remain the compatibility authorities.
"""
from urllib.parse import quote, urlparse
import ipaddress
import socket


def _public_http_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal")):
        return False
    try:
        addresses = socket.getaddrinfo(host, None)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                return False
    except (OSError, ValueError):
        return False
    return True


def research(query, log=lambda message: None, max_pages=4):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Install requirements-browser.txt and run "
            "'python -m playwright install chromium'."
        ) from exc

    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(12000)
        try:
            search_url = "https://html.duckduckgo.com/html/?q=" + quote(query)
            page.goto(search_url, wait_until="domcontentloaded")
            links = page.locator("a.result__a")
            count = min(links.count(), max_pages * 2)
            candidates = []
            for index in range(count):
                link = links.nth(index)
                href = link.get_attribute("href")
                title = (link.inner_text() or "").strip()
                if href and title and _public_http_url(href):
                    candidates.append((title, href))
                if len(candidates) >= max_pages:
                    break

            for title, href in candidates:
                try:
                    page.goto(href, wait_until="domcontentloaded")
                    text = page.locator("body").inner_text(timeout=8000)
                    text = " ".join(text.split())[:2600]
                    if text:
                        results.append({"title": title, "url": href, "text": text})
                        log(f"Browser research read: {title}")
                except Exception as exc:
                    log(f"Browser research skipped {href}: {exc}")
        finally:
            browser.close()
    return results
