from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .core.bus import InMemoryEventBus
from .core.clock import SystemClock
from .core.conversation import ConversationService
from .core.engine import InfrastructureEngine
from .core.executor import PlanExecutor
from .core.flywheel_router import FlywheelIntentRouter
from .core.agent_kernel import ClaudeAgentKernel, DeterministicAgentKernel
from .core.intent_cache import InMemoryIntentLibrary
from .core.intent_planner import RuleBasedIntentPlanner
from .core.interaction_backend import InteractionBackend, IntentPlanner
from .core.nlu_service import ClaudeNLUService
from .core.persistent_intent_cache import SQLiteIntentLibrary
from .core.postgres import PostgresStorage
from .core.repositories import Repositories
from .core.response_generator import ResponseGenerator
from .core.session_manager import InMemoryInteractionSessionManager, RedisInteractionSessionManager
from .core.storage import SQLiteStorage
from .core.template_tools import TemplateToolset


@dataclass(slots=True)
class App:
    engine: InfrastructureEngine
    conversation: ConversationService
    executor: PlanExecutor
    intent_planner: IntentPlanner
    intent_library: InMemoryIntentLibrary
    response_generator: ResponseGenerator
    interaction_backend: InteractionBackend
    interaction_sessions: InMemoryInteractionSessionManager | RedisInteractionSessionManager
    template_tools: TemplateToolset


def create_app(db_path: str | None = None) -> App:
    storage = build_storage(db_path)
    repositories = Repositories(storage=storage)
    event_bus = InMemoryEventBus()
    clock = SystemClock()
    engine = InfrastructureEngine(
        repositories=repositories,
        event_bus=event_bus,
        clock=clock,
    )
    conversation = ConversationService(engine)
    executor = PlanExecutor(engine)
    if os.getenv("DUEDATEHQ_PERSIST_FLYWHEEL") == "1" and isinstance(storage, SQLiteStorage):
        intent_library = SQLiteIntentLibrary(storage)
    else:
        intent_library = InMemoryIntentLibrary()
    if os.getenv("DUEDATEHQ_USE_FLYWHEEL_ROUTER") == "1":
        rule_planner = RuleBasedIntentPlanner(engine)
        if os.getenv("DUEDATEHQ_USE_CLAUDE_NLU") == "1":
            planner = ClaudeNLUService(engine)
            fallback_planner = rule_planner
        else:
            planner = rule_planner
            fallback_planner = None
        intent_planner = FlywheelIntentRouter(
            intent_library=intent_library,
            planner=planner,
            fallback_planner=fallback_planner,
        )
    elif os.getenv("DUEDATEHQ_USE_CLAUDE_NLU") == "1":
        intent_planner = ClaudeNLUService(engine, intent_library=intent_library)
    else:
        intent_planner = RuleBasedIntentPlanner(engine)
    response_generator = ResponseGenerator(engine)
    template_tools = TemplateToolset(engine)
    agent_kernel = (
        ClaudeAgentKernel(engine)
        if os.getenv("DUEDATEHQ_USE_AGENT_KERNEL") == "1" or os.getenv("DUEDATEHQ_USE_AGENT_POLICY") == "1"
        else DeterministicAgentKernel()
    )
    interaction_backend = InteractionBackend(
        executor,
        response_generator,
        intent_planner,
        intent_library,
        agent_kernel=agent_kernel,
    )
    redis_url = os.getenv("DUEDATEHQ_REDIS_URL")
    interaction_sessions = (
        RedisInteractionSessionManager(redis_url)
        if redis_url
        else InMemoryInteractionSessionManager()
    )
    return App(
        engine=engine,
        conversation=conversation,
        executor=executor,
        intent_planner=intent_planner,
        intent_library=intent_library,
        response_generator=response_generator,
        interaction_backend=interaction_backend,
        interaction_sessions=interaction_sessions,
        template_tools=template_tools,
    )


def build_storage(db_path: str | None = None):
    db_path = db_path or os.getenv("DUEDATEHQ_DATABASE_URL")
    if db_path and db_path.startswith(("postgresql://", "postgres://")):
        storage = PostgresStorage(db_path)
        storage.initialize()
        return storage
    resolved = Path(db_path) if db_path else Path.cwd() / ".duedatehq" / "duedatehq.sqlite3"
    return SQLiteStorage(resolved)
