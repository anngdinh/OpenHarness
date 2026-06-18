"""Permission checking for tool execution."""

from __future__ import annotations

from dataclasses import dataclass

from lgharness.permissions.modes import PermissionMode

# Tools that never mutate state and are always safe to run.
READ_ONLY_TOOLS: frozenset[str] = frozenset({"read_file"})


@dataclass(frozen=True)
class PermissionDecision:
    """Result of checking whether a tool invocation may run."""

    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


class PermissionChecker:
    """Evaluate a tool call against the active permission mode."""

    def __init__(self, mode: PermissionMode) -> None:
        self._mode = mode

    def evaluate(self, tool_name: str) -> PermissionDecision:
        """Return whether the named tool may run, or needs confirmation."""
        if self._mode == PermissionMode.FULL_AUTO:
            return PermissionDecision(allowed=True, reason="full_auto allows all tools")

        if tool_name in READ_ONLY_TOOLS:
            return PermissionDecision(allowed=True, reason="read-only tool")

        if self._mode == PermissionMode.PLAN:
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason="plan mode blocks mutating tools",
            )

        # DEFAULT mode: mutating tools require confirmation.
        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="mutating tool requires user confirmation in default mode",
        )
