"""Main video rendering engine. Combines audio and visuals into a final MP4."""
from __future__ import annotations

import logging
from pathlib import Path
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeAudioClip, ColorClip, TextClip

log = logging.getLogger("app.rendering.engine")

class RenderEngine:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    async def render_project(self, hub, project_id: int) -> Path:
        """
        The Grand Finale: Takes a project, generates assets, and renders the video.
        """
        project = hub.projects.get_project(project_id)
        storyboard = hub.storyboards.state(project_id)
        scenes = hub.storyboards.scenes(project_id)
        
        if not scenes:
            raise ValueError("Storyboard is empty. Please generate scenes first.")

        export_dir = hub.projects.folder(project_id, "exports")
        export_dir.mkdir(parents=True, exist_ok=True)
        
        final_clips = []
        
        log.info("Starting render for project %s...", project_id)
        
        for idx, scene in enumerate(scenes):
            scene_id = scene["id"]
            log.info("Rendering scene %d/%d (ID: %s)...", idx + 1, len(scenes), scene_id)
            
            # 1. Voiceover
            audio_path = export_dir / f"scene_{idx+1}.mp3"
            # We assume 'description' in scene contains the text to speak
            text = scene.get("description", "No text provided")
            await hub.tts.synthesize(text, audio_path)
            
            # 2. Visual
            image_path = export_dir / f"scene_{idx+1}.jpg"
            # We use the description as prompt for Pollinations
            await hub.free_gen.generate(text, image_path)
            
            # 3. Create MoviePy Clip
            audio_clip = AudioFileClip(str(audio_path))
            duration = audio_clip.duration
            
            img_clip = ImageClip(str(image_path)).set_duration(duration)
            img_clip = img_clip.set_audio(audio_clip)
            
            final_clips.append(img_clip)
        
        # Combine all
        final_video = concatenate_videoclips(final_clips, method="compose")
        output_file = export_dir / "final_video.mp4"
        
        # Render to file (low-res for speed/stability)
        final_video.write_videofile(
            str(output_file), 
            fps=24, 
            codec="libx264", 
            audio_codec="aac",
            threads=4,
            preset="ultrafast"
        )
        
        return output_file