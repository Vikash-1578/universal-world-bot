
async def job_render_video(hub, project_id, params):
    """Renders the final video for a project."""
    try:
        output_path = await hub.renderer.render_project(hub, project_id)
        return {"status": "success", "path": str(output_path)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


"""Registers job handlers. Each milestone adds its own; unregistered job types simply stay queued."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.container import Hub


def register_all(hub: "Hub") -> None:
    from app.observability.selftest import register as reg_selftest

    reg_selftest(hub)
    from app.scripts.jobs import register as reg_story

    reg_story(hub)
    from app.characters.jobs import register as reg_library

    reg_library(hub)
    from app.animation.two_d.jobs import register as reg_anim2d

    reg_anim2d(hub)