from http.server import BaseHTTPRequestHandler
import json
import os
import random
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


def check_win(players):
    alive = [p for p in players if p.get("is_alive")]
    mafia_alive = [p for p in alive if p.get("role") in ("godfather", "mafia", "negotiator")]
    town_alive = [p for p in alive if p.get("role") not in ("godfather", "mafia", "negotiator")]
    if len(mafia_alive) == 0:
        return "town"
    if len(mafia_alive) >= len(town_alive):
        return "mafia"
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
            action = data.get("action")
            actor_tg_id = data.get("actor_tg_id")

            if not room_id or not action:
                return self._send_json(400, {"error": "room_id و action الزامی است"})

            rooms = sb_request("GET", f"rooms?id=eq.{parse.quote(str(room_id))}&select=*")
            if not rooms:
                return self._send_json(404, {"error": "اتاق پیدا نشد"})
            room = rooms[0]
            is_host = actor_tg_id and int(room["host_tg_id"]) == int(actor_tg_id)

            players = sb_request("GET", f"players?room_id=eq.{parse.quote(str(room_id))}&select=*")

            if action == "start_vote":
                if not is_host:
                    return self._send_json(403, {"error": "فقط سازنده اتاق می‌تونه رای‌گیری رو شروع کنه"})
                for p in players:
                    sb_request("PATCH", f"players?id=eq.{parse.quote(str(p['id']))}", {"voted_for_tg_id": None})
                ends_at = (datetime.now(timezone.utc) + timedelta(seconds=75)).isoformat()
                sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "day_vote", "phase_ends_at": ends_at})
                post_system_msg(room_id, "رای‌گیری روز شروع شد! هر بازیکن زنده به فرد مظنون رای بدهد.")
                return self._send_json(200, {"ok": True, "status": "day_vote"})

            if action == "cast_vote":
                target_tg_id = data.get("target_tg_id")
                voter = next((p for p in players if int(p["tg_id"]) == int(actor_tg_id)), None)
                if not voter or not voter.get("is_alive"):
                    return self._send_json(403, {"error": "فقط بازیکن زنده می‌تونه رای بده"})
                sb_request(
                    "PATCH",
                    f"players?id=eq.{parse.quote(str(voter['id']))}",
                    {"voted_for_tg_id": int(target_tg_id) if target_tg_id else None},
                )
                return self._send_json(200, {"ok": True})

            if action == "bots_vote":
                if not is_host:
                    return self._send_json(403, {"error": "فقط سازنده اتاق مجاز است"})
                alive = [p for p in players if p.get("is_alive")]
                for p in alive:
                    if str(p.get("username", "")).startswith("bot_test_"):
                        candidates = [x for x in alive if int(x["tg_id"]) != int(p["tg_id"])]
                        if candidates:
                            chosen = random.choice(candidates)
                            sb_request("PATCH", f"players?id=eq.{parse.quote(str(p['id']))}", {"voted_for_tg_id": int(chosen["tg_id"])})
                return self._send_json(200, {"ok": True})

            if action == "finish_vote":
                if not is_host:
                    return self._send_json(403, {"error": "فقط سازنده اتاق می‌تونه رای‌گیری رو ببنده"})
                counts = {}
                for p in players:
                    if p.get("is_alive") and p.get("voted_for_tg_id"):
                        tid = int(p["voted_for_tg_id"])
                        counts[tid] = counts.get(tid, 0) + 1

                eliminated_player = None
                if counts:
                    max_votes = max(counts.values())
                    top_targets = [tid for tid, c in counts.items() if c == max_votes]
                    if len(top_targets) == 1:
                        eliminated_player = next((p for p in players if int(p["tg_id"]) == top_targets[0]), None)

                if eliminated_player:
                    sb_request("PATCH", f"players?id=eq.{parse.quote(str(eliminated_player['id']))}", {"is_alive": False})
                    eliminated_player["is_alive"] = False
                    post_system_msg(room_id, f"با رای شهر، {eliminated_player['full_name']} از بازی خارج شد.")
                else:
                    post_system_msg(room_id, "رای‌گیری مساوی شد یا کسی رای نداد؛ هیچ‌کس از شهر خارج نشد.")

                winner = check_win(players)
                if winner:
                    sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "ended", "phase_ends_at": None})
                    win_msg = "تیم شهروند برنده بازی شد!" if winner == "town" else "تیم مافیا برنده بازی شد!"
                    post_system_msg(room_id, f"🏆 پایان بازی! {win_msg}")
                    return self._send_json(200, {"ok": True, "winner": winner})

                for p in players:
                    sb_request("PATCH", f"players?id=eq.{parse.quote(str(p['id']))}", {"night_target_tg_id": None})

                ends_at = (datetime.now(timezone.utc) + timedelta(seconds=75)).isoformat()
                sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "night", "phase_ends_at": ends_at})
                post_system_msg(room_id, "شب شد! نقش‌های شب اکشن خود را انجام دهند.")
                return self._send_json(200, {"ok": True, "status": "night"})

            return self._send_json(400, {"error": "action نامعتبر است"})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})
            
