from http.server import BaseHTTPRequestHandler
import json
import os
from datetime import datetime, timezone, timedelta
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


def check_win(players):
    alive = [p for p in players if p.get("is_alive")]
    mafia_alive = [p for p in alive if p.get("role") in ("godfather", "mafia")]
    town_alive = [p for p in alive if p.get("role") not in ("godfather", "mafia")]
    if len(mafia_alive) == 0:
        return "town"
    if len(mafia_alive) >= len(town_alive):
        return "mafia"
    return None


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
            action = data.get("action")
            actor_tg_id = data.get("actor_tg_id")

            rooms = sb_request("GET", f"rooms?id=eq.{parse.quote(str(room_id))}&select=*")
            if not rooms:
                return self._send_json(404, {"error": "اتاق پیدا نشد"})
            room = rooms[0]

            players = sb_request("GET", f"players?room_id=eq.{parse.quote(str(room_id))}&select=*")

            if action == "set_target":
                target_tg_id = data.get("target_tg_id")
                actor = next((p for p in players if int(p["tg_id"]) == int(actor_tg_id)), None)
                if not actor or not actor.get("is_alive"):
                    return self._send_json(403, {"error": "بازیکن معتبر نیست"})

                role = actor.get("role")
                if role == "doctor" and int(target_tg_id) == int(actor["tg_id"]):
                    if actor.get("doctor_self_heal_used"):
                        return self._send_json(400, {"error": "دکتر فقط یک بار می‌تونه خودش رو نجات بده"})
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(actor['id']))}",
                        {"night_target_tg_id": int(target_tg_id), "doctor_self_heal_used": True},
                    )
                else:
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(actor['id']))}",
                        {"night_target_tg_id": int(target_tg_id) if target_tg_id else None},
                    )

                extra_msg = None
                if role == "detective":
                    target_p = next((p for p in players if int(p["tg_id"]) == int(target_tg_id)), None)
                    t_role = target_p.get("role") if target_p else ""
                    is_pos = t_role in ("mafia",)  # پدرخوانده منفی است
                    verdict = "مثبت (مافیا)" if is_pos else "منفی (شهروند/پدرخوانده)"
                    extra_msg = f"🕵️ استعلام {target_p['full_name'] if target_p else ''}: {verdict}"

                return self._send_json(200, {"ok": True, "inquiry": extra_msg})

            if action == "resolve_night":
                mafia_targets = [
                    int(p["night_target_tg_id"])
                    for p in players
                    if p.get("is_alive") and p.get("role") in ("godfather", "mafia") and p.get("night_target_tg_id")
                ]
                mafia_shot = mafia_targets[-1] if mafia_targets else None

                doctor_saves = [
                    int(p["night_target_tg_id"])
                    for p in players
                    if p.get("is_alive") and p.get("role") == "doctor" and p.get("night_target_tg_id")
                ]
                saved_id = doctor_saves[-1] if doctor_saves else None

                snipers = [
                    p for p in players
                    if p.get("is_alive") and p.get("role") == "sniper" and p.get("sniper_bullet_left") and p.get("night_target_tg_id")
                ]

                dead_ids = set()
                if mafia_shot and mafia_shot != saved_id:
                    dead_ids.add(mafia_shot)

                for sn in snipers:
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(sn['id']))}",
                        {"sniper_bullet_left": False},
                    )
                    t_id = int(sn["night_target_tg_id"])
                    t_player = next((p for p in players if int(p["tg_id"]) == t_id), None)
                    if t_player:
                        if t_player.get("role") in ("godfather", "mafia"):
                            dead_ids.add(t_id)
                        else:
                            dead_ids.add(int(sn["tg_id"]))

                dead_names = []
                for p in players:
                    if int(p["tg_id"]) in dead_ids and p.get("is_alive"):
                        sb_request(
                            "PATCH",
                            f"players?id=eq.{parse.quote(str(p['id']))}",
                            {"is_alive": False},
                        )
                        p["is_alive"] = False
                        dead_names.append(p["full_name"])

                if dead_names:
                    report = "صبح شد! دیشب این افراد از بازی خارج شدند: " + "، ".join(dead_names)
                else:
                    report = "صبح شد! دیشب هیچ‌کس کشته نشد."

                sb_request(
                    "POST",
                    "messages",
                    {
                        "room_id": room_id,
                        "sender_tg_id": 0,
                        "sender_name": "راوی",
                        "channel": "system",
                        "content": report,
                    },
                )

                winner = check_win(players)
                if winner:
                    sb_request(
                        "PATCH",
                        f"rooms?id=eq.{parse.quote(str(room_id))}",
                        {"status": "ended", "phase_ends_at": None},
                    )
                    win_msg = "تیم شهروند برنده بازی شد!" if winner == "town" else "تیم مافیا برنده بازی شد!"
                    sb_request(
                        "POST",
                        "messages",
                        {
                            "room_id": room_id,
                            "sender_tg_id": 0,
                            "sender_name": "راوی",
                            "channel": "system",
                            "content": f"🏆 پایان بازی! {win_msg}",
                        },
                    )
                    return self._send_json(200, {"ok": True, "winner": winner})

                next_round = int(room.get("round_number", 1)) + 1
                ends_at = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
                sb_request(
                    "PATCH",
                    f"rooms?id=eq.{parse.quote(str(room_id))}",
                    {"status": "day_talk", "round_number": next_round, "phase_ends_at": ends_at},
                )
                return self._send_json(200, {"ok": True, "status": "day_talk", "round": next_round})

            return self._send_json(400, {"error": "action نامعتبر است"})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})
          
