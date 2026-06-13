from openharness.permissions.modes import PermissionMode
from openharness.permissions.checker import PermissionChecker

from domo.config import DomoConfig


def test_defaults():
    c = DomoConfig()
    assert c.model is None
    assert c.datasources == []
    assert c.permission_mode == "full_auto"


def test_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DOMO_MODEL", "gpt-x")
    monkeypatch.setenv("DOMO_CWD", str(tmp_path))
    c = DomoConfig.from_env()
    assert c.model == "gpt-x"
    assert c.cwd == str(tmp_path)


def test_permission_blocks_kubectl_mutations_allows_reads():
    checker = PermissionChecker(DomoConfig().permission_settings())
    assert not checker.evaluate("bash", is_read_only=False, command="kubectl delete pod web").allowed
    assert not checker.evaluate("bash", is_read_only=False, command="kubectl apply -f x.yaml").allowed
    assert not checker.evaluate("bash", is_read_only=False, command="sudo reboot").allowed
    assert checker.evaluate("bash", is_read_only=False, command="kubectl get pods").allowed
    assert checker.evaluate("bash", is_read_only=False, command="kubectl describe pod web").allowed


def test_permission_mode_is_full_auto():
    assert DomoConfig().permission_settings().mode == PermissionMode.FULL_AUTO
