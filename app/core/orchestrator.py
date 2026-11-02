"""The Master Orchestrator that manages agent hand-offs."""
from __future__ import annotations
from app.core.pipeline import AgentState, get_next_state
import logging

log = logging.getLogger("app.core.orchestrator")

class Orchestrator:
    def __init__(self, hub):
        self.hub = hub

    async def run_pipeline(self, project_id: int, initial_input: dict):
        """Drives the project through the agent sequence."""
        current_state = AgentState.RESEARCHING
        current_input = initial_input
        
        while current_state is not None and current_state != AgentState.COMPLETED:
            log.info("Project %d: Now at state %s", project_id, current_state.name)
            
            # 1. Map State to Agent
            agent = self._get_agent_for_state(current_state)
            if not agent:
                log.warning("No agent found for state %s. Skipping.", current_state.name)
                current_state = get_next_state(current_state)
                continue
            
            try:
                # 2. Execute the Agent (Logic -> Execute -> Verify loop)
                result = await agent.run(project_id, current_input)
                current_input = result # Output of Agent N becomes input of Agent N+1
                
                # 3. Move to next state
                current_state = get_next_state(current_state)
                
            except Exception as e:
                log.error("Pipeline failed at state %s: %s", current_state.name, e)
                return {"status": "failed", "state": current_state.name, "error": str(e)}
        
        return {"status": "success", "final_output": current_input}

    def _get_agent_for_state(self, state: AgentState):
        mapping = {
            AgentState.RESEARCHING: self.hub.research_agent,
            AgentState.VERIFYING_ACCURACY: self.hub.accuracy_agent,
            AgentState.SCRIPTING: self.hub.scripting_agent,
            AgentState.CHECKING_VIRALITY: self.hub.virality_agent,
            # Other agents will be added here as we build them
        }
        return mapping.get(state)