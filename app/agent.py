# ruff: noqa
import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import load_memory, preload_memory
from google.genai import types

from app.a2ui_utils import a2ui_callback
from app.tools import (
    add_destination,
    fetch_live_weather,
    find_nearby_places,
    generate_destination_image,
    generate_destination_video,
    geocode_address,
    get_currency_exchange_rates,
    get_destination_details,
    list_destinations,
)

MODEL = "gemini-2.5-flash"
PROJECT_ID = "qwiklabs-gcp-02-0170751dd1c4"
LOCATION = "us-west1"

# Load Agent Engine Reasoning Engine resource name from deployment_metadata.json
DEPLOYMENT_METADATA_PATH = Path(__file__).parent.parent / "deployment_metadata.json"
code_executor = None
agent_engine_id = "710482423636295680"

if DEPLOYMENT_METADATA_PATH.exists():
    try:
        with open(DEPLOYMENT_METADATA_PATH, "r") as f:
            meta = json.load(f)
        remote_id = meta.get("remote_agent_runtime_id")
        if remote_id:
            agent_engine_id = remote_id.split("/")[-1]
            code_executor = AgentEngineSandboxCodeExecutor(
                agent_engine_resource_name=remote_id
            )
    except Exception as e:
        print(f"Warning: Could not initialize AgentEngineSandboxCodeExecutor: {e}")

# Initialize Memory Service for Agent Engine Memory Bank
memory_service = VertexAiMemoryBankService(
    project=PROJECT_ID,
    location=LOCATION,
    agent_engine_id=agent_engine_id,
)

# Build A2UI v0.8 System Prompt
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description="You are Smart Travel Concierge, an AI assistant for travel planning and recommendations.",
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

full_instruction = (
    f"{a2ui_instruction}\n\n"
    "=== MEMORY, CAPABILITIES & ALLERGY GUIDELINES ===\n"
    "1. ALLERGY & DIETARY MEMORY: You MUST remember and track all user food allergies (e.g. peanuts, shellfish, gluten, dairy, tree nuts, eggs, soy) and dietary restrictions across all sessions.\n"
    "2. Whenever a user states or mentions an allergy or dietary restriction, store it into your Memory Bank so it is permanently remembered.\n"
    "3. ALWAYS check and load stored user memory using `load_memory` or `preload_memory` before making any restaurant, dining, food tour, or itinerary recommendations to guarantee that all suggested options are safe for the user's documented allergies.\n"
    "4. Always use available tools (list_destinations, get_destination_details, add_destination, fetch_live_weather, get_currency_exchange_rates, geocode_address, find_nearby_places, generate_destination_image) to retrieve real data before generating UI cards or responses."
)


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    elif "tokyo" in query.lower() or "kyoto" in query.lower():
        tz_identifier = "Asia/Tokyo"
    elif "paris" in query.lower():
        tz_identifier = "Europe/Paris"
    else:
        return f"Current time information for '{query}': UTC timezone."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time in {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


root_agent = Agent(
    name="smart_travel_concierge",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=full_instruction,
    after_model_callback=a2ui_callback,
    code_executor=code_executor,
    tools=[
        list_destinations,
        get_destination_details,
        add_destination,
        fetch_live_weather,
        get_currency_exchange_rates,
        geocode_address,
        find_nearby_places,
        generate_destination_image,
        generate_destination_video,
        get_current_time,
        load_memory,
        preload_memory,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
