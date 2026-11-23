"""Options-flow contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from custom_components.kr_public_data import config_flow
from custom_components.kr_public_data.config_flow import KRPublicDataOptionsFlow
from custom_components.kr_public_data.const import (
    CONF_ENTRY_TYPE,
    ENTRY_BUS,
    ENTRY_FUEL,
    ENTRY_KEPCO,
    ENTRY_PHARMACY,
    ENTRY_TRANSIT,
)


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


def _submit(data, user_input, step="async_step_init", **validators):
    flow, written = _flow(data)
    mocks = {name: AsyncMock(return_value=value) for name, value in validators.items()}
    with patch.multiple(config_flow, **mocks):
        result = asyncio.run(getattr(flow, step)(user_input))
    return result, written, mocks


def test_changed_api_key_is_validated_before_saving():
    result, written, mocks = _submit(
        {CONF_ENTRY_TYPE: ENTRY_BUS, "api_key": "old"}, {"api_key": "typo"},
        _validate_api_key=False)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    assert not written
    mocks["_validate_api_key"].assert_awaited_once()


def test_unchanged_legacy_key_is_not_revalidated():
    # Pre-rename bus entries hold service_key; the form shows it as api_key.
    result, written, mocks = _submit(
        {CONF_ENTRY_TYPE: ENTRY_BUS, "service_key": "k"}, {"api_key": "k"},
        _validate_api_key=False)
    assert result["type"] == "create_entry"
    assert written["api_key"] == "k"
    mocks["_validate_api_key"].assert_not_awaited()


def test_emptied_optional_key_is_not_validated():
    result, _, mocks = _submit(
        {CONF_ENTRY_TYPE: ENTRY_TRANSIT, "seoul_api_key": "k"}, {"seoul_api_key": ""},
        _validate_api_key=False)
    assert result["type"] == "create_entry"
    mocks["_validate_api_key"].assert_not_awaited()


def test_changed_kepco_password_reports_validator_error():
    result, written, _ = _submit(
        {CONF_ENTRY_TYPE: ENTRY_KEPCO, "username": "u", "password": "p"},
        {"username": "u", "password": "wrong"}, _validate_kepco="invalid_auth")
    assert result["errors"] == {"base": "invalid_auth"}
    assert not written


def test_pharmacy_key_change_is_validated():
    result, written, _ = _submit(
        {CONF_ENTRY_TYPE: ENTRY_PHARMACY, "api_key": "old", "regions": []},
        {"api_key": "typo"}, step="async_step_pharmacy_options", _validate_api_key=False)
    assert result["step_id"] == "pharmacy_options"
    assert result["errors"] == {"base": "cannot_connect"}
    assert not written
