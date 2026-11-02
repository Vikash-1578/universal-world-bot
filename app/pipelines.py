"""Job handlers for each milestone and Agent Pipeline registration."""
from __future__ import annotations

import logging
from typing import Any
from app.core.pipeline import AgentState

log = logging.getLogger("app.pipelines")

async def job_run_agent_pipeline(hub, project_id, params):
    """Runs the full multi-agent pipeline for a project."""
    topic = params.get("topic", "General Facts")
    try:
        result = await hub.orchestrator.run_pipeline(project_id, {"topic": topic})
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

def register_all(hub):
    """Registers all background job handlers."""
    hub.jobs.register("run_agent_pipeline", job_run_agent_pipeline)
    # Add other milestone jobs here if needed
