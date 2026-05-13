"""URL discovery — the cornerstone of webpull.

Mirrors webpull/src/discover.ts strategies:
    1. Resolve the base URL (follow redirects).
    2. SPA shell?
        - Hash-router? Render once, extract `href="#..."`.
        - JS bundles? Scrape `path:/to:/href:` strings from each bundle.
        - Otherwise render the page and extract nav links.
    3. Static site?
        - robots.txt sitemap lines.
        - /sitemap.xml, /sitemap_index.xml, /sitemap-0.xml at both the
          resolved origin and the original origin.
        - Nav selectors (nav, aside, [class*="sidebar"], etc.).
        - BFS crawl as the last resort.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from superton.puller import routes
from superton.puller.detect import is_spa_shell
from superton.puller.ua import get_headers

logger = logging.getLogger(__name__)

_IGNORED = re.compile(
    r"\.(png|jpg|jpeg|gif|svg|webp|ico|pdf|zip|tar|gz|"
    r"mp4|mp3|woff2?|ttf|eot|css|js|json|xml|rss|atom)$",
    re.IGNORECASE,
)

_NAV_SELECTORS = (
    "nav a[href]",
    "aside a[href]",
    '[class*="sidebar"] a[href]',
    '[class*="Sidebar"] a[href]',
    '[class*="navigation"] a[href]',
    '[class*="toc"] a[href]',
    '[class*="menu"] a[href]',
    '[role="navigation"] a[href]',
)

_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"""href=["'](.*?)["']""", re.IGNORECASE)


# --- Scoping --------------------------------------------------------------


def _get_scope_path(pathname: str) -> str:
    """Match webpull's getScopePath — keep the crawl inside the subtree
    the user asked for."""
    if pathname == "/":
        return "/"
    if re.search(r"\.\w+$", pathname):
        return re.sub(r"/[^/]*$", "/", pathname)
    if pathname.endswith("/"):
        return pathname
    segs = [s for s in pathname.split("/") if s]
    if len(segs) <= 1:
        return pathname
    return "/" + "/".join(segs[:-1]) + "/"


def _apex(host: str) -> str:
    return re.sub(r"^www\.", "", host)


def _normalize_host(url: str, preferred_host: str) -> str:
    parsed = urlparse(url)
    if _apex(parsed.hostname or "") == _apex(preferred_host):
        parsed = parsed._replace(netloc=preferred_host + (f":{parsed.port}" if parsed.port else ""))
    return urlunparse(parsed)


def _filter_and_dedupe(
    urls: list[str],
    hosts: set[str],
    scope: str,
    max_pages: int,
    preferred_host: str | None = None,
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        try:
            if preferred_host:
                raw = _normalize_host(raw, preferred_host)
            u = urlparse(raw)
            if not u.hostname or u.hostname not in hosts:
                continue
            if not u.path.startswith(scope):
                continue
            if _IGNORED.search(u.path):
                continue
            # strip query + fragment
            u = u._replace(query="", fragment="")
            if u.path in seen:
                continue
            seen.add(u.path)
            out.append(urlunparse(u))
        except Exception:
            continue
    return out[:max_pages]


# --- HTTP helpers ---------------------------------------------------------


async def _try_fetch(
    client: httpx.AsyncClient, url: str
) -> tuple[str, str] | None:
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        return (r.text, str(r.url))
    except Exception:
        return None


# --- Sitemap --------------------------------------------------------------


async def _fetch_sitemap(
    client: httpx.AsyncClient, url: str, depth: int = 0
) -> list[str]:
    if depth > 3:
        return []
    fetched = await _try_fetch(client, url)
    if not fetched:
        return []
    text, _ = fetched
    if "<" not in text:
        return []
    locs = [m.group(1).strip() for m in _LOC_RE.finditer(text)]
    is_index = "<sitemapindex" in text or ("<sitemap>" in text and "<urlset" not in text)
    if is_index:
        nested = await asyncio.gather(
            *(_fetch_sitemap(client, u, depth + 1) for u in locs),
            return_exceptions=True,
        )
        out: list[str] = []
        for result in nested:
            if isinstance(result, list):
                out.extend(result)
        return out
    return locs


async def _sitemap_from_robots(client: httpx.AsyncClient, origin: str) -> list[str]:
    fetched = await _try_fetch(client, f"{origin}/robots.txt")
    if not fetched:
        return []
    text, _ = fetched
    low = text.lower()
    if "<!doctype" in low or "<html" in low:
        return []
    sitemap_urls = [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.lower().lstrip().startswith("sitemap:")
    ]
    if not sitemap_urls:
        return []
    results = await asyncio.gather(
        *(_fetch_sitemap(client, u) for u in sitemap_urls),
        return_exceptions=True,
    )
    out: list[str] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out


# --- Nav extraction -------------------------------------------------------


def _extract_nav(base: str, html: str) -> list[str]:
    """Equivalent of webpull's extractNav using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [base]

    parser = "lxml" if _has_lxml() else "html.parser"
    soup = BeautifulSoup(html, parser)
    urls: set[str] = {base}
    for sel in _NAV_SELECTORS:
        for link in soup.select(sel):
            href = link.get("href")
            if not href or not isinstance(href, str):
                continue
            if href.startswith(("#", "javascript:", "mailto:")):
                continue
            try:
                resolved = urljoin(base, href)
                p = urlparse(resolved)
                p = p._replace(query="", fragment="")
                if _IGNORED.search(p.path):
                    continue
                urls.add(urlunparse(p))
            except Exception:
                continue
    return sorted(urls)


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except ImportError:
        return False


def _extract_links(
    html: str, base: str, visited: set[str], scope: str
) -> list[str]:
    """Same-domain, same-scope link extraction for the BFS fallback."""
    base_parsed = urlparse(base)
    out: list[str] = []
    for m in _HREF_RE.finditer(html):
        try:
            r = urljoin(base, m.group(1))
            rp = urlparse(r)
            rp = rp._replace(query="", fragment="")
            href = urlunparse(rp)
            if rp.hostname != base_parsed.hostname:
                continue
            if not rp.path.startswith(scope):
                continue
            if _IGNORED.search(rp.path):
                continue
            if href in visited:
                continue
            out.append(href)
        except Exception:
            continue
    return list(dict.fromkeys(out))  # dedupe, preserve order


# --- BFS crawl ------------------------------------------------------------


async def _crawl(
    client: httpx.AsyncClient, base: str, max_pages: int, scope: str
) -> list[str]:
    visited: set[str] = set()
    queue: list[str] = [base]
    found: list[str] = []
    base_parsed = urlparse(base)

    while queue and len(found) < max_pages:
        batch_size = min(20, max_pages - len(found))
        batch = [u for u in queue[:batch_size] if u not in visited]
        queue = queue[batch_size:]
        for u in batch:
            visited.add(u)

        results = await asyncio.gather(
            *(_try_fetch(client, u) for u in batch),
            return_exceptions=True,
        )
        for url, res in zip(batch, results, strict=False):
            _ = url
            if isinstance(res, Exception) or res is None:
                continue
            text, final_url = res
            if "</html" not in text:
                continue
            found.append(final_url)
            for link in _extract_links(text, base, visited, scope):
                if link in visited or len(found) + len(queue) >= max_pages:
                    continue
                queue.append(link)
    return found


# --- SPA discovery --------------------------------------------------------


async def _discover_spa(
    client: httpx.AsyncClient,
    base: str,
    html: str,
    max_pages: int,
    scope: str,
    hosts: set[str],
    render_js: bool,
) -> list[str]:
    """SPA-specific discovery: hash-router, JS bundle routes, or rendered nav."""
    base_parsed = urlparse(base)
    is_hash_router = bool(
        (base_parsed.fragment and len(base_parsed.fragment) > 1)
        or "HashRouter" in html
        or "createHashRouter" in html
        or "hash-router" in html
        or "#/page/" in html
    )

    if is_hash_router and render_js:
        full = f"{base_parsed.scheme}://{base_parsed.netloc}{base_parsed.path}"
        if base_parsed.fragment:
            full += f"#{base_parsed.fragment}"
        try:
            from superton.puller.renderer import launch_browser, render_page
        except Exception:
            return [full]
        try:
            await launch_browser()
            rendered = await render_page(full, timeout=20.0)
        except Exception:
            rendered = None
        if rendered is not None:
            hash_links: list[str] = []
            for m in re.finditer(r"""href=["'](#[^"'\s]+)["']""", rendered.html):
                frag = m.group(1)
                if frag and len(frag) > 1:
                    hash_links.append(
                        f"{base_parsed.scheme}://{base_parsed.netloc}"
                        f"{base_parsed.path}{frag}"
                    )
            deduped = list(dict.fromkeys(hash_links))
            if full not in deduped:
                deduped.insert(0, full)
            if deduped:
                return deduped[:max_pages]
            nav = _extract_nav(rendered.url, rendered.html)
            if len(nav) > 1:
                return nav[:max_pages]
        return [full]

    # Strategy 1 — parse JS bundles.
    js_urls = routes.extract_js_bundle_urls(html, base)
    if js_urls:
        route_urls = await routes.extract_routes_from_bundles(
            js_urls, base, scope, client=client
        )
        if route_urls:
            filtered = _filter_and_dedupe(route_urls, hosts, scope, max_pages)
            if filtered:
                return filtered

    # Strategy 2 — render once and extract nav.
    if render_js:
        try:
            from superton.puller.renderer import launch_browser, render_page
        except Exception:
            return [base]
        try:
            await launch_browser()
            rendered = await render_page(base)
        except Exception:
            rendered = None
        if rendered is not None:
            nav = _extract_nav(base, rendered.html)
            if len(nav) > 1:
                filtered = _filter_and_dedupe(nav, hosts, scope, max_pages)
                if filtered:
                    return filtered
            links = _extract_links(rendered.html, base, set(), scope)
            filtered = _filter_and_dedupe(links, hosts, scope, max_pages)
            if filtered:
                return filtered

    return [base]


# --- Public entry point ---------------------------------------------------


async def discover(
    base_url: str,
    max_pages: int,
    *,
    render_js: bool = False,
    timeout: float = 15.0,
) -> list[str]:
    """Return up to `max_pages` URLs to pull from a site."""
    async with httpx.AsyncClient(
        headers=get_headers(),
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        try:
            r = await client.get(base_url)
            r.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {base_url}: {e}") from e
        html = r.text
        actual = str(r.url)

        original = urlparse(base_url)
        actual_parsed = urlparse(actual)
        hosts = {original.hostname or "", actual_parsed.hostname or ""}
        hosts.discard("")
        scope = _get_scope_path(actual_parsed.path or "/")

        if is_spa_shell(html):
            spa_base = actual
            if original.fragment and not actual_parsed.fragment:
                spa_base = f"{actual}#{original.fragment}"
            return await _discover_spa(
                client, spa_base, html, max_pages, scope, hosts, render_js
            )

        origins = {
            f"{original.scheme}://{original.netloc}",
            f"{actual_parsed.scheme}://{actual_parsed.netloc}",
        }
        base_paths = {
            re.sub(r"/[^/]*$", "/", actual_parsed.path or "/"),
            "/",
        }

        strategies: list[asyncio.Future[list[str]] | asyncio.Task[list[str]]] = []
        for o in origins:
            strategies.append(asyncio.ensure_future(_sitemap_from_robots(client, o)))
            for bp in base_paths:
                for name in ("sitemap.xml", "sitemap_index.xml", "sitemap-0.xml"):
                    strategies.append(
                        asyncio.ensure_future(
                            _fetch_sitemap(client, f"{o}{bp}{name}")
                        )
                    )
        results = await asyncio.gather(*strategies, return_exceptions=True)

        best: list[str] = []
        for urls in results:
            if isinstance(urls, Exception) or not urls:
                continue
            for u in urls:
                try:
                    host = urlparse(u).hostname
                    if host:
                        hosts.add(host)
                except Exception:
                    continue
            filtered = _filter_and_dedupe(
                urls, hosts, scope, max_pages, actual_parsed.hostname
            )
            if len(filtered) > len(best):
                best = filtered
        if best:
            return best

        nav = _extract_nav(actual, html)
        if len(nav) > 5:
            filtered = _filter_and_dedupe(
                nav, hosts, scope, max_pages, actual_parsed.hostname
            )
            if filtered:
                return filtered

        return await _crawl(client, actual, max_pages, scope)
