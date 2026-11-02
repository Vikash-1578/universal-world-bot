"""Agent 7: Voice Agent - Generates human-like consistent voiceovers."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging
from pathlib import Path
import re

log = logging.getLogger("app.agents.voice")

class VoiceAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        script = input_data.get("script", "")
        log.info("Synthesizing human-like voiceover for project %d...", project_id)
        
        # 1. Get Channel Voice Settings (Persistent across channel)
        # Default settings for "Verinomia" style (Dark, Heavy, Mysterious)
        voice_settings = {
            "voice": "hi-IN-MadhurNeural", 
            "rate": "-5%",   # Slightly slower for mystery
            "pitch": "-10Hz" # Lower pitch for heavy/masculine feel
        }
        
        # In future, we'll fetch this from hub.db.get_setting(f"voice_{channel_id}")
        
        export_dir = self.hub.projects.folder(project_id, "assets", "audio")
        export_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. Segment script into scenes/chunks for better control
        scenes = re.split(r"\[Scene \d+.*?\]", script)
        scenes = [s.strip() for s in scenes if s.strip()]
        
        audio_files = []
        for idx, text in enumerate(scenes):
            # Dynamic Tone Adjustment
            # If text contains [dark], [whisper], [excited], we change pitch/rate for that chunk
            current_rate = voice_settings["rate"]
            current_pitch = voice_settings["pitch"]
            
            if "[dark]" in text.lower():
                current_pitch = "-20Hz"
                current_rate = "-10%"
            elif "[excited]" in text.lower():
                current_rate = "+15%"
                current_pitch = "+5Hz"
            
            clean_text = re.sub(r"\[.*?\]", "", text) # Remove markers
            path = export_dir / f"scene_{idx+1}.mp3"
            
            await self.hub.tts.synthesize(
                text=clean_text, 
                output_path=path, 
                voice=voice_settings["voice"],
                rate=current_rate,
                pitch=current_pitch
            )
            audio_files.append(str(path))
            
        return {"audio_files": audio_files, "script": script, "voice_used": voice_settings["voice"]}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        # Verify all audio files were actually created on disk
        files = output_data.get("audio_files", [])
        if not files: return False
        
        for f in files:
            if not Path(f).exists(): return False
            
        return True
