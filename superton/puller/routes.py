"""Extract routes from a site's JS bundles — port of webpull/src/routes.ts.

For SPAs that don't ship a sitemap, route tables are usually embedded in
the JavaScript. We regex-scrape `path: "/foo"`, `to: "/foo"`, and
`href: "/foo"` patterns from each bundle and filter for plausible content
pages (no wildcards, no /api/, no asset extensions).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from superton.puller.ua import get_headers

# Routes we should never emit: framework internals, dynamic placeholders,
# bundler outputs, etc.
_IGNORED_ROUTE_RE = re.compile(
    r"^/(?:api|_|\*|:|\.)|\.(?:js|css|json|ico|png|jpg|svg|woff)$",
    re.IGNORECASE,
)

_PATH_RE = re.compile(
    r"""path:\s*["'`](/[^"'`\s]{1,200})["'`]""",
)
_TO_RE = re.compile(
    r"""to[:=]\s*["'`](/[^"'`\s]{1,200})["'`]""",
)
_HREF_RE = re.compile(
    r"""href[:=]\s*["'`](/[^"'`\s]{1,200})["'`]""",
)
_SCRIPT_SRC_RE = re.compile(
    r"""src=["']([^"']*\.js)["']""",
    re.IGNORECASE,
)


def extract_js_bundle_urls(html: str, base: str) -> list[str]:
    """Return a list of resolved <script src="…"> URLs found in `html`."""
    out: list[str] = []
    for m in _SCRIPT_SRC_RE.finditer(html):
        try:
            out.append(urljoin(base, m.group(1)))
        except Exception:
            continue
    return out


def _paths_in_code(code: str) -> list[str]:
    paths: list[str] = []
    for rgx in (_PATH_RE, _TO_RE, _HREF_RE):
        for m in rgx.finditer(code):
            paths.append(m.group(1))
    return paths


async def extract_routes_from_bundles(
    js_urls: list[str],
    base: str,
    scope: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> list[str]:
    """Fetch every bundle and return the set of usable route URLs."""
    routes: set[str] = set()

    own_client = client is None
    http = client or httpx.AsyncClient(
        headers=get_headers(), follow_redirects=True, timeout=timeout
    )
    try:
        for js_url in js_urls:
            try:
                r = await http.get(js_url)
                if r.status_code != 200:
                    continue
                code = r.text
            except Exception:
                continue
            for path in _paths_in_code(code):
                if ":" in path or "*" in path:
                    continue
                if _IGNORED_ROUTE_RE.search(path):
                    continue
                if scope != "/" and not path.startswith(scope):
                    continue
                try:
                    full = urljoin(base, path)
                    # Normalize: strip fragment/query
                    parsed = urlparse(full)
                    clean = parsed._replace(query="", fragment="").geturl()
                    routes.add(clean)
                except Exception:
                    continue
    finally:
        if own_client:
            await http.aclose()
    return sorted(routes)
