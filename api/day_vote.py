from http.server import BaseHTTPRequestHandler
import json
import random
from urllib import parse
from _common import sb_request, post_system_msg, check_win, settle_prize_pool, next_phase_iso


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
            return self._send_json(500, {"error": str(e)})
