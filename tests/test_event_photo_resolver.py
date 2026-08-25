from utils.event_photo import _absolute_image, _external_url, _official_image


def test_rejects_evenementen_and_ad_links():
    page = "https://evenementen.nl/events/test-event"
    assert _external_url("https://evenementen.nl/zoeken/festivals", page) is None
    assert _external_url("https://example.com/banner/aanbieding", page) is None
    assert _external_url("https://examplefestival.nl/", page) == "https://examplefestival.nl/"


def test_rejects_ad_product_image():
    assert _absolute_image("https://cdn.example.nl/shop/earplugs-banner.jpg", "https://festival.nl") is None


def test_prefers_official_og_image():
    html = '''
    <html><head>
      <meta property="og:image" content="/media/bernissepop-hero.jpg">
    </head><body></body></html>
    '''
    assert _official_image(html, "https://bernissepop.nl/", "BernissePoP 2026") == (
        "https://bernissepop.nl/media/bernissepop-hero.jpg"
    )
