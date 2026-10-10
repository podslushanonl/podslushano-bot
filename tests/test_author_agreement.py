from utils.authors_web import (
    AGREEMENT_DATE,
    AGREEMENT_SHA256,
    AGREEMENT_VERSION,
    _form_page,
)


def test_author_agreement_page_contains_operator_and_terms():
    page = _form_page()
    assert "Aleksei Maksimovich Egorov" in page
    assert "98882317" in page
    assert "NL005359099B74" in page
    assert "Karel Doormanstraat 63" in page
    assert "podslushano.nl@gmail.com" in page
    assert f"версия {AGREEMENT_VERSION}" in page
    assert AGREEMENT_DATE in page


def test_author_agreement_page_has_required_fields_and_acceptance():
    page = _form_page()
    for field in ("full_name", "city", "email", "telegram", "phone_model", "accept"):
        assert f'name="{field}"' in page
    assert "Принять условия и отправить анкету" in page
    assert AGREEMENT_SHA256[:12] in page
    assert "независимого участия" in page
    assert "каждая платная задача отдельно" in page
    assert "не означает автоматическое принятие" in page


def test_author_agreement_hash_is_sha256():
    assert len(AGREEMENT_SHA256) == 64
    int(AGREEMENT_SHA256, 16)
