"""Tests for the superton.puller package."""
from superton.puller.detect import is_empty_content, is_spa_shell
from superton.puller.extractor import _extract_title, extract, frontmatter
from superton.puller.routes import extract_js_bundle_urls
from superton.puller.ua import get_headers, get_random_ua


def test_spa_detection_empty_shell():
    html = '<html><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>'
    assert is_spa_shell(html) is True


def test_spa_detection_real_content():
    html = '<html><body><main><h1>Hello</h1><p>' + 'x' * 300 + '</p></main></body></html>'
    assert is_spa_shell(html) is False


def test_is_empty_content():
    assert is_empty_content('   ') is True
    assert is_empty_content('short') is True
    assert is_empty_content('x' * 100) is False


def test_extract_title_from_html():
    assert _extract_title('<html><title>My Page</title><body></body></html>') == 'My Page'
    assert _extract_title('<html><body><h1>Heading</h1></body></html>') == 'Heading'
    assert _extract_title('<html><body>no title</body></html>') == ''


def test_frontmatter():
    fm = frontmatter('Hello World', 'https://example.com/page')
    assert 'title: "Hello World"' in fm
    assert 'url: "https://example.com/page"' in fm
    assert fm.startswith('---\n')
    assert fm.endswith('\n\n')


def test_extract_real_html():
    html = '<html><head><title>Test</title></head><body><main><h1>Test</h1><p>This is a paragraph with enough content to pass the minimum threshold for extraction.</p></main></body></html>'
    result = extract(html, url='https://example.com')
    assert result.title == 'Test'
    assert len(result.content) > 10


def test_extract_empty_html():
    result = extract('', url=None)
    assert result.title == ''
    assert result.content == ''


def test_ua_rotation():
    ua1 = get_random_ua()
    ua2 = get_random_ua()
    assert isinstance(ua1, str)
    assert len(ua1) > 20
    # They rotate (may or may not be different on consecutive calls)
    assert isinstance(ua2, str)


def test_get_headers():
    h = get_headers()
    assert 'User-Agent' in h
    assert 'Accept' in h
    assert 'Accept-Language' in h


def test_extract_js_bundle_urls():
    html = '<html><head><script src="/static/app.js"></script><script src="https://cdn.example.com/vendor.js"></script></head><body></body></html>'
    urls = extract_js_bundle_urls(html, 'https://example.com')
    assert 'https://example.com/static/app.js' in urls
    assert 'https://cdn.example.com/vendor.js' in urls


def test_extract_js_bundle_urls_empty():
    assert extract_js_bundle_urls('<html><body></body></html>', 'https://x.com') == []
