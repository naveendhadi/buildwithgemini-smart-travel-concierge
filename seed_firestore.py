import subprocess
import google.auth
import google.oauth2.credentials
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-02-0170751dd1c4"

SEED_DESTINATIONS = [
    {
        "id": "dest-tokyo-01",
        "name": "Tokyo",
        "country": "Japan",
        "description": "Vibrant capital known for high-tech culture, traditional temples, and world-class cuisine.",
        "price_per_day_usd": 180.0,
        "category": "Culture & Urban",
        "popular_spots": ["Shibuya Crossing", "Senso-ji Temple", "Tsukiji Outer Market"],
        "best_season": "Spring / Autumn",
    },
    {
        "id": "dest-paris-02",
        "name": "Paris",
        "country": "France",
        "description": "The City of Light, iconic for romance, art, fashion, and haute cuisine.",
        "price_per_day_usd": 220.0,
        "category": "Romance & Art",
        "popular_spots": ["Eiffel Tower", "Louvre Museum", "Montmartre"],
        "best_season": "Spring / Fall",
    },
    {
        "id": "dest-kyoto-03",
        "name": "Kyoto",
        "country": "Japan",
        "description": "Japan's ancient capital, famous for classical Buddhist temples, gardens, and imperial palaces.",
        "price_per_day_usd": 150.0,
        "category": "Historic & Culture",
        "popular_spots": ["Fushimi Inari Shrine", "Kinkaku-ji (Golden Pavilion)", "Arashiyama Bamboo Grove"],
        "best_season": "Spring (Cherry Blossoms) / Autumn",
    },
    {
        "id": "dest-bali-04",
        "name": "Bali",
        "country": "Indonesia",
        "description": "Tropical paradise featuring volcanic mountains, iconic rice paddies, beaches, and coral reefs.",
        "price_per_day_usd": 95.0,
        "category": "Beach & Wellness",
        "popular_spots": ["Ubud Monkey Forest", "Uluwatu Temple", "Tegallalang Rice Terraces"],
        "best_season": "Dry Season (April - October)",
    },
    {
        "id": "dest-swiss-05",
        "name": "Swiss Alps",
        "country": "Switzerland",
        "description": "Breathtaking alpine landscapes, world-class skiing, hiking trails, and picturesque mountain villages.",
        "price_per_day_usd": 280.0,
        "category": "Nature & Adventure",
        "popular_spots": ["Matterhorn", "Jungfraujoch", "Interlaken"],
        "best_season": "Winter (Skiing) / Summer (Hiking)",
    },
]


def get_firestore_client():
    try:
        # Try standard Client initialization first
        client = firestore.Client(project=PROJECT_ID)
        # Verify write capability
        client.collection("_ping").document("ping").set({"status": "ok"})
        return client
    except Exception:
        # Fallback to gcloud user access token if running in local workstation environment
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        creds = google.oauth2.credentials.Credentials(token)
        return firestore.Client(project=PROJECT_ID, credentials=creds)


def seed_database():
    print(f"Connecting to Firestore for project: {PROJECT_ID}...")
    db = get_firestore_client()
    collection_ref = db.collection("destinations")

    for dest in SEED_DESTINATIONS:
        doc_ref = collection_ref.document(dest["id"])
        doc_ref.set(dest)
        print(f"Seeded document: {dest['id']} ({dest['name']}, {dest['country']})")

    print("\n✅ Firestore seeding completed successfully!")


if __name__ == "__main__":
    seed_database()
