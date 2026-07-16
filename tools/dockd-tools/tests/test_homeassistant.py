import pytest

from dockd_tools.homeassistant import HomeAssistant, HomeAssistantError, _base_url


def test_base_url_strips_accidental_api_endpoint():
    # The common paste error: the full REST endpoint in the url field.
    assert (
        _base_url("http://10.0.0.75:8123/api/services/scene/turn_on")
        == "http://10.0.0.75:8123"
    )


def test_base_url_leaves_plain_host_alone():
    assert _base_url("http://10.0.0.75:8123") == "http://10.0.0.75:8123"
    assert _base_url("http://10.0.0.75:8123/") == "http://10.0.0.75:8123"


def test_base_url_preserves_reverse_proxy_prefix():
    assert _base_url("http://ha.local/hass/api/services/scene/turn_on") == "http://ha.local/hass"


def test_base_url_adds_scheme_when_missing():
    assert _base_url("10.0.0.75:8123") == "http://10.0.0.75:8123"


def test_client_builds_single_api_path():
    ha = HomeAssistant("http://ha:8123/api/services/scene/turn_on", token="x")
    # base must not already contain the endpoint, or requests would 404.
    assert ha.base == "http://ha:8123"


def test_missing_token_raises():
    with pytest.raises(HomeAssistantError):
        HomeAssistant("http://ha:8123", token=None)
