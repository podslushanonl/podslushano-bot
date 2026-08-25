from handlers.photo_refresh import PHOTO_VERSION


def test_photo_version_is_v2():
    assert PHOTO_VERSION == "official-photo-v2"
