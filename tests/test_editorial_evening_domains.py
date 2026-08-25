from utils.editorial_websearch_fix import EVENING_SOURCE_GROUPS


def test_evening_sources_do_not_include_known_inaccessible_domains():
    domains = {domain for group in EVENING_SOURCE_GROUPS for domain in group}
    assert "nu.nl" not in domains
