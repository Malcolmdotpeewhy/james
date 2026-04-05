"""
JAMES Web Intelligence — Browsing, scraping, and content extraction tools.

Provides the AI with the ability to:
- Browse web pages and extract clean readable text
- Scrape structured data (links, images, tables, metadata)
- Search the web via DuckDuckGo (no API key)
- Crawl multi-page sites
- Extract and follow sitemaps
- Monitor pages for changes
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, quote_plus

logger = logging.getLogger("james.tools.web")

# ── Constants ─────────────────────────────────────────────────────

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_DEFAULT_TIMEOUT = 20
_MAX_BODY = 100_000  # Max chars to return in body


# ══════════════════════════════════════════════════════════════════
# CORE HTTP HELPERS
# ══════════════════════════════════════════════════════════════════

def _fetch(url: str, headers: dict = None, timeout: int = _DEFAULT_TIMEOUT,
           method: str = "GET", data: bytes = None) -> dict:
    """
    Fetch a URL and return response metadata + body.
    Handles redirects, encoding detection, error codes.
    """
    hdrs = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "identity",
    }
    hdrs.update(headers or {})

    req = urllib_request.Request(url, headers=hdrs, data=data, method=method)

    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # Detect encoding
            content_type = resp.headers.get("Content-Type", "")
            encoding = "utf-8"
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()

            try:
                body = raw.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                body = raw.decode("utf-8", errors="replace")

            return {
                "url": resp.url,
                "status": resp.status,
                "headers": dict(resp.headers),
                "content_type": content_type,
                "body": body,
                "length": len(body),
                "encoding": encoding,
            }
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:5000]
        except Exception:
            pass
        return {"url": url, "status": e.code, "error": str(e), "body": body}
    except URLError as e:
        return {"url": url, "status": 0, "error": str(e)}
    except Exception as e:
        return {"url": url, "status": 0, "error": str(e)}


def _get_soup(html: str):
    """Parse HTML with BeautifulSoup. Falls back to basic regex if BS4 unavailable."""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "lxml")
    except ImportError:
        try:
            from bs4 import BeautifulSoup
            return BeautifulSoup(html, "html.parser")
        except ImportError:
            return None


# ══════════════════════════════════════════════════════════════════
# WEB TOOL IMPLEMENTATIONS
# ══════════════════════════════════════════════════════════════════

def web_browse(url: str, extract: str = "text") -> dict:
    """
    Browse a web page and extract content.

    Args:
        url: Page URL to browse
        extract: What to extract — "text" (clean readable), "html" (raw),
                 "all" (text + links + images + meta)

    Returns:
        Dict with page content, title, and metadata.
    """
    resp = _fetch(url)
    if resp.get("error") and resp.get("status", 0) == 0:
        return resp

    html = resp.get("body", "")
    result = {
        "url": resp.get("url", url),
        "status": resp.get("status"),
        "content_type": resp.get("content_type", ""),
    }

    soup = _get_soup(html)
    if soup:
        # Title
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else ""

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            result["description"] = meta_desc.get("content", "")

        # Meta keywords
        meta_kw = soup.find("meta", attrs={"name": "keywords"})
        if meta_kw:
            result["keywords"] = meta_kw.get("content", "")

        # Open Graph
        og_tags = {}
        for og in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
            og_tags[og.get("property", "")] = og.get("content", "")
        if og_tags:
            result["opengraph"] = og_tags

        if extract in ("text", "all"):
            # Remove script, style, nav, footer — noise
            for tag in soup.find_all(["script", "style", "nav", "footer", "header",
                                       "aside", "noscript", "iframe"]):
                tag.decompose()

            # Get clean text
            text = soup.get_text(separator="\n", strip=True)
            # Collapse blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            result["text"] = text[:_MAX_BODY]
            result["text_length"] = len(text)

        if extract in ("all",):
            # Links
            links = []
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a["href"])
                link_text = a.get_text(strip=True)[:100]
                if href.startswith(("http://", "https://")):
                    links.append({"url": href, "text": link_text})
            result["links"] = links[:100]
            result["link_count"] = len(links)

            # Images
            images = []
            for img in soup.find_all("img", src=True):
                src = urljoin(url, img["src"])
                alt = img.get("alt", "")[:100]
                images.append({"src": src, "alt": alt})
            result["images"] = images[:50]

            # Headings
            headings = []
            for level in range(1, 7):
                for h in soup.find_all(f"h{level}"):
                    headings.append({"level": level, "text": h.get_text(strip=True)[:200]})
            result["headings"] = headings[:50]

    else:
        # Fallback: regex-based extraction
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        result["title"] = title_match.group(1).strip() if title_match else ""

        # Strip tags for text
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        result["text"] = text[:_MAX_BODY]

    if extract == "html":
        result["html"] = html[:_MAX_BODY]

    return result


def web_search(query: str, count: int = 10) -> list:
    """
    Search the web using DuckDuckGo HTML (no API key needed).

    Args:
        query: Search query string
        count: Max results to return

    Returns:
        List of search results with title, url, snippet.
    """
    encoded_q = quote_plus(query)
    search_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"

    resp = _fetch(search_url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/html",
    })

    if resp.get("error") and resp.get("status", 0) == 0:
        return [{"error": resp["error"]}]

    html = resp.get("body", "")
    results = []

    soup = _get_soup(html)
    if soup:
        for item in soup.find_all("div", class_="result"):
            title_tag = item.find("a", class_="result__a")
            snippet_tag = item.find("a", class_="result__snippet")

            if title_tag:
                href = title_tag.get("href", "")
                # DuckDuckGo wraps URLs in redirect
                if "uddg=" in href:
                    from urllib.parse import unquote
                    href = unquote(href.split("uddg=")[-1].split("&")[0])

                results.append({
                    "title": title_tag.get_text(strip=True),
                    "url": href,
                    "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
                })

                if len(results) >= count:
                    break
    else:
        # Regex fallback
        for m in re.finditer(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            href, title = m.groups()
            title = re.sub(r"<[^>]+>", "", title).strip()
            if "uddg=" in href:
                from urllib.parse import unquote
                href = unquote(href.split("uddg=")[-1].split("&")[0])
            results.append({"title": title, "url": href, "snippet": ""})
            if len(results) >= count:
                break

    if not results:
        # Try alternate parsing for zero-click results
        return [{"info": "No results found or DuckDuckGo layout changed", "query": query}]

    return results


def web_extract_links(url: str, filter_domain: str = None) -> dict:
    """
    Extract all links from a web page.

    Args:
        url: Page URL
        filter_domain: Only return links matching this domain (optional)

    Returns:
        Dict with internal_links, external_links, and totals.
    """
    resp = _fetch(url)
    if resp.get("error") and resp.get("status", 0) == 0:
        return resp

    html = resp.get("body", "")
    parsed_url = urlparse(url)
    base_domain = parsed_url.netloc

    internal = []
    external = []

    soup = _get_soup(html)
    if soup:
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            link_text = a.get_text(strip=True)[:100]
            parsed_href = urlparse(href)

            if not parsed_href.scheme.startswith("http"):
                continue

            entry = {"url": href, "text": link_text}

            if parsed_href.netloc == base_domain:
                internal.append(entry)
            else:
                if filter_domain and filter_domain.lower() not in parsed_href.netloc.lower():
                    continue
                external.append(entry)
    else:
        for m in re.finditer(r'href="(https?://[^"]+)"', html):
            href = m.group(1)
            parsed_href = urlparse(href)
            entry = {"url": href, "text": ""}
            if parsed_href.netloc == base_domain:
                internal.append(entry)
            else:
                external.append(entry)

    return {
        "url": url,
        "domain": base_domain,
        "internal_links": internal[:100],
        "external_links": external[:100],
        "internal_count": len(internal),
        "external_count": len(external),
        "total": len(internal) + len(external),
    }


def web_extract_tables(url: str) -> list:
    """
    Extract HTML tables from a web page as structured data.

    Args:
        url: Page URL

    Returns:
        List of tables, each as a list of row-dicts.
    """
    resp = _fetch(url)
    if resp.get("error") and resp.get("status", 0) == 0:
        return [resp]

    html = resp.get("body", "")
    tables = []

    soup = _get_soup(html)
    if soup:
        for table in soup.find_all("table"):
            rows = []
            headers = []

            # Get headers
            thead = table.find("thead")
            if thead:
                for th in thead.find_all(["th", "td"]):
                    headers.append(th.get_text(strip=True))

            # If no thead, check first row
            if not headers:
                first_row = table.find("tr")
                if first_row:
                    ths = first_row.find_all("th")
                    if ths:
                        headers = [th.get_text(strip=True) for th in ths]

            # Get rows
            tbody = table.find("tbody") or table
            for tr in tbody.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    if headers and len(cells) == len(headers):
                        rows.append(dict(zip(headers, cells)))
                    else:
                        rows.append(cells)

            if rows:
                tables.append({
                    "headers": headers,
                    "rows": rows[:100],
                    "row_count": len(rows),
                })
    else:
        return [{"error": "BeautifulSoup not available — install beautifulsoup4 for table extraction"}]

    return tables if tables else [{"info": "No tables found on page"}]


def web_extract_metadata(url: str) -> dict:
    """
    Extract comprehensive metadata from a page (meta tags, Open Graph, Twitter cards, schema.org).

    Args:
        url: Page URL

    Returns:
        Dict with all extracted metadata.
    """
    resp = _fetch(url)
    if resp.get("error") and resp.get("status", 0) == 0:
        return resp

    html = resp.get("body", "")
    meta = {
        "url": resp.get("url", url),
        "status": resp.get("status"),
        "response_headers": {},
    }

    # Key response headers
    for key in ["Server", "X-Powered-By", "Content-Type", "X-Frame-Options",
                 "Strict-Transport-Security", "Content-Security-Policy"]:
        val = resp.get("headers", {}).get(key)
        if val:
            meta["response_headers"][key] = val

    soup = _get_soup(html)
    if soup:
        # Title
        title = soup.find("title")
        meta["title"] = title.get_text(strip=True) if title else ""

        # All meta tags
        standard_meta = {}
        og_meta = {}
        twitter_meta = {}

        for tag in soup.find_all("meta"):
            name = tag.get("name", "").lower()
            prop = tag.get("property", "").lower()
            content = tag.get("content", "")

            if name:
                standard_meta[name] = content
            if prop.startswith("og:"):
                og_meta[prop] = content
            if name.startswith("twitter:") or prop.startswith("twitter:"):
                twitter_meta[name or prop] = content

        meta["meta_tags"] = standard_meta
        meta["opengraph"] = og_meta
        meta["twitter_card"] = twitter_meta

        # Canonical URL
        canonical = soup.find("link", rel="canonical")
        if canonical:
            meta["canonical"] = canonical.get("href", "")

        # Favicon
        icon = soup.find("link", rel=re.compile(r"icon", re.I))
        if icon:
            meta["favicon"] = urljoin(url, icon.get("href", ""))

        # JSON-LD (Schema.org)
        json_ld = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                json_ld.append(json.loads(script.string))
            except Exception:
                pass
        if json_ld:
            meta["schema_org"] = json_ld

        # RSS/Atom feeds
        feeds = []
        for link in soup.find_all("link", type=re.compile(r"(rss|atom)", re.I)):
            feeds.append({
                "type": link.get("type", ""),
                "title": link.get("title", ""),
                "url": urljoin(url, link.get("href", "")),
            })
        if feeds:
            meta["feeds"] = feeds

    return meta


def web_crawl(start_url: str, max_pages: int = 10, same_domain: bool = True,
              depth: int = 2) -> dict:
    """
    Crawl a website starting from a URL.

    Args:
        start_url: Starting URL
        max_pages: Maximum pages to crawl
        same_domain: Only follow links on the same domain
        depth: Maximum link-following depth

    Returns:
        Dict with crawled pages, sitemap, and statistics.
    """
    parsed_start = urlparse(start_url)
    base_domain = parsed_start.netloc

    visited = set()
    queue = [(start_url, 0)]  # (url, depth)
    pages = []
    errors = []

    while queue and len(pages) < max_pages:
        current_url, current_depth = queue.pop(0)

        # Normalize URL
        parsed = urlparse(current_url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized in visited:
            continue
        visited.add(normalized)

        # Only same domain if flag is set
        if same_domain and parsed.netloc != base_domain:
            continue

        # Fetch page
        resp = _fetch(current_url, timeout=15)
        if resp.get("error") and resp.get("status", 0) == 0:
            errors.append({"url": current_url, "error": resp["error"]})
            continue

        content_type = resp.get("content_type", "")
        if "text/html" not in content_type:
            continue

        html = resp.get("body", "")
        soup = _get_soup(html)

        page_data = {
            "url": resp.get("url", current_url),
            "status": resp.get("status"),
            "depth": current_depth,
        }

        if soup:
            title = soup.find("title")
            page_data["title"] = title.get_text(strip=True) if title else ""

            # Count content
            for tag in soup.find_all(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text(strip=True)
            page_data["word_count"] = len(text.split())

            # ⚡ Bolt: Cache DOM query for links to prevent redundant O(N) traversals
            # Extract links for further crawling
            links = soup.find_all("a", href=True)
            page_data["links_found"] = len(links)
            if current_depth < depth:
                for a in links:
                    href = urljoin(current_url, a["href"])
                    p = urlparse(href)
                    # Skip non-HTTP, anchors, query strings
                    if not p.scheme.startswith("http"):
                        continue
                    clean = f"{p.scheme}://{p.netloc}{p.path}"
                    if clean not in visited:
                        queue.append((clean, current_depth + 1))

        pages.append(page_data)
        logger.info(f"  Crawled: {current_url} ({len(pages)}/{max_pages})")

    return {
        "start_url": start_url,
        "domain": base_domain,
        "pages_crawled": len(pages),
        "pages": pages,
        "errors": errors,
        "urls_discovered": len(visited),
    }


def web_get_headers(url: str) -> dict:
    """
    Get HTTP response headers for a URL (HEAD request).

    Args:
        url: Target URL

    Returns:
        Dict with status code and all response headers.
    """
    hdrs = {"User-Agent": _USER_AGENT}
    req = urllib_request.Request(url, headers=hdrs, method="HEAD")

    try:
        with urllib_request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
            return {
                "url": resp.url,
                "status": resp.status,
                "headers": dict(resp.headers),
            }
    except HTTPError as e:
        return {"url": url, "status": e.code, "headers": dict(e.headers)}
    except Exception as e:
        return {"url": url, "error": str(e)}


def web_check_status(urls: list) -> list:
    """
    Check HTTP status codes for multiple URLs (fast batch check).

    Args:
        urls: List of URLs to check

    Returns:
        List of status results.
    """
    results = []
    for url in urls[:20]:  # Cap at 20
        try:
            req = urllib_request.Request(url, headers={"User-Agent": _USER_AGENT}, method="HEAD")
            with urllib_request.urlopen(req, timeout=10) as resp:
                results.append({"url": url, "status": resp.status, "ok": True})
        except HTTPError as e:
            results.append({"url": url, "status": e.code, "ok": False})
        except Exception as e:
            results.append({"url": url, "status": 0, "ok": False, "error": str(e)})
    return results


def web_screenshot(url: str, output: str = None, width: int = 1280, height: int = 720) -> dict:
    """
    Take a screenshot of a web page (requires Playwright).
    Falls back to a text-based representation if Playwright is unavailable.

    Args:
        url: Page URL
        output: Output file path (auto-generated if not provided)
        width: Viewport width
        height: Viewport height

    Returns:
        Dict with screenshot path or text representation.
    """
    try:
        from playwright.sync_api import sync_playwright
        if not output:
            safe_name = re.sub(r"[^\w]", "_", urlparse(url).netloc)[:30]
            output = os.path.join(os.environ.get("TEMP", "."), f"screenshot_{safe_name}.png")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.screenshot(path=output, full_page=False)
            title = page.title()
            browser.close()

        return {
            "url": url,
            "screenshot": output,
            "size": os.path.getsize(output),
            "title": title,
            "method": "playwright",
        }
    except ImportError:
        # Fallback: return text representation
        resp = web_browse(url, extract="text")
        return {
            "url": url,
            "error": "Playwright not installed. Use 'pip install playwright && playwright install chromium' for screenshots.",
            "title": resp.get("title", ""),
            "text_preview": resp.get("text", "")[:2000],
            "method": "text_fallback",
        }
    except Exception as e:
        return {"url": url, "error": str(e)}


def web_parse_sitemap(url: str) -> dict:
    """
    Parse a sitemap.xml and extract all URLs.

    Args:
        url: Sitemap URL (or site root — will try /sitemap.xml)

    Returns:
        Dict with list of URLs from the sitemap.
    """
    # Try direct URL first, then /sitemap.xml
    sitemap_url = url
    if not url.endswith(".xml"):
        parsed = urlparse(url)
        sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    resp = _fetch(sitemap_url)
    if resp.get("status") != 200:
        # Try robots.txt for sitemap reference
        robots_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}/robots.txt"
        robots_resp = _fetch(robots_url)
        if robots_resp.get("status") == 200:
            body = robots_resp.get("body", "")
            sitemap_matches = re.findall(r"Sitemap:\s*(.+)", body, re.IGNORECASE)
            if sitemap_matches:
                sitemap_url = sitemap_matches[0].strip()
                resp = _fetch(sitemap_url)

    if resp.get("status") != 200:
        return {"error": f"Could not fetch sitemap from {sitemap_url}", "status": resp.get("status")}

    body = resp.get("body", "")
    urls = []

    # Parse XML
    soup = _get_soup(body)
    if soup:
        for loc in soup.find_all("loc"):
            urls.append(loc.get_text(strip=True))
    else:
        # Regex fallback
        urls = re.findall(r"<loc>(.*?)</loc>", body)

    return {
        "sitemap_url": sitemap_url,
        "urls": urls[:500],
        "total_urls": len(urls),
    }


def web_page_diff(url: str, previous_hash: str = None) -> dict:
    """
    Check if a web page has changed since last visit.

    Args:
        url: Page URL
        previous_hash: Hash from a previous call (for comparison)

    Returns:
        Dict with current hash, change status, and content snapshot.
    """
    resp = _fetch(url)
    if resp.get("error") and resp.get("status", 0) == 0:
        return resp

    html = resp.get("body", "")
    soup = _get_soup(html)

    # Get meaningful content (skip scripts, styles)
    if soup:
        for tag in soup.find_all(["script", "style", "nav"]):
            tag.decompose()
        content = soup.get_text(strip=True)
    else:
        content = re.sub(r"<[^>]+>", "", html)

    current_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    result = {
        "url": url,
        "hash": current_hash,
        "timestamp": datetime.now().isoformat(),
        "content_length": len(content),
    }

    if previous_hash:
        result["changed"] = current_hash != previous_hash
        result["previous_hash"] = previous_hash
    else:
        result["changed"] = None  # No previous to compare

    return result


def web_read_article(url: str) -> dict:
    """
    Extract the main article/content from a page (reader mode).
    Strips navigation, ads, sidebars — returns just the core content.

    Args:
        url: Article URL

    Returns:
        Dict with title, author, date, and clean article text.
    """
    resp = _fetch(url)
    if resp.get("error") and resp.get("status", 0) == 0:
        return resp

    html = resp.get("body", "")
    soup = _get_soup(html)

    if not soup:
        return {"error": "BeautifulSoup required for article extraction"}

    article = {
        "url": resp.get("url", url),
        "status": resp.get("status"),
    }

    # Title
    title = soup.find("title")
    article["title"] = title.get_text(strip=True) if title else ""

    # Try h1 as title
    h1 = soup.find("h1")
    if h1:
        article["headline"] = h1.get_text(strip=True)

    # Author
    author_meta = (
        soup.find("meta", attrs={"name": "author"}) or
        soup.find("meta", attrs={"property": "article:author"})
    )
    if author_meta:
        article["author"] = author_meta.get("content", "")

    # Published date
    date_meta = (
        soup.find("meta", attrs={"property": "article:published_time"}) or
        soup.find("meta", attrs={"name": "publication_date"}) or
        soup.find("time")
    )
    if date_meta:
        article["published"] = date_meta.get("content", "") or date_meta.get("datetime", "") or date_meta.get_text(strip=True)

    # Find the main content area
    # Priority: <article>, <main>, role="main", class containing "content"/"article"
    content_el = (
        soup.find("article") or
        soup.find("main") or
        soup.find(attrs={"role": "main"}) or
        soup.find(class_=re.compile(r"(article|content|post|entry)[-_]?(body|content|text)?", re.I))
    )

    if not content_el:
        content_el = soup.find("body") or soup

    # Remove noise from content area
    for tag in content_el.find_all(["script", "style", "nav", "footer", "header",
                                     "aside", "iframe", "form", "noscript"]):
        tag.decompose()

    # Also remove elements with common ad/sidebar classes
    for tag in content_el.find_all(class_=re.compile(
        r"(sidebar|widget|ad[s-]|banner|social|share|comment|related|popup|modal|menu|nav)",
        re.I
    )):
        tag.decompose()

    # Extract paragraphs
    paragraphs = []
    for p in content_el.find_all(["p", "h2", "h3", "h4", "blockquote", "li"]):
        text = p.get_text(strip=True)
        if len(text) > 20:  # Skip tiny fragments
            tag_name = p.name
            if tag_name.startswith("h"):
                paragraphs.append(f"\n## {text}\n")
            elif tag_name == "blockquote":
                paragraphs.append(f"> {text}")
            elif tag_name == "li":
                paragraphs.append(f"• {text}")
            else:
                paragraphs.append(text)

    article["content"] = "\n\n".join(paragraphs)[:_MAX_BODY]
    article["word_count"] = len(article["content"].split())

    return article


# ══════════════════════════════════════════════════════════════════
# REGISTRATION (called from registry.py)
# ══════════════════════════════════════════════════════════════════

def register_web_tools(registry):
    """Register all web tools with the tool registry."""

    registry.register("web_browse", web_browse,
        "Browse a web page and extract clean readable text, links, images, and metadata",
        {"url": "page URL", "extract": "text|html|all"})

    registry.register("web_search", web_search,
        "Search the web using DuckDuckGo — returns titles, URLs, and snippets",
        {"query": "search query", "count": "max results (default 10)"})

    registry.register("web_extract_links", web_extract_links,
        "Extract all links from a web page (internal + external)",
        {"url": "page URL", "filter_domain": "optional domain filter"})

    registry.register("web_extract_tables", web_extract_tables,
        "Extract HTML tables from a page as structured data (rows/columns)",
        {"url": "page URL"})

    registry.register("web_extract_metadata", web_extract_metadata,
        "Extract page metadata: Open Graph, Twitter Cards, Schema.org, meta tags",
        {"url": "page URL"})

    registry.register("web_crawl", web_crawl,
        "Crawl a website from a starting URL, following links up to a depth limit",
        {"start_url": "starting page", "max_pages": "limit (default 10)", "depth": "max depth"})

    registry.register("web_get_headers", web_get_headers,
        "Get HTTP response headers for a URL (HEAD request)",
        {"url": "target URL"})

    registry.register("web_check_status", web_check_status,
        "Check HTTP status codes for multiple URLs in batch",
        {"urls": "list of URLs"})

    registry.register("web_screenshot", web_screenshot,
        "Take a screenshot of a web page (requires Playwright, falls back to text)",
        {"url": "page URL", "output": "output file path", "width": "viewport width"})

    registry.register("web_parse_sitemap", web_parse_sitemap,
        "Parse a sitemap.xml and extract all indexed URLs",
        {"url": "sitemap URL or site root"})

    registry.register("web_page_diff", web_page_diff,
        "Check if a web page has changed since last visit (hash comparison)",
        {"url": "page URL", "previous_hash": "hash from previous check"})

    registry.register("web_read_article", web_read_article,
        "Extract article content in reader mode — strips ads, nav, sidebars",
        {"url": "article URL"})
