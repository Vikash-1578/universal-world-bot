"""Base class for all AI Agents to ensure a Logic -> Execution -> Checking loop."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import logging

log = logging.getLogger("app.core.agent")

class BaseAgent(ABC):
    def __init__(self, hub):
        self.hub = hub

    @abstractmethod
    async def execute(self, project_id: int, input_data: dict) -> dict:
        """Main logic of the agent."""
        pass

    @abstractmethod
    async def verify(self, project_id: int, output_data: dict) -> bool:
        """Self-correction: check if output meets quality standards."""
        pass

    async def run(self, project_id: int, input_data: dict):
        """The Agentic Loop: Execute -> Verify -> (Repeat if Fail) -> Pass."""
        attempts = 0
        max_attempts = 3
        
        while attempts < max_attempts:
            attempts += 1
            log.info("Agent %s: Execution attempt %d/%d", self.__class__.__name__, attempts, max_attempts)
            
            output = await self.execute(project_id, input_data)
            
            if await self.verify(project_id, output):
                log.info("Agent %s: Verified successfully!", self.__class__.__name__)
                return output
            
            log.warning("Agent %s: Verification failed. Retrying...", self.__class__.__name__)
            # Update input_data based on failure if possible
            
        raise RuntimeError(f"Agent {self.__class__.__name__} failed after {max_attempts} attempts.")
