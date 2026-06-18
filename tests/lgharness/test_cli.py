from lgharness.cli import build_parser
from lgharness.permissions.modes import PermissionMode


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.permission_mode is None
    assert args.model is None


def test_parser_flags():
    args = build_parser().parse_args(
        ["--model", "gpt-x", "--base-url", "http://h/v1", "--permission-mode", "full_auto"]
    )
    assert args.model == "gpt-x"
    assert args.base_url == "http://h/v1"
    assert args.permission_mode == "full_auto"


def test_permission_mode_choices_match_enum():
    parser = build_parser()
    # All enum values must be accepted choices.
    for mode in PermissionMode:
        ns = parser.parse_args(["--permission-mode", mode.value])
        assert ns.permission_mode == mode.value
