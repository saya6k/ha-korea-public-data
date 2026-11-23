"""Options-flow contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.kr_public_data.config_flow import KRPublicDataOptionsFlow
from custom_components.kr_public_data.const import CONF_ENTRY_TYPE, ENTRY_FUEL


def _flow(data):
    """Options flow over a subentry-less entry; captures what it writes."""
    entry = SimpleNamespace(data=data, subentries={})
    written = {}

    def update_entry(_entry, *, data):
        written.update(data)

    flow = KRPublicDataOptionsFlow(entry)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=update_entry))
    return flow, written


def test_legacy_fuel_options_rewrite_configs():
    flow, written = _flow({CONF_ENTRY_TYPE: ENTRY_FUEL, "opinet_api_key": "k",
                           "configs": [{"sido_code": "01", "fuel_code": "B027"}]})
    result = asyncio.run(flow.async_step_init({
        "opinet_api_key": "k", "sido_codes": ["01", "02"], "fuel_codes": ["D047"]}))
    assert result["type"] == "create_entry"
    # __init__.py builds coordinators from "configs" only.
    assert written["configs"] == [{"sido_code": "01", "fuel_code": "D047"},
                                  {"sido_code": "02", "fuel_code": "D047"}]
    assert "sido_codes" not in written
    assert "fuel_codes" not in written


def test_legacy_fuel_options_reject_empty_selection():
    flow, written = _flow({CONF_ENTRY_TYPE: ENTRY_FUEL, "opinet_api_key": "k",
                           "configs": [{"sido_code": "01", "fuel_code": "B027"}]})
    result = asyncio.run(flow.async_step_init({
        "opinet_api_key": "k", "sido_codes": [], "fuel_codes": ["D047"]}))
    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_selection"}
    assert not written


def test_oldest_fuel_entry_defaults_to_its_single_config():
    flow, _ = _flow({CONF_ENTRY_TYPE: ENTRY_FUEL, "api_key": "k",
                     "sido_code": "01", "fuel_code": "B027"})
    schema = asyncio.run(flow._build_schema(ENTRY_FUEL))
    defaults = {str(k): k.default() for k in schema.schema}
    assert defaults["sido_codes"] == ["01"]
    assert defaults["fuel_codes"] == ["B027"]
