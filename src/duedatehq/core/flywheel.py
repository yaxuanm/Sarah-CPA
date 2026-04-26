from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .intent_cache import InMemoryIntentLibrary
from .intent_planner import RuleBasedIntentPlanner


@dataclass(frozen=True, slots=True)
class LabeledFlywheelInput:
    text: str
    expected_intent: str


@dataclass(slots=True)
class FlywheelConvergenceResult:
    total_inputs: int
    first_round_hits: int
    second_round_hits: int
    template_count: int
    second_round_hit_rate: float
    matched_intents: list[str]
    missed_inputs: list[str]


@dataclass(slots=True)
class LabeledFlywheelMismatch:
    text: str
    expected_intent: str
    actual_intent: str | None
    phase: str


@dataclass(slots=True)
class LabeledFlywheelConvergenceResult:
    total_inputs: int
    first_round_hits: int
    second_round_hits: int
    template_count: int
    second_round_hit_rate: float
    second_round_accuracy: float
    planner_mismatches: list[LabeledFlywheelMismatch]
    cache_mismatches: list[LabeledFlywheelMismatch]
    missed_inputs: list[str]
    templates: list[str]


@dataclass(slots=True)
class HoldoutFlywheelResult:
    train_inputs: int
    test_inputs: int
    template_count: int
    hit_rate: float
    accuracy: float
    mismatches: list[LabeledFlywheelMismatch]
    missed_inputs: list[str]
    templates: list[str]


def run_convergence_test(
    inputs: list[str],
    *,
    planner: RuleBasedIntentPlanner,
    session: dict[str, Any],
    library: InMemoryIntentLibrary | None = None,
) -> FlywheelConvergenceResult:
    intent_library = library or InMemoryIntentLibrary()
    first_round_hits = 0

    for user_input in inputs:
        plan = planner.plan(user_input, session)
        intent_library.learn(user_input, plan, session)

    matched_intents: list[str] = []
    missed_inputs: list[str] = []
    second_round_hits = 0
    for user_input in inputs:
        match = intent_library.match(user_input, session)
        if match:
            second_round_hits += 1
            matched_intents.append(match.template.intent_label)
        else:
            missed_inputs.append(user_input)

    total = len(inputs)
    return FlywheelConvergenceResult(
        total_inputs=total,
        first_round_hits=first_round_hits,
        second_round_hits=second_round_hits,
        template_count=len(intent_library.all()),
        second_round_hit_rate=second_round_hits / total if total else 0.0,
        matched_intents=matched_intents,
        missed_inputs=missed_inputs,
    )


def run_labeled_convergence_test(
    inputs: list[LabeledFlywheelInput],
    *,
    planner: RuleBasedIntentPlanner,
    session: dict[str, Any],
    library: InMemoryIntentLibrary | None = None,
) -> LabeledFlywheelConvergenceResult:
    intent_library = library or InMemoryIntentLibrary()
    first_round_hits = 0
    planner_mismatches: list[LabeledFlywheelMismatch] = []

    for item in inputs:
        plan = planner.plan(item.text, session)
        actual_intent = plan.get("intent_label")
        if actual_intent != item.expected_intent:
            planner_mismatches.append(
                LabeledFlywheelMismatch(
                    text=item.text,
                    expected_intent=item.expected_intent,
                    actual_intent=actual_intent,
                    phase="planner",
                )
            )
        intent_library.learn(item.text, plan, session)

    second_round_hits = 0
    correct_second_round_hits = 0
    missed_inputs: list[str] = []
    cache_mismatches: list[LabeledFlywheelMismatch] = []

    for item in inputs:
        match = intent_library.match(item.text, session)
        if not match:
            missed_inputs.append(item.text)
            cache_mismatches.append(
                LabeledFlywheelMismatch(
                    text=item.text,
                    expected_intent=item.expected_intent,
                    actual_intent=None,
                    phase="cache",
                )
            )
            continue

        second_round_hits += 1
        actual_intent = match.template.intent_label
        if actual_intent == item.expected_intent:
            correct_second_round_hits += 1
        else:
            cache_mismatches.append(
                LabeledFlywheelMismatch(
                    text=item.text,
                    expected_intent=item.expected_intent,
                    actual_intent=actual_intent,
                    phase="cache",
                )
            )

    total = len(inputs)
    templates = sorted({template.intent_label for template in intent_library.all()})
    return LabeledFlywheelConvergenceResult(
        total_inputs=total,
        first_round_hits=first_round_hits,
        second_round_hits=second_round_hits,
        template_count=len(intent_library.all()),
        second_round_hit_rate=second_round_hits / total if total else 0.0,
        second_round_accuracy=correct_second_round_hits / total if total else 0.0,
        planner_mismatches=planner_mismatches,
        cache_mismatches=cache_mismatches,
        missed_inputs=missed_inputs,
        templates=templates,
    )


def run_labeled_holdout_test(
    inputs: list[LabeledFlywheelInput],
    *,
    planner: RuleBasedIntentPlanner,
    session: dict[str, Any],
    train_ratio: float = 0.65,
    library: InMemoryIntentLibrary | None = None,
) -> HoldoutFlywheelResult:
    intent_library = library or InMemoryIntentLibrary()
    by_intent: dict[str, list[LabeledFlywheelInput]] = {}
    for item in inputs:
        by_intent.setdefault(item.expected_intent, []).append(item)

    train: list[LabeledFlywheelInput] = []
    test: list[LabeledFlywheelInput] = []
    for intent_items in by_intent.values():
        split_at = max(1, int(len(intent_items) * train_ratio))
        if split_at >= len(intent_items) and len(intent_items) > 1:
            split_at = len(intent_items) - 1
        train.extend(intent_items[:split_at])
        test.extend(intent_items[split_at:])

    for item in train:
        plan = planner.plan(item.text, session)
        intent_library.learn(item.text, plan, session)

    hits = 0
    correct = 0
    mismatches: list[LabeledFlywheelMismatch] = []
    missed_inputs: list[str] = []
    for item in test:
        match = intent_library.match(item.text, session)
        if not match:
            missed_inputs.append(item.text)
            mismatches.append(
                LabeledFlywheelMismatch(
                    text=item.text,
                    expected_intent=item.expected_intent,
                    actual_intent=None,
                    phase="holdout_cache",
                )
            )
            continue
        hits += 1
        actual_intent = match.template.intent_label
        if actual_intent == item.expected_intent:
            correct += 1
        else:
            mismatches.append(
                LabeledFlywheelMismatch(
                    text=item.text,
                    expected_intent=item.expected_intent,
                    actual_intent=actual_intent,
                    phase="holdout_cache",
                )
            )

    total = len(test)
    return HoldoutFlywheelResult(
        train_inputs=len(train),
        test_inputs=total,
        template_count=len(intent_library.all()),
        hit_rate=hits / total if total else 0.0,
        accuracy=correct / total if total else 0.0,
        mismatches=mismatches,
        missed_inputs=missed_inputs,
        templates=sorted({template.intent_label for template in intent_library.all()}),
    )
