"""The Master Orchestrator with cinematic live reporting and state regression."""
from __future__ import annotations
from app.core.pipeline import AgentState, get_next_state
import logging

log = logging.getLogger("app.core.orchestrator")

class Orchestrator:
    def __init__(self, hub):
        self.hub = hub
        # Detailed descriptions for the live chat
        self.agent_descriptions = {
            AgentState.RESEARCHING: "🔍 **Agent 1 (Research):** Gathering deep facts and hidden gems from the web...",
            AgentState.VERIFYING_ACCURACY: "🧪 **Agent 2 (Accuracy):** Cross-verifying every single claim to ensure 100% truth...",
            AgentState.SCRIPTING: "✍️ **Agent 3 (Scripting):** Crafting a high-retention Hinglish story with a killer hook...",
            AgentState.CHECKING_VIRALITY: "📈 **Agent 4 (Virality):** Analyzing pacing and retention triggers to ensure it goes viral...",
            AgentState.QUALITY_CONTROL: "🧐 **Agent 5 (Quality):** Reviewing brand tone and language for the Verinomia vibe...",
            AgentState.VOICEOVER: "🎙️ **Agent 6 (Voice):** Synthesizing a professional, human-like mysterious voiceover...",
            AgentState.SOURCING_MEDIA: "🖼️ **Agent 7 (Media):** Sourcing cinematic stock footage and AI visuals...",
            AgentState.CHECKING_MEDIA: "👁️ **Agent 8 (Media Checker):** Ensuring every visual matches the script perfectly...",
            AgentState.EDITING: "🎬 **Agent 9 (Editor):** Assembling everything with Pro-Zoom and smooth transitions...",
            AgentState.VERIFYING_VIDEO: "✅ **Agent 10 (Video Checker):** Final quality scan of the rendered MP4...",
            AgentState.THUMBNAIL_GEN: "🎨 **Agent 11 (Thumbnail):** Designing a high-CTR viral thumbnail...",
            AgentState.SEO_OPTIMIZATION: "🚀 **Agent 12 (SEO):** Writing viral titles and search-optimized tags...",
            AgentState.ANALYZING: "📊 **Agent 13 (Analyser):** Studying trends to optimize future content...",
            AgentState.CONFIGURING: "⚙️ **Agent 14 (Config):** Optimizing system health and performance...",
        }

    async def run_pipeline(self, project_id: int, initial_input: dict, bot=None, chat_id=None):
        current_state = AgentState.RESEARCHING
        current_input = initial_input
        
        REGRESSION_MAP = {
            AgentState.VERIFYING_ACCURACY: AgentState.RESEARCHING,
            AgentState.CHECKING_VIRALITY: AgentState.SCRIPTING,
            AgentState.QUALITY_CONTROL: AgentState.SCRIPTING,
            AgentState.CHECKING_MEDIA: AgentState.SOURCING_MEDIA,
            AgentState.VERIFYING_VIDEO: AgentState.EDITING,
        }
        
        while current_state is not None and current_state != AgentState.COMPLETED:
            # --- CINEMATIC LIVE UPDATE ---
            if bot and chat_id:
                desc = self.agent_descriptions.get(current_state, f"Processing {current_state.name}...")
                update_msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{desc}\n"
                    f"⏳ **Status:** Working... please wait."
                )
                await bot.send_message(chat_id, update_msg, parse_mode="Markdown")

            agent = self._get_agent_for_state(current_state)
            if not agent:
                current_state = get_next_state(current_state)
                continue
            
            try:
                result = await agent.run(project_id, current_input)
                current_input = result
                current_state = get_next_state(current_state)
                
            except Exception as e:
                log.error("Agent %s failed: %s", current_state.name, e)
                fallback_state = REGRESSION_MAP.get(current_state)
                if fallback_state:
                    if bot and chat_id:
                        await bot.send_message(
                            chat_id, 
                            f"⚠️ **Quality Alert!**\nAgent {current_state.name} found an issue. \n\n"
                            f"↩️ **Action:** Sending project back to {fallback_state.name.replace('_', ' ').title()} for correction.\n"
                            f"❌ **Reason:** {str(e)}", 
                            parse_mode="Markdown"
                        )
                    current_state = fallback_state
                else:
                    if bot and chat_id:
                        await bot.send_message(chat_id, f"❌ Critical Failure at {current_state.name}: {e}")
                    return {"status": "failed", "state": current_state.name, "error": str(e)}
        
        if bot and chat_id:
            await bot.send_message(chat_id, "🎉 **Mission Accomplished!**\n\nYour professional video is ready. All 15 agents have successfully finished their work!", parse_mode="Markdown")
            
        return {"status": "success", "final_output": current_input}

    def _get_agent_for_state(self, state: AgentState):
        mapping = {
            AgentState.RESEARCHING: self.hub.research_agent,
            AgentState.VERIFYING_ACCURACY: self.hub.accuracy_agent,
            AgentState.SCRIPTING: self.hub.scripting_agent,
            AgentState.CHECKING_VIRALITY: self.hub.virality_agent,
            AgentState.QUALITY_CONTROL: self.hub.quality_agent,
            AgentState.VOICEOVER: self.hub.voice_agent,
            AgentState.SOURCING_MEDIA: self.hub.media_agent,
            AgentState.CHECKING_MEDIA: self.hub.media_checker_agent,
            AgentState.EDITING: self.hub.editor_agent,
            AgentState.VERIFYING_VIDEO: self.hub.video_checker_agent,
            AgentState.THUMBNAIL_GEN: self.hub.thumbnail_agent,
            AgentState.SEO_OPTIMIZATION: self.hub.seo_agent,
            AgentState.ANALYZING: self.hub.analyser_agent,
            AgentState.CONFIGURING: self.hub.config_agent,
        }
        return mapping.get(state)
