from utils.admin_channels import normalize_channel_reference


def test_normalize_channel_reference_accepts_id():
    assert normalize_channel_reference("-1001234567890") == -1001234567890


def test_normalize_channel_reference_accepts_username():
    assert normalize_channel_reference("@podslushano_test") == "@podslushano_test"
    assert normalize_channel_reference("podslushano_test") == "@podslushano_test"


def test_normalize_channel_reference_accepts_tme_link():
    assert (
        normalize_channel_reference("https://t.me/podslushano_test/123")
        == "@podslushano_test"
    )


def test_normalize_channel_reference_rejects_garbage():
    try:
        normalize_channel_reference("not a channel")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid reference must raise ValueError")


if __name__ == "__main__":
    test_normalize_channel_reference_accepts_id()
    test_normalize_channel_reference_accepts_username()
    test_normalize_channel_reference_accepts_tme_link()
    test_normalize_channel_reference_rejects_garbage()
    print("admin channel tests: ok")
