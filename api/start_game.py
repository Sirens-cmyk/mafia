from http.server import BaseHTTPRequestHandler
import json
import os
import random
from datetime import datetime, timezone, timedelta
from urllib import request, parse

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
MAFIA_ROLES = ("godfather", "mafia", "negotiator")
VALID_SIZES = (8, 10, 12)


def sb_request(method: str, path: str, payload=None):
    if not SUPABASE_URL or not SERVICE_KEY:
        raise RuntimeError("متغیرهای SUPABASE_URL یا SUPABASE_SERVICE_ROLE_KEY در Vercel تنظیم نشده‌اند")
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


def get_roles(count: int):
    if count == 8:
        return ["godfather", "mafia", "detective", "doctor", "sniper", "bodyguard", "citizen", "citizen"]
    if count == 10:
        return ["godfather", "mafia", "negotiator", "detective", "doctor", "sniper", "bodyguard", "citizen", "citizen", "citizen"]
    if count == 12:
        return ["godfather", "mafia", "negotiator", "detective", "doctor", "sniper", "bodyguard", "citizen", "citizen", "citizen", "citizen", "citizen"]
    return None


class handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw or "{}")
            room_id = data.get("room_id")
            actor_tg_id = data.get("actor_tg_id")

            if not room_id or not actor_tg_id:
                return self._send_json(400, {"error": "room_id و actor_tg_id الزامی است"})

            rooms = sb_request("GET", f"rooms?id=eq.{parse.quote(str(room_id))}&select=*")
            if not rooms:
                return self._send_json(404, {"error": "اتاق پیدا نشد"})
            room = rooms[0]

            if int(room["host_tg_id"]) != int(actor_tg_id):
                return self._send_json(403, {"error": "فقط سازنده اتاق مجاز به شروع بازی است"})

            players = sb_request("GET", f"players?room_id=eq.{parse.quote(str(room_id))}&order=joined_at.asc")
            raw_cap = room.get("max_players")
            cap = int(raw_cap) if raw_cap in VALID_SIZES else len(players)

            if len(players) not in VALID_SIZES or len(players) != cap:
                return self._send_json(400, {"error": f"میز استاندارد باید دقیقاً {cap} بازیکن (۸، ۱۰ یا ۱۲ نفر) داشته باشد"})

            roles_pool = get_roles(len(players))
            shuffled = roles_pool[:]
            random.shuffle(shuffled)

            for player, role in zip(players, shuffled):
                sb_request(
                    "PATCH",
                    f"players?id=eq.{parse.quote(str(player['id']))}",
                    {
                        "role": role,
                        "is_alive": True,
                        "doctor_self_heal_used": False,
                        "sniper_bullet_left": True,
                        "voted_for_tg_id": None,
                        "night_target_tg_id": None,
                    },
                )

            ends_at = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
            sb_request(
                "PATCH",
                f"rooms?id=eq.{parse.quote(str(room_id))}",
                {
                    "status": "day_talk",
                    "round_number": 1,
                    "phase_ends_at": ends_at,
                },
            )

            sb_request(
                "POST",
                "messages",
                {
                    "room_id": room_id,
                    "sender_tg_id": 0,
                    "sender_name": "راوی بازی",
                    "channel": "system",
                    "content": f"بازی استاندارد {len(players)} نفره آغاز شد! روز اول (۹۰ ثانیه گفتگو) شروع شد.",
                },
            )

            return self._send_json(200, {"ok": True, "status": "day_talk"})
        except Exception as e:
            return self._send_json(500, {"error": f"خطای سرور: {str(e)}"})
            
