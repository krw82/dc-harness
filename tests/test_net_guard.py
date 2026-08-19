import pytest

from dc_harness.net.guard import DC_HOSTS, UnsafeUrlError, host_is_public, validate_http_url


def test_allows_dc_hosts():
    assert validate_http_url("https://gall.dcinside.com/board/lists/?id=crypto", DC_HOSTS)


def test_rejects_non_allowlisted_host_for_dc():
    with pytest.raises(UnsafeUrlError):
        validate_http_url("https://evil.example.com/lists?id=crypto", DC_HOSTS)


@pytest.mark.parametrize("scheme", ["file", "ftp", "javascript"])
def test_rejects_non_http_schemes(scheme: str):
    with pytest.raises(UnsafeUrlError):
        validate_http_url(f"{scheme}://gall.dcinside.com/x", DC_HOSTS)


def test_rejects_private_or_loopback_when_no_allowlist():
    with pytest.raises(UnsafeUrlError):
        validate_http_url("http://127.0.0.1:8080/api")
    with pytest.raises(UnsafeUrlError):
        validate_http_url("http://192.168.1.5/api")


def test_host_is_public_ip_literals():
    assert host_is_public("93.184.216.34") is True
    assert host_is_public("127.0.0.1") is False
    assert host_is_public("10.0.0.1") is False
    assert host_is_public("169.254.1.1") is False
