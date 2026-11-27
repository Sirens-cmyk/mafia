import json
import os
from urllib import request, parse

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def sb_request(method: str, path: str, payload=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


def post_message(room_id: str, content: str, channel: str = "system", sender_tg_id: int = 0, sender_name: str = "گرداننده (AI)"):
    sb_request(
        "POST",
        "messages",
        {
            "room_id": room_id,
            "sender_tg_id": sender_tg_id,
            "sender_name": sender_name,
            "channel": channel,
            "content": content,
        },
    )


def get_roles_for_count(count: int):
    if count == 8:
        return [
            "godfather",
            "mafia",
            "detective",
            "doctor",
            "sniper",
            "bodyguard",
            "citizen",
            "citizen",
        ]
    if count == 10:
        return [
            "godfather",
            "mafia",
            "negotiator",
            "detective",
            "doctor",
            "sniper",
            "bodyguard",
            "citizen",
            "citizen",
            "citizen",
        ]
    if count == 12:
        return [
            "godfather",
            "mafia",
            "negotiator",
            "detective",
            "doctor",
            "sniper",
            "bodyguard",
            "citizen",
            "citizen",
            "citizen",
            "citizen",
            "citizen",
        ]
    return None


def check_win(players):
    alive = [p for p in players if p.get("is_alive") and p.get("role") != "moderator"]
    mafia_alive = [p for p in alive if p.get("role") in ("godfather", "mafia", "negotiator")]
    town_alive = [p for p in alive if p.get("role") not in ("godfather", "mafia", "negotiator")]
    if len(mafia_alive) == 0:
        return "town"
    if len(mafia_alive) >= len(town_alive):
        return "mafia"
    return None
