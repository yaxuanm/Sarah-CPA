from __future__ import annotations

from dataclasses import dataclass

from ..core.models import DeadlineAction, DeadlineStatus


class InvalidTransitionError(ValueError):
    pass


ACTION_TRANSITIONS: dict[DeadlineStatus, dict[DeadlineAction, DeadlineStatus]] = {
    DeadlineStatus.PENDING: {
        DeadlineAction.COMPLETE: DeadlineStatus.COMPLETED,
        DeadlineAction.SNOOZE: DeadlineStatus.SNOOZED,
        DeadlineAction.WAIVE: DeadlineStatus.WAIVED,
        DeadlineAction.OVERRIDE: DeadlineStatus.OVERRIDDEN,
    },
    DeadlineStatus.SNOOZED: {
        DeadlineAction.RESUME: DeadlineStatus.PENDING,
        DeadlineAction.COMPLETE: DeadlineStatus.COMPLETED,
        DeadlineAction.WAIVE: DeadlineStatus.WAIVED,
    },
    DeadlineStatus.COMPLETED: {
        DeadlineAction.REOPEN: DeadlineStatus.PENDING,
    },
    DeadlineStatus.WAIVED: {
        DeadlineAction.REOPEN: DeadlineStatus.PENDING,
    },
    DeadlineStatus.OVERRIDDEN: {
        DeadlineAction.COMPLETE: DeadlineStatus.COMPLETED,
        DeadlineAction.SNOOZE: DeadlineStatus.SNOOZED,
        DeadlineAction.WAIVE: DeadlineStatus.WAIVED,
    },
}


@dataclass(slots=True)
class DeadlineStateMachine:
    def available_actions(self, current: DeadlineStatus) -> list[DeadlineAction]:
        return list(ACTION_TRANSITIONS.get(current, {}).keys())

    def transition(self, current: DeadlineStatus, action: DeadlineAction) -> DeadlineStatus:
        try:
            return ACTION_TRANSITIONS[current][action]
        except KeyError as exc:
            raise InvalidTransitionError(f"{current.value} -> {action.value} is not allowed") from exc
