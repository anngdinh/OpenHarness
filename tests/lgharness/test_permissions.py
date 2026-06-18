from lgharness.permissions.checker import PermissionChecker
from lgharness.permissions.modes import PermissionMode


def test_read_only_always_allowed():
    for mode in PermissionMode:
        d = PermissionChecker(mode).evaluate("read_file")
        assert d.allowed is True
        assert d.requires_confirmation is False


def test_full_auto_allows_mutating():
    d = PermissionChecker(PermissionMode.FULL_AUTO).evaluate("write_file")
    assert d.allowed is True
    assert d.requires_confirmation is False


def test_default_mode_confirms_mutating():
    d = PermissionChecker(PermissionMode.DEFAULT).evaluate("bash")
    assert d.allowed is False
    assert d.requires_confirmation is True


def test_plan_mode_blocks_mutating_without_asking():
    d = PermissionChecker(PermissionMode.PLAN).evaluate("write_file")
    assert d.allowed is False
    assert d.requires_confirmation is False
