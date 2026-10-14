import re

import pytest

from countjar import docs


@pytest.mark.parametrize("slug", [p[0] for p in docs.PAGES])
def test_docs_pages_render_with_seo(client, slug):
    resp = client.get(docs.url(slug))
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert f"<title>{docs.BY_SLUG[slug][2]}" in html
    assert '"@type": "TechArticle"' in html or '"TechArticle"' in html


def test_unknown_docs_page_is_404(client):
    assert client.get("/docs/nope").status_code == 404


def test_sitemap_lists_every_docs_page(client):
    xml = client.get("/sitemap.xml").get_data(as_text=True)
    for slug, *_ in docs.PAGES:
        assert f"https://countjar.test{docs.url(slug)}</loc>" in xml


def test_code_samples_are_shown_as_text_not_markup(client):
    html = client.get("/docs/widgets").get_data(as_text=True)
    assert '<div class="countjar"' not in html
    assert "&lt;div class=&#34;countjar&#34;" in html
    assert re.search(r'<script src="https://countjar\.test/embed\.js"', html) is None


def test_docs_internal_links_resolve(client):
    for slug, *_ in docs.PAGES:
        html = client.get(docs.url(slug)).get_data(as_text=True)
        for href in set(re.findall(r'href="(/docs[^"#]*)', html)):
            assert client.get(href).status_code == 200, (slug, href)


def test_docs_anchor_links_exist(client):
    pages = {docs.url(s): client.get(docs.url(s)).get_data(as_text=True) for s, *_ in docs.PAGES}
    for url, html in pages.items():
        for target, anchor in re.findall(r'href="(/docs[^"#]*)?#([\w-]+)"', html):
            assert f'id="{anchor}"' in pages[target or url], (url, target, anchor)
