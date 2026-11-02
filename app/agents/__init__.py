"""Specialist agents for faceless facts / history / mystery videos.

Each agent does ONE job and returns an `AgentResult`. The Manager runs them in order as a resumable job.
Light work uses the local model; cloud is used only if the owner enabled it (handled by the LLM router)."""
