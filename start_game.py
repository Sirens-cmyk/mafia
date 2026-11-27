from http.server import BaseHTTPRequestHandler
import json
import random
from datetime import datetime, timezone, timedelta
from urllib import parse
from _common import sb_request, post_message, get_roles_for_count


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, obj: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

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

            players = sb_request("GET", f"players?room_id=eq.{parse.quote(str(room_id))}&order=joined_at.asc")
            actor = next((p for p in players if int(p["tg_id"]) == int(actor_tg_id)), None)

            is_host = int(room["host_tg_id"]) == int(actor_tg_id)
            is_mod = actor and actor.get("role") == "moderator"
            if not (is_host or is_mod):
                return self._send_json(403, {"error": "فقط گرداننده یا سازنده اتاق می‌تونه بازی رو شروع کنه"})

            game_players = [p for p in players if p.get("role") != "moderator"]
            roles_pool = get_roles_for_count(len(game_players))
            if not roles_pool:
                return self._send_json(
                    400,
                    {"error": f"تعداد بازیکنان باید ۸، ۱۰ یا ۱۲ نفر باشد (الان {len(game_players)} نفر هستند)"}
                )

            shuffled = roles_pool[:]
            random.shuffle(shuffled)

            for player, role in zip(game_players, shuffled):
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

            ends_at = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
            sb_request(
                "PATCH",
                f"rooms?id=eq.{parse.quote(str(room_id))}",
                {
                    "status": "day_talk",
                    "round_number": 1,
                    "phase_ends_at": ends_at,
                },
            )

            post_message(
                room_id,
                f"بازی {len(game_players)} نفره شروع شد! نقش‌ها مخفیانه پخش شدن؛ روز اول (۱۲۰ ثانیه بحث و چالش) آغاز شد.",
                channel="system",
            )

            return self._send_json(200, {"ok": True, "status": "day_talk", "player_count": len(game_players)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})
