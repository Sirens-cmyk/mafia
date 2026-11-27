from http.server import BaseHTTPRequestHandler
import json
import random
from urllib import parse
from _common import sb_request, post_system_msg, check_win, settle_prize_pool, next_phase_iso, MAFIA_ROLES


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

            if action == "set_target":
                if room.get("status") != "night":
                    return self._send_json(400, {"error": "فقط در فاز شب امکان ثبت اکشن وجود دارد"})
                target_tg_id = data.get("target_tg_id")
                actor = next((p for p in players if int(p["tg_id"]) == int(actor_tg_id)), None)
                if not actor or not actor.get("is_alive"):
                    return self._send_json(403, {"error": "بازیکن حذف‌شده اجازه اکشن شب ندارد"})
                target_p = next((p for p in players if int(p["tg_id"]) == int(target_tg_id)), None)
                if not target_p or not target_p.get("is_alive"):
                    return self._send_json(400, {"error": "هدف انتخاب‌شده زنده نیست"})

                role = actor.get("role")
                if role == "sniper" and not actor.get("sniper_bullet_left"):
                    return self._send_json(400, {"error": "تک‌تیرانداز تیر خود را قبلاً مصرف کرده است"})

                if role == "doctor" and int(target_tg_id) == int(actor["tg_id"]):
                    if actor.get("doctor_self_heal_used"):
                        return self._send_json(400, {"error": "دکتر فقط یک بار در کل بازی می‌تواند خودش را نجات دهد"})
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(actor['id']))}",
                        {"night_target_tg_id": int(target_tg_id), "doctor_self_heal_used": True},
                    )
                else:
                    sb_request(
                        "PATCH",
                        f"players?id=eq.{parse.quote(str(actor['id']))}",
                        {"night_target_tg_id": int(target_tg_id)},
                    )

                extra_msg = None
                if role == "detective":
                    t_role = target_p.get("role") or ""
                    verdict = "مثبت (مافیای ساده)" if t_role == "mafia" else "منفی (شهروند / پدرخوانده / مذاکره‌کننده)"
                    extra_msg = f"🕵️ استعلام {target_p['full_name']}: {verdict}"

                return self._send_json(200, {"ok": True, "inquiry": extra_msg})

            if action == "bots_night":
                if not is_host:
                    return self._send_json(403, {"error": "فقط سازنده اتاق مجاز است"})
                alive = [p for p in players if p.get("is_alive")]
                for p in alive:
                    if str(p.get("username", "")).startswith("bot_test_"):
                        if p.get("role") in ("godfather", "mafia", "negotiator", "doctor", "bodyguard"):
                            target = random.choice(alive)
                            sb_request("PATCH", f"players?id=eq.{parse.quote(str(p['id']))}", {"night_target_tg_id": int(target["tg_id"])})
                return self._send_json(200, {"ok": True})

            if action == "resolve_night":
                if not is_host:
                    return self._send_json(403, {"error": "فقط سازنده اتاق مجاز است"})

                mafia_targets = [
                    int(p["night_target_tg_id"])
                    for p in players
                    if p.get("is_alive") and p.get("role") in MAFIA_ROLES and p.get("night_target_tg_id")
                ]
                mafia_shot = mafia_targets[-1] if mafia_targets else None

                doctor_saves = [
                    int(p["night_target_tg_id"])
                    for p in players
                    if p.get("is_alive") and p.get("role") == "doctor" and p.get("night_target_tg_id")
                ]
                saved_id = doctor_saves[-1] if doctor_saves else None

                bodyguards = [
                    p for p in players
                    if p.get("is_alive") and p.get("role") == "bodyguard" and p.get("night_target_tg_id")
                ]
                snipers = [
                    p for p in players
                    if p.get("is_alive") and p.get("role") == "sniper" and p.get("sniper_bullet_left") and p.get("night_target_tg_id")
                ]

                dead_ids = set()
                notes = []

                if mafia_shot and mafia_shot != saved_id:
                    bg_for_target = next((bg for bg in bodyguards if int(bg["night_target_tg_id"]) == mafia_shot), None)
                    if bg_for_target:
                        dead_ids.add(int(bg_for_target["tg_id"]))
                        notes.append(f"محافظ {bg_for_target['full_name']} جلوی شلیک را گرفت و حذف شد")
                    else:
                        dead_ids.add(mafia_shot)

                for sn in snipers:
                    sb_request("PATCH", f"players?id=eq.{parse.quote(str(sn['id']))}", {"sniper_bullet_left": False})
                    t_id = int(sn["night_target_tg_id"])
                    t_player = next((p for p in players if int(p["tg_id"]) == t_id), None)
                    if t_player:
                        if t_player.get("role") in MAFIA_ROLES:
                            dead_ids.add(t_id)
                        else:
                            dead_ids.add(int(sn["tg_id"]))
                            notes.append(f"تک‌تیرانداز {sn['full_name']} هدف اشتباه زد و حذف شد")

                dead_names = []
                for p in players:
                    if int(p["tg_id"]) in dead_ids and p.get("is_alive"):
                        sb_request("PATCH", f"players?id=eq.{parse.quote(str(p['id']))}", {"is_alive": False})
                        p["is_alive"] = False
                        dead_names.append(p["full_name"])

                report = "صبح شد! حذف‌شده‌های شب: " + "، ".join(dead_names) if dead_names else "صبح شد! دیشب هیچ‌کس حذف نشد."
                if notes:
                    report += " (" + "؛ ".join(notes) + ")"
                post_system_msg(room_id, report)

                winner = check_win(players)
                if winner:
                    sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "ended", "phase_ends_at": None})
                    win_msg = ("تیم شهروند برنده شد!" if winner == "town" else "تیم مافیا برنده شد!") + settle_prize_pool(room, players, winner)
                    post_system_msg(room_id, f"🏆 پایان بازی! {win_msg}")
                    return self._send_json(200, {"ok": True, "winner": winner})

                next_round = int(room.get("round_number", 1)) + 1
                sb_request("PATCH", f"rooms?id=eq.{parse.quote(str(room_id))}", {"status": "day_talk", "round_number": next_round, "phase_ends_at": next_phase_iso(90)})
                return self._send_json(200, {"ok": True, "status": "day_talk", "round": next_round})

            return self._send_json(400, {"error": "action نامعتبر است"})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})
