"""ResilientCoordinator contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from custom_components.kr_public_data import resilience


def _coord(entry_id, title):
    return SimpleNamespace(hass=None, name="airkorea", _quota_issue_active=False,
                           config_entry=SimpleNamespace(entry_id=entry_id, title=title))


def test_quota_issues_are_scoped_per_entry():
    a, b = _coord("A", "에어코리아"), _coord("B", "에어코리아 2")
    with patch.object(resilience.ir, "async_create_issue") as create, \
            patch.object(resilience.ir, "async_delete_issue") as delete:
        resilience.ResilientCoordinator._set_quota_issue(a, True)
        resilience.ResilientCoordinator._set_quota_issue(b, True)
        resilience.ResilientCoordinator._set_quota_issue(b, False)
    created = [c.args[2] for c in create.call_args_list]
    assert created == ["quota_exceeded_A_airkorea", "quota_exceeded_B_airkorea"]
    # B recovering only clears B's issue.
    assert [c.args[2] for c in delete.call_args_list] == ["quota_exceeded_B_airkorea"]
    assert create.call_args_list[1].kwargs["translation_placeholders"] == {
        "name": "에어코리아 2 (airkorea)"}
