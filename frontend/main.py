"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.

Run:
  export AGENT_ENGINE_RESOURCE_NAME="projects/.../locations/.../reasoningEngines/..."
  export AGENT_DIRECTORY="app"   # your agent's app directory (agents-cli-manifest.yaml)
  python main.py                 # -> http://localhost:8080
"""

import json
import os
import re
import uuid

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ["AGENT_ENGINE_RESOURCE_NAME"]
# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
# Location is embedded in the resource name: projects/<p>/locations/<loc>/reasoningEngines/<id>.
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

# A2A endpoint for an Agent Runtime deployment, via the Agent Engine HTTP passthrough.
A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"

# The agent tags its A2UI data parts with this mime type or encloses them in <a2ui-json>.
_A2UI_MIME = "application/json+a2ui"
_A2UI_REGEX = re.compile(r"<a2ui-json>\s*(.*?)\s*</a2ui-json>", re.DOTALL)

# One set of ADC credentials, refreshed per request.
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE A2A context per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}


def _extract_parts(parts: list) -> list[dict]:
    out: list[dict] = []
    for p in parts:
        if isinstance(p, dict):
            mime = p.get("mimeType") or (p.get("metadata", {}) or {}).get("mimeType")
            text = p.get("text")
            data = p.get("data")
            file_info = p.get("file") or {}
            uri = file_info.get("uri") if isinstance(file_info, dict) else None

            if mime == _A2UI_MIME and data is not None:
                out.append({"kind": "a2ui", "data": data})
            elif text:
                matches = list(_A2UI_REGEX.finditer(text))
                if matches:
                    last_end = 0
                    for match in matches:
                        before = text[last_end:match.start()].strip()
                        if before:
                            out.append({"kind": "text", "text": before})
                        try:
                            a2ui_data = json.loads(match.group(1))
                            out.append({"kind": "a2ui", "data": a2ui_data})
                        except Exception:
                            out.append({"kind": "text", "text": match.group(0)})
                        last_end = match.end()
                    after = text[last_end:].strip()
                    if after:
                        out.append({"kind": "text", "text": after})
                else:
                    out.append({"kind": "text", "text": text})
            elif uri:
                out.append({"kind": "text", "text": uri})
    return out


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    msg_payload = {
        "message_id": str(uuid.uuid4()),
        "role": "user",
        "parts": [{"text": message}],
    }
    if _contexts.get(user_id):
        msg_payload["context_id"] = _contexts[user_id]

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": msg_payload
        },
    }

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        resp = await client.post(A2A_BASE, json=payload)
        resp.raise_for_status()
        res_data = resp.json()

        result = res_data.get("result", {})
        context_id = result.get("contextId")
        if context_id:
            _contexts[user_id] = context_id

        artifacts = result.get("artifacts", [])
        for artifact in artifacts:
            parts.extend(_extract_parts(artifact.get("parts", [])))

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


# Serve the chat UI (keep this mount last so /chat wins).
app.mount("/", StaticFiles(directory="frontend/static" if os.path.exists("frontend/static") else "static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
