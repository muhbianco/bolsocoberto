from __future__ import annotations

import pytest

from app.services.fetch import FetchError, assert_public_host, parse_http_url


def test_parse_rejects_non_http() -> None:
    with pytest.raises(FetchError):
        parse_http_url("ftp://example.com/x")


def test_parse_rejects_credentials() -> None:
    with pytest.raises(FetchError):
        parse_http_url("https://user:pass@example.com/")


def test_parse_accepts_https() -> None:
    assert parse_http_url("https://bolsocoberto.com.br/a") == "https://bolsocoberto.com.br/a"


def test_blocks_localhost() -> None:
    with pytest.raises(FetchError):
        assert_public_host("localhost")


def test_blocks_loopback_ip() -> None:
    with pytest.raises(FetchError):
        assert_public_host("127.0.0.1")


def test_blocks_rfc1918() -> None:
    with pytest.raises(FetchError):
        assert_public_host("10.0.0.8")
    with pytest.raises(FetchError):
        assert_public_host("192.168.1.1")
    with pytest.raises(FetchError):
        assert_public_host("169.254.169.254")
