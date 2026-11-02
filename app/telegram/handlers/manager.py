"""Handler for the Manager Agent - The single point of contact."""
from __future__ import annotations
from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from app.telegram.ui import show, answer, fail
from app.telegram.keyboards.menus import nav

router = Router(name="manager")

@router.message(F.text.startswith("/make_video "))
async def cmd_make_video(message: Message, hub):
    """Command: /make_video [Topic]"""
    topic = message.text.replace("/make_video ", "").strip()
    if not topic:
        await message.answer("Please provide a topic. Example: /make_video Space Mystery")
        return

    # Create a project for this video
    project = hub.projects.create_project(name=topic, settings={"target_seconds": 60})
    pid = project["id"]
    
    await message.answer(f"💼 Manager is taking over! Project created: {topic}. Starting the 15-agent pipeline...")
    
    # Trigger the pipeline asynchronously
    # We use hub.jobs to run this in background
    job = hub.jobs.submit_job(
        "run_agent_pipeline", pid, 
        {"topic": topic}, 
        heavy=True, 
        chat_id=message.chat.id, 
        title=f"Producing: {topic}"
    )
    
    await message.answer(f"Pipeline started. Job ID: {job['id']}. I will notify you as each agent finishes their work!")

@router.message(F.text == "/manager")
async def cmd_manager(message: Message, hub):
    await show(message, "👋 Hello! I am the Universal World Manager.\n\nI control 14 specialist agents to build your videos.\n\nUse /make_video [Topic] to start a professional production.")
