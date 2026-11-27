from http.server import BaseHTTPRequestHandler
import json
import random
from datetime import datetime, timezone, timedelta
from urllib import parse
from _common import sb_request, post_message, check_win


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

            if not room_id or not action:
                return self._send_json(400, {"error": "room_id و action الزامی است"})

            rooms = sb_request("GET", f"rooms?id=eq.{parse.quote(str(room_id))}&select=*")
            if not rooms:
                return self._send_json(404, {"error": "اتاق پیدا نشد"})
            room = rooms[0]

            players = sb_request("GET", f"players?room_id=eq.{parse.quote(str(room_id))}&select=*")
            actor = next((p for p in players if int(p["tg_id"]) == int(actor_tg_id)), None) if actor_tg_id else None
            is_mod_or_host = (actor_tg_id and int(room["host_tg_id"]) == int(actor_tg_id)) or (
                actor and actor.get("role") == "moderator"
            )

            if action == "start_vote":
                if not is_mod_or_host:
                    return self._send_json(403, {"error": "فقط گرداننده یا هاست می‌تونه رای‌گیری رو شروع کنه"})
                for p in players:
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(p['id']))}",
                        {"voted_for_tg_id": None},
                    )
                ends_at = (datetime.now(timezone.utc) + timedelta(seconds=75)).isoformat()
                sb_request(
                    "PATCH",
                    f"rooms?id=eq.{parse.quote(str(room_id))}",
                    {"status": "day_vote", "phase_ends_at": ends_at},
                )
                post_message(room_id, "رای‌گیری روز شروع شد! هر بازیکن زنده به فرد مظنون رای بدهد.", channel="system")
                return self._send_json(200, {"ok": True, "status": "day_vote"})

            if action == "cast_vote":
                target_tg_id = data.get("target_tg_id")
                if not actor or not actor.get("is_alive") or actor.get("role") == "moderator":
                    return self._send_json(403, {"error": "فقط بازیکن زنده می‌تونه رای بده"})
                sb_request(
                    "PATCH",
                    f"players?id=eq.{parse.quote(str(actor['id']))}",
                    {"voted_for_tg_id": int(target_tg_id) if target_tg_id else None},
                )
                return self._send_json(200, {"ok": True})

            if action == "bots_vote":
                if not is_mod_or_host:
                    return self._send_json(403, {"error": "فقط گرداننده یا هاست مجاز است"})
                alive = [p for p in players if p.get("is_alive") and p.get("role") != "moderator"]
                if len(alive) < 2:
                    return self._send_json(400, {"error": "بازیکن زنده کافی نیست"})
                for p in alive:
                    if str(p.get("username", "")).startswith("bot_test_"):
                        candidates = [x for x in alive if int(x["tg_id"]) != int(p["tg_id"])]
                        if candidates:
                            chosen = random.choice(candidates)
                            sb_request(
                                "PATCH",
                                f"players?id=eq.{parse.quote(str(p['id']))}",
                                {"voted_for_tg_id": int(chosen["tg_id"])},
                            )
                return self._send_json(200, {"ok": True})

            if action == "finish_vote":
                if not is_mod_or_host:
                    return self._send_json(403, {"error": "فقط گرداننده یا هاست می‌تونه رای‌گیری رو ببنده"})
                counts = {}
                for p in players:
                    if p.get("is_alive") and p.get("role") != "moderator" and p.get("voted_for_tg_id"):
                        tid = int(p["voted_for_tg_id"])
                        counts[tid] = counts.get(tid, 0) + 1

                eliminated_player = None
                if counts:
                    max_votes = max(counts.values())
                    top_targets = [tid for tid, c in counts.items() if c == max_votes]
                    if len(top_targets) == 1:
                        eliminated_player = next(
                            (p for p in players if int(p["tg_id"]) == top_targets[0]), None
                        )

                if eliminated_player:
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(eliminated_player['id']))}",
                        {"is_alive": False},
                    )
                    eliminated_player["is_alive"] = False
                    post_message(
                        room_id,
                        f"با رای شهر، {eliminated_player['full_name']} از بازی خارج شد.",
                        channel="system",
                    )
                else:
                    post_message(
                        room_id,
                        "رای‌گیری مساوی شد یا کسی رای نداد؛ هیچ‌کس از شهر خارج نشد.",
                        channel="system",
                    )

                winner = check_win(players)
                if winner:
                    sb_request(
                        "PATCH",
                        f"rooms?id=eq.{parse.quote(str(room_id))}",
                        {"status": "ended", "phase_ends_at": None},
                    )
                    win_msg = "تیم شهروند برنده بازی شد!" if winner == "town" else "تیم مافیا برنده بازی شد!"
                    post_message(room_id, f"🏆 پایان بازی! {win_msg}", channel="system")
                    return self._send_json(200, {"ok": True, "winner": winner})

                for p in players:
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(p['id']))}",
                        {"night_target_tg_id": None},
                    )

                ends_at = (datetime.now(timezone.utc) + timedelta(seconds=75)).isoformat()
                sb_request(
                    "PATCH",
                    f"rooms?id=eq.{parse.quote(str(room_id))}",
                    {"status": "night", "phase_ends_at": ends_at},
                )
                post_message(
                    room_id,
                    "شب شد! بادیگارد محافظت کنه، دکتر نجات بده، کارآگاه استعلام بگیره، مافیا هدف بزنه و اسنایپر تصمیم بگیره.",
                    channel="system",
                )
                return self._send_json(200, {"ok": True, "status": "night"})

            return self._send_json(400, {"error": "action نامعتبر است"})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})
