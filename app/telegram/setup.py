"""Wire routers, the owner-only gate and the job-card updater into the aiogram dispatcher."""
from __future__ import annotations

from aiogram import Dispatcher

from app.core.security import OwnerGate
from app.telegram.conversations.state import Conversations
from app.telegram.handlers import animation, fallback, home, jobs, library, projects, studio, wizard
from app.telegram.ratelimit import RateLimit


def setup_dispatcher(dp: Dispatcher, hub) -> None:
    gate = OwnerGate(hub.settings.owner_id, hub.audit)
    # outer middleware: runs before any filter, so unauthorised updates never reach a handler
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    limit = RateLimit()
    dp.message.outer_middleware(limit)
    dp.callback_query.outer_middleware(limit)
    hub.extra.setdefault("conv", Conversations(hub.db))
    dp["hub"] = hub
    for r in (home.router, projects.router, jobs.router, wizard.router, studio.router, library.router, animation.router, *hub.extra.get("routers", []), fallback.router):
        if r.parent_router is not None:
            r._parent_router = None  # allow re-use in tests
        dp.include_router(r)
    updater = jobs.CardUpdater(hub)
    hub.bus.subscribe("job.status", updater)
    hub.bus.subscribe("job.progress", updater)
    hub.bus.subscribe("job.status", animation.VideoSender(hub))
    hub.bus.subscribe("job.status", wizard.WizardNotifier(hub))
