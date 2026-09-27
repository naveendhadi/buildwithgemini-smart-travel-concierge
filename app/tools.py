import os
import subprocess
import urllib.parse
import uuid
from typing import Any, Optional
from dotenv import load_dotenv

import google.auth
import google.oauth2.credentials
import httpx
from google import genai
from google.adk.tools import ToolContext
from google.cloud import firestore, storage
from google.genai import types

load_dotenv()

PROJECT_ID = "qwiklabs-gcp-02-0170751dd1c4"
BUCKET_NAME = "smart-travel-concierge-media-qwiklabs-gcp-02-0170751dd1c4"


def get_firestore_client() -> firestore.Client:
    """Returns a Firestore client configured with the explicit project ID."""
    try:
        client = firestore.Client(project=PROJECT_ID)
        client.collection("_ping").document("ping").get()
        return client
    except Exception:
        try:
            token = subprocess.check_output(
                ["gcloud", "auth", "print-access-token"], text=True
            ).strip()
            creds = google.oauth2.credentials.Credentials(token)
            return firestore.Client(project=PROJECT_ID, credentials=creds)
        except Exception:
            return firestore.Client(project=PROJECT_ID)


def list_destinations(category: Optional[str] = None) -> list[dict[str, Any]]:
    """Retrieves travel destinations from the Firestore catalog.

    Args:
        category: Optional category filter (e.g. 'Culture & Urban', 'Romance & Art', 'Beach & Wellness').

    Returns:
        A list of destination dictionaries.
    """
    db = get_firestore_client()
    query = db.collection("destinations")

    if category:
        query = query.where("category", "==", category)

    docs = query.stream()
    results = [doc.to_dict() for doc in docs]
    return results


def get_destination_details(destination_id: str) -> dict[str, Any]:
    """Retrieves full details for a specific travel destination by ID.

    Args:
        destination_id: The unique identifier of the destination (e.g. 'dest-tokyo-01').

    Returns:
        A dictionary containing destination details or an error message.
    """
    db = get_firestore_client()
    doc_ref = db.collection("destinations").document(destination_id)
    doc = doc_ref.get()

    if doc.exists:
        return doc.to_dict()
    return {"error": f"Destination with ID '{destination_id}' not found."}


def add_destination(
    name: str,
    country: str,
    description: str,
    price_per_day_usd: float,
    category: str,
    popular_spots: list[str],
    best_season: str,
) -> dict[str, Any]:
    """Adds a new destination or updates an existing one in the Firestore catalog.

    Args:
        name: Name of the city/region (e.g. 'Kyoto').
        country: Name of the country (e.g. 'Japan').
        description: Summary of what makes this destination special.
        price_per_day_usd: Estimated average daily cost in USD.
        category: Travel category (e.g. 'Historic & Culture').
        popular_spots: List of top attractions/spots.
        best_season: Best season or time of year to visit.

    Returns:
        A dictionary confirming creation and containing the assigned ID.
    """
    db = get_firestore_client()
    dest_id = f"dest-{name.lower().replace(' ', '-')}-custom"

    new_dest = {
        "id": dest_id,
        "name": name,
        "country": country,
        "description": description,
        "price_per_day_usd": float(price_per_day_usd),
        "category": category,
        "popular_spots": popular_spots,
        "best_season": best_season,
    }

    db.collection("destinations").document(dest_id).set(new_dest)
    return {"status": "success", "destination_id": dest_id, "data": new_dest}


def fetch_live_weather(location: str) -> dict[str, Any]:
    """Fetches real-time live weather and climate conditions for any city worldwide using the Open-Meteo API.

    Args:
        location: City name or destination location (e.g. 'Tokyo', 'Paris', 'Kyoto', 'New York').

    Returns:
        A dictionary with live temperature, weather conditions, wind speed, and location details.
    """
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(location)}&count=1&language=en&format=json"
        r = httpx.get(geo_url, timeout=5)
        data = r.json()
        if "results" in data and data["results"]:
            loc = data["results"][0]
            lat, lon = loc["latitude"], loc["longitude"]
            city_name = loc.get("name", location)
            country = loc.get("country", "")

            forecast_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
            weather_res = httpx.get(forecast_url, timeout=5).json()
            current = weather_res.get("current_weather", {})
            temp_c = current.get("temperature")
            temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else None

            return {
                "status": "success",
                "location": f"{city_name}, {country}".strip(", "),
                "temperature_celsius": temp_c,
                "temperature_fahrenheit": temp_f,
                "windspeed_kmh": current.get("windspeed"),
                "is_daytime": bool(current.get("is_day", 1)),
            }
        return {"error": f"Could not find coordinates for location: '{location}'."}
    except Exception as e:
        return {"error": f"Failed to fetch live weather: {str(e)}"}


def get_currency_exchange_rates(
    base_currency: str = "USD",
    target_currencies: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Fetches real-time foreign exchange rates for travel budget calculations from Exchange Rates API.

    Args:
        base_currency: The base currency code (e.g. 'USD', 'EUR', 'GBP', 'JPY').
        target_currencies: Optional list of target currency codes to filter (e.g. ['EUR', 'JPY', 'GBP', 'IDR']).

    Returns:
        A dictionary with live exchange rates, base currency, and last update timestamp.
    """
    try:
        base = base_currency.upper().strip()
        api_key = os.getenv("EXCHANGE_RATE_API_KEY", "")

        url = f"https://open.er-api.com/v6/latest/{base}"
        headers = {"User-Agent": "SmartTravelConcierge/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        r = httpx.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            rates = data.get("rates", {})
            if target_currencies:
                filtered = [c.upper().strip() for c in target_currencies]
                rates = {k: v for k, v in rates.items() if k in filtered}
            return {
                "status": "success",
                "base_currency": base,
                "rates": rates,
                "last_update_utc": data.get("time_last_update_utc"),
            }
        return {"error": f"Failed to fetch exchange rates for '{base_currency}'. Status: {r.status_code}"}
    except Exception as e:
        return {"error": f"Failed to fetch currency exchange rates: {str(e)}"}


def geocode_address(address: str) -> dict[str, Any]:
    """Converts a street address or location name into geographic coordinates (latitude, longitude) using Google Geocoding API.

    Args:
        address: The location address or landmark name (e.g., 'Eiffel Tower, Paris' or 'Shibuya Crossing, Tokyo').

    Returns:
        A dictionary containing the formatted address, location coordinates (latitude, longitude), and place ID.
    """
    try:
        load_dotenv()
        api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not api_key:
            return {"error": "GOOGLE_MAPS_API_KEY environment variable is not configured."}

        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
        r = httpx.get(url, timeout=5)
        data = r.json()

        if data.get("status") == "OK" and data.get("results"):
            res = data["results"][0]
            loc = res.get("geometry", {}).get("location", {})
            return {
                "status": "success",
                "name": address,
                "formatted_address": res.get("formatted_address"),
                "location": {
                    "latitude": loc.get("lat"),
                    "longitude": loc.get("lng"),
                },
                "place_id": res.get("place_id"),
            }
        return {"error": f"Geocoding failed for address '{address}'. Status: {data.get('status')}", "details": data}
    except Exception as e:
        return {"error": f"Failed to geocode address: {str(e)}"}


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "restaurant",
    radius_meters: float = 1000.0,
) -> dict[str, Any]:
    """Finds nearby places of interest (restaurants, hotels, tourist attractions, etc.) near coordinates using Google Places API (New).

    Args:
        latitude: Center point latitude (e.g. 35.6595).
        longitude: Center point longitude (e.g. 139.7004).
        place_type: Type of place to search for (e.g. 'restaurant', 'tourist_attraction', 'lodging', 'cafe', 'museum').
        radius_meters: Search radius in meters (default 1000.0 meters).

    Returns:
        A dictionary containing a list of nearby places with name, formatted address, and coordinates.
    """
    try:
        load_dotenv()
        api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not api_key:
            return {"error": "GOOGLE_MAPS_API_KEY environment variable is not configured."}

        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
        }
        body = {
            "includedTypes": [place_type],
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                    },
                    "radius": float(radius_meters),
                }
            },
        }

        r = httpx.post(url, json=body, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            raw_places = data.get("places", [])
            places_list = []
            for p in raw_places:
                display_name = p.get("displayName", {}).get("text", "")
                formatted_address = p.get("formattedAddress", "")
                loc = p.get("location", {})
                places_list.append({
                    "name": display_name,
                    "address": formatted_address,
                    "location": {
                        "latitude": loc.get("latitude"),
                        "longitude": loc.get("longitude"),
                    },
                })
            return {
                "status": "success",
                "center_location": {"latitude": latitude, "longitude": longitude},
                "place_type": place_type,
                "places": places_list,
            }
        return {"error": f"Places search failed with status HTTP {r.status_code}", "response": r.text}
    except Exception as e:
        return {"error": f"Failed to search nearby places: {str(e)}"}


async def generate_destination_image(
    prompt: str,
    destination_name: str = "travel_destination",
    tool_context: Optional[ToolContext] = None,
) -> dict[str, Any]:
    """Generates a high-quality travel image for a destination using gemini-3.1-flash-lite-image model in global region.

    Saves the generated image as an artifact in ToolContext and uploads the image bytes directly to public Cloud Storage.

    Args:
        prompt: Detailed visual prompt describing the scene/landmark to generate.
        destination_name: Name of the destination/landmark for filename generation.
        tool_context: Automatically provided ADK ToolContext for artifact saving.

    Returns:
        A dictionary containing the public Cloud Storage image URL, artifact filename, and status.
    """
    try:
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="global",
        )

        full_prompt = f"A vibrant, high quality travel photograph of {destination_name}: {prompt}"
        res = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=full_prompt,
        )

        img_bytes = None
        mime_type = "image/jpeg"
        if res.candidates and res.candidates[0].content and res.candidates[0].content.parts:
            for part in res.candidates[0].content.parts:
                if part.inline_data:
                    img_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or mime_type
                    break

        if not img_bytes:
            return {"error": f"No image bytes generated for '{destination_name}'."}

        safe_name = destination_name.lower().replace(" ", "-")
        filename = f"destination-{safe_name}-{uuid.uuid4().hex[:8]}.jpg"

        # 1. Save with tool_context.save_artifact
        if tool_context:
            await tool_context.save_artifact(
                filename=filename,
                artifact=types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
            )

        # 2. Upload image bytes directly to public Cloud Storage bucket
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(img_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "destination_name": destination_name,
            "filename": filename,
            "public_url": public_url,
            "mime_type": mime_type,
        }
    except Exception as e:
        return {"error": f"Failed to generate destination image: {str(e)}"}


async def generate_destination_video(
    prompt: str,
    destination_name: str = "travel_destination",
    tool_context: Optional[ToolContext] = None,
) -> dict[str, Any]:
    """Generates a short video for a travel destination item using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the generated video as an artifact in ToolContext and uploads the video bytes directly to public Cloud Storage.

    Args:
        prompt: Detailed prompt describing the short video scene.
        destination_name: Name of the travel destination or item.
        tool_context: Automatically provided ADK ToolContext for artifact saving.

    Returns:
        A dictionary containing the public Cloud Storage video URL, filename, and status.
    """
    try:
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="global",
        )

        full_prompt = f"Generate a short video snippet for {destination_name}: {prompt}"
        interaction = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=full_prompt,
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(interaction, "output_video") and interaction.output_video:
            video_bytes = getattr(interaction.output_video, "data", None)
            mime_type = getattr(interaction.output_video, "mime_type", None) or mime_type

        if not video_bytes and hasattr(interaction, "outputs") and interaction.outputs:
            for output in interaction.outputs:
                if hasattr(output, "content") and output.content:
                    for part in output.content:
                        if hasattr(part, "inline_data") and part.inline_data:
                            video_bytes = getattr(part.inline_data, "data", None)
                            mime_type = getattr(part.inline_data, "mime_type", None) or mime_type
                            if video_bytes:
                                break

        if not video_bytes:
            return {"error": f"No video bytes generated for '{destination_name}'."}

        safe_name = destination_name.lower().replace(" ", "-")
        filename = f"video-{safe_name}-{uuid.uuid4().hex[:8]}.mp4"

        # 1. Save with tool_context.save_artifact
        if tool_context:
            await tool_context.save_artifact(
                filename=filename,
                artifact=types.Part.from_bytes(data=video_bytes, mime_type=mime_type),
            )

        # 2. Upload video bytes directly to public Cloud Storage bucket
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

        return {
            "status": "success",
            "destination_name": destination_name,
            "filename": filename,
            "public_url": public_url,
            "mime_type": mime_type,
        }
    except Exception as e:
        return {"error": f"Failed to generate destination video: {str(e)}"}

