from http.server import BaseHTTPRequestHandler
import json
import os
import random
from datetime import datetime, timezone, timedelta
from urllib import request, parse

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
MAFIA_ROLES = ("godfather", "mafia", "negotiator")


def sb_request(method: str, path: str, payload=None):
    if not SUPABASE_URL or not SERVICE_KEY:
        raise RuntimeError("متغیرهای SUPABASE_URL یا SUPABASE_SERVICE_ROLE_KEY تنظیم نشده‌اند")
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

            rooms = sb_request("GET", f"rooms?id=eq.{parse.quote(str(room_id))}&select=*")
            if not rooms:
                return self._send_json(404, {"error": "اتاق پیدا نشد"})
            room = rooms[0]
            is_host = actor_tg_id and int(room["host_tg_id"]) == int(actor_tg_id)
            players = sb_request("GET", f"players?room_id=eq.{parse.quote(str(room_id))}&select=*")

            if action == "start_vote":
                if not is_host:
                    return self._send_json(403, {"error": "فقط سازنده اتاق مجاز است"})
                for p in players:
                    sb_request("PATCH", f"players?id=eq.{parse.quote(str(p['id']))}", {"voted_for_tg_id": None})
                sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "day_vote", "phase_ends_at": next_phase_iso(60)})
                post_system_msg(room_id, "رای‌گیری روز آغاز شد! هر بازیکن زنده فقط یک رای معتبر دارد.")
                return self._send_json(200, {"ok": True, "status": "day_vote"})

            if action == "cast_vote":
                if room.get("status") != "day_vote":
                    return self._send_json(400, {"error": "در حال حاضر فاز رای‌گیری فعال نیست"})
                target_tg_id = data.get("target_tg_id")
                voter = next((p for p in players if int(p["tg_id"]) == int(actor_tg_id)), None)
                if not voter or not voter.get("is_alive"):
                    return self._send_json(403, {"error": "بازیکن حذف‌شده حق رای ندارد"})
                target = next((p for p in players if int(p["tg_id"]) == int(target_tg_id)), None)
                if not target or not target.get("is_alive"):
                    return self._send_json(400, {"error": "فقط می‌توان به بازیکن زنده رای داد"})
                sb_request("PATCH", f"players?id=eq.{parse.quote(str(voter['id']))}", {"voted_for_tg_id": int(target_tg_id)})
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
                    return self._send_json(403, {"error": "فقط سازنده اتاق مجاز است"})
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
                    post_system_msg(room_id, f"با رای اکثریت شهر، {eliminated_player['full_name']} حذف شد.")
                else:
                    post_system_msg(room_id, "آرا مساوی شد یا رایی ثبت نشد؛ طبق قانون، هیچ‌کس حذف نشد.")

                winner = check_win(players)
                if winner:
                    sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "ended", "phase_ends_at": None})
                    win_msg = ("تیم شهروند برنده شد!" if winner == "town" else "تیم مافیا برنده شد!") + settle_prize_pool(room, players, winner)
                    post_system_msg(room_id, f"🏆 پایان بازی! {win_msg}")
                    return self._send_json(200, {"ok": True, "winner": winner})

                for p in players:
                    sb_request("PATCH", f"players?id=eq.{parse.quote(str(p['id']))}", {"night_target_tg_id": None})
                sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "night", "phase_ends_at": next_phase_iso(60)})
                post_system_msg(room_id, "شب شد! اکشن‌های شب را با دقت انجام دهید.")
                return self._send_json(200, {"ok": True, "status": "night"})

            return self._send_json(400, {"error": "action نامعتبر است"})
        except Exception as e:
            return self._send_json(500, {"error": f"خطای سرور: {str(e)}"})
