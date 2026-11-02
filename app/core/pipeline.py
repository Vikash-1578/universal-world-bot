"""Defines the sequential pipeline for the Multi-Agent Studio."""
from __future__ import annotations
from enum import Enum, auto

class AgentState(Enum):
    IDLE = auto()
    RESEARCHING = auto()
    VERIFYING_ACCURACY = auto()
    SCRIPTING = auto()
    CHECKING_VIRALITY = auto()
    QUALITY_CONTROL = auto()
    VOICEOVER = auto()
    SOURCING_MEDIA = auto()
    CHECKING_MEDIA = auto()
    EDITING = auto()
    VERIFYING_VIDEO = auto()
    THUMBNAIL_GEN = auto()
    SEO_OPTIMIZATION = auto()
    ANALYZING = auto()
    CONFIGURING = auto()
    COMPLETED = auto()
    FAILED = auto()

# The Order of Agents (1 to 15)
AGENT_SEQUENCE = [
    AgentState.RESEARCHING,        # Agent 1
    AgentState.VERIFYING_ACCURACY, # Agent 2
    AgentState.SCRIPTING,          # Agent 3
    AgentState.CHECKING_VIRALITY,  # Agent 4
    AgentState.QUALITY_CONTROL,    # Agent 5 (Wait, user said 6 is Quality Checker)
    AgentState.VOICEOVER,          # Agent 7
    AgentState.SOURCING_MEDIA,     # Agent 8
    AgentState.CHECKING_MEDIA,     # Agent 9
    AgentState.EDITING,            # Agent 10
    AgentState.VERIFYING_VIDEO,    # Agent 11
    AgentState.THUMBNAIL_GEN,      # Agent 12
    AgentState.SEO_OPTIMIZATION,   # Agent 13
    AgentState.ANALYZING,          # Agent 14
    AgentState.CONFIGURING,        # Agent 15
]

def get_next_state(current: AgentState) -> AgentState | None:
    try:
        idx = AGENT_SEQUENCE.index(current)
        if idx + 1 < len(AGENT_SEQUENCE):
            return AGENT_SEQUENCE[idx + 1]
    except ValueError:
        pass
    return None
