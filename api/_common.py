import json
import os
from datetime import datetime, timezone, timedelta
from urllib import request, parse

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
MAFIA_ROLES = ("godfather", "mafia", "negotiator")
VALID_SIZES = (8, 10, 12)


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


def post_system_msg(room_id: str, text: str):
    sb_request(
        "POST",
        "messages",
        {
            "room_id": room_id,
            "sender_tg_id": 0,
            "sender_name": "راوی بازی",
            "channel": "system",
            "content": text,
        },
    )


def get_roles(count: int):
    if count == 8:
        return ["godfather", "mafia", "detective", "doctor", "sniper", "bodyguard", "citizen", "citizen"]
    if count == 10:
        return ["godfather", "mafia", "negotiator", "detective", "doctor", "sniper", "bodyguard", "citizen", "citizen", "citizen"]
    if count == 12:
        return ["godfather", "mafia", "negotiator", "detective", "doctor", "sniper", "bodyguard", "citizen", "citizen", "citizen", "citizen", "citizen"]
    return None


def check_win(players):
    alive = [p for p in players if p.get("is_alive")]
    mafia_alive = [p for p in alive if p.get("role") in MAFIA_ROLES]
    town_alive = [p for p in alive if p.get("role") not in MAFIA_ROLES]
    if len(mafia_alive) == 0:
        return "town"
    if len(mafia_alive) >= len(town_alive):
        return "mafia"
    return None


def settle_prize_pool(room: dict, players: list, winner_team: str):
    pool = int(room.get("prize_pool_stars") or 0)
    if pool <= 0:
        return ""
    winners = [
        p for p in players
        if (p.get("role") in MAFIA_ROLES if winner_team == "mafia" else p.get("role") not in MAFIA_ROLES)
    ]
    if not winners:
        return ""
    share = pool // len(winners)
    remainder = pool % len(winners)
    lines = []
    for idx, w in enumerate(winners):
        bonus = share + (1 if idx < remainder else 0)
        lines.append(f"{w['full_name']}: {bonus} ⭐")
    return " | تقسیم صندوق جایزه: " + " ، ".join(lines)


def next_phase_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
