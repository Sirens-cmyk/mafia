const SUPABASE_URL = "https://gdinatfzwqqxjrozkmtp.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_9dzG5wwNBQZS9DkFtdvDvg_lQse46j7"; // کلید Publishable خودت رو اینجا بذار

const ROLE_FA = {
  godfather: "پدرخوانده (مافیا)",
  mafia: "مافیای ساده",
  detective: "کارآگاه (شهروند)",
  doctor: "دکتر (شهروند)",
  sniper: "تک‌تیرانداز (شهروند)",
  citizen: "شهروند ساده"
};

const STATUS_FA = {
  lobby: "لابی",
  day_talk: "روز - گفتگو",
  day_vote: "روز - رای‌گیری",
  night: "شب",
  ended: "پایان بازی"
};

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const tgUser = tg?.initDataUnsafe?.user || {
  id: Math.floor(100000 + Math.random() * 899999),
  first_name: "بازیکن مهمان",
  username: "guest",
  photo_url: ""
};

document.getElementById("userInfo").innerText =
  `بازیکن: ${tgUser.first_name} (ID: ${tgUser.id})`;

const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

let currentRoom = null;
let currentPlayers = [];
let realtimeChannel = null;
let timerInterval = null;

function randomCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let out = "MAF";
  for (let i = 0; i < 4; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out;
}

async function createRoom() {
  const code = randomCode();
  const { data: room, error } = await sb
    .from("rooms")
    .insert({ code, host_tg_id: tgUser.id, status: "lobby" })
    .select()
    .single();
  if (error) return alert("خطا در ساخت اتاق: " + error.message);
  await joinRoomByObject(room);
}

async function joinRoomByCode() {
  const code = document.getElementById("roomCodeInput").value.trim().toUpperCase();
  if (!code) return alert("کد اتاق رو وارد کن");
  const { data: room, error } = await sb.from("rooms").select("*").eq("code", code).single();
  if (error || !room) return alert("اتاقی با این کد پیدا نشد");
  await joinRoomByObject(room);
}

async function joinRoomByObject(room) {
  const { error: pErr } = await sb.from("players").upsert(
    {
      room_id: room.id,
      tg_id: tgUser.id,
      full_name: tgUser.first_name,
      username: tgUser.username || "",
      photo_url: tgUser.photo_url || "",
      is_alive: true
    },
    { onConflict: "room_id,tg_id" }
  );
  if (pErr) return alert("خطا در ورود: " + pErr.message);

  currentRoom = room;
  document.getElementById("homeSection").classList.add("hidden");
  document.getElementById("roomSection").classList.remove("hidden");
  document.getElementById("roomCodeText").innerText = room.code;

  await refreshAll();
  subscribeRealtime(room.id);
}

async function addTestBots() {
  if (!currentRoom) return;
  const needed = 8 - currentPlayers.length;
  if (needed <= 0) return;

  const botRows = [];
  for (let i = 1; i <= needed; i++) {
    const botId = 900000000 + Math.floor(Math.random() * 90000000) + i;
    botRows.push({
      room_id: currentRoom.id,
      tg_id: botId,
      full_name: `بات تست ${i}`,
      username: `bot_test_${i}`,
      is_alive: true
    });
  }
  const { error } = await sb.from("players").insert(botRows);
  if (error) alert("خطا در افزودن بات: " + error.message);
  await refreshAll();
}

async function refreshAll() {
  if (!currentRoom) return;
  const { data: room } = await sb.from("rooms").select("*").eq("id", currentRoom.id).single();
  if (room) {
    currentRoom = room;
    document.getElementById("roomStatusText").innerText = STATUS_FA[room.status] || room.status;
    startCountdown(room.phase_ends_at);
  }

  const { data: players } = await sb
    .from("players")
    .select("*")
    .eq("room_id", currentRoom.id)
    .order("joined_at", { ascending: true });

  currentPlayers = players || [];
  renderPlayers(currentPlayers);
  renderControls();

  const { data: msgs } = await sb
    .from("messages")
    .select("*")
    .eq("room_id", currentRoom.id)
    .order("created_at", { ascending: true })
    .limit(60);

  renderMessages(msgs || []);
}

function renderPlayers(players) {
  document.getElementById("playerCount").innerText = players.length;
  const listEl = document.getElementById("playersList");
  listEl.innerHTML = "";

  let myRole = null;
  for (const p of players) {
    if (Number(p.tg_id) === Number(tgUser.id) && p.role) {
      myRole = p.role;
    }
    const div = document.createElement("div");
    div.className = "player-box" + (p.is_alive ? "" : " dead");
    const voteTag = p.voted_for_tg_id ? " [رای داد]" : "";
    div.innerText = `${p.full_name} (${p.is_alive ? "زنده" : "حذف"})${voteTag}`;
    listEl.appendChild(div);
  }

  const roleBox = document.getElementById("myRoleBox");
  if (myRole) {
    roleBox.classList.remove("hidden");
    document.getElementById("myRoleText").innerText = "نقش شما: " + (ROLE_FA[myRole] || myRole);
  } else {
    roleBox.classList.add("hidden");
  }
}

function renderControls() {
  const isHost = Number(currentRoom.host_tg_id) === Number(tgUser.id);
  const status = currentRoom.status;

  document.getElementById("addBotsBtn").classList.toggle("hidden", !(isHost && status === "lobby" && currentPlayers.length < 8));
  document.getElementById("startGameBtn").classList.toggle("hidden", !(isHost && status === "lobby" && currentPlayers.length === 8));
  document.getElementById("startVoteBtn").classList.toggle("hidden", !(isHost && status === "day_talk"));
  document.getElementById("finishVoteBtn").classList.toggle("hidden", !(isHost && status === "day_vote"));
  document.getElementById("resolveNightBtn").classList.toggle("hidden", !(isHost && status === "night"));

  const aliveTargets = currentPlayers.filter((p) => p.is_alive);

  const voteSec = document.getElementById("voteSection");
  voteSec.classList.toggle("hidden", status !== "day_vote");
  const voteSel = document.getElementById("voteTargetSelect");
  voteSel.innerHTML = "";
  for (const t of aliveTargets) {
    const opt = document.createElement("option");
    opt.value = t.tg_id;
    opt.innerText = t.full_name;
    voteSel.appendChild(opt);
  }

  const nightSec = document.getElementById("nightSection");
  nightSec.classList.toggle("hidden", status !== "night");
  const nightSel = document.getElementById("nightTargetSelect");
  nightSel.innerHTML = "";
  for (const t of aliveTargets) {
    const opt = document.createElement("option");
    opt.value = t.tg_id;
    opt.innerText = t.full_name;
    nightSel.appendChild(opt);
  }
}

function renderMessages(msgs) {
  const box = document.getElementById("chatBox");
  box.innerHTML = "";
  for (const m of msgs) {
    const div = document.createElement("div");
    div.className = "msg" + (m.channel === "system" ? " system" : "");
    div.innerText = m.channel === "system" ? `🔔 ${m.content}` : `${m.sender_name}: ${m.content}`;
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

async function sendMessage() {
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text || !currentRoom) return;
  await sb.from("messages").insert({
    room_id: currentRoom.id,
    sender_tg_id: tgUser.id,
    sender_name: tgUser.first_name,
    channel: "public",
    content: text
  });
  input.value = "";
}

async function callApi(endpoint, payload) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!res.ok) alert(data.error || "خطا در اجرای عملیات");
  return data;
}

async function startGame() {
  await callApi("/api/start_game", { room_id: currentRoom.id, host_tg_id: tgUser.id });
}

async function startVote() {
  await callApi("/api/day_vote", { room_id: currentRoom.id, action: "start_vote" });
}

async function castVote() {
  const targetId = document.getElementById("voteTargetSelect").value;
  const data = await callApi("/api/day_vote", {
    room_id: currentRoom.id,
    action: "cast_vote",
    actor_tg_id: tgUser.id,
    target_tg_id: targetId
  });
  if (data.ok) alert("رای شما ثبت شد");
}

async function finishVote() {
  await callApi("/api/day_vote", { room_id: currentRoom.id, action: "finish_vote" });
}

async function submitNightAction() {
  const targetId = document.getElementById("nightTargetSelect").value;
  const data = await callApi("/api/night_action", {
    room_id: currentRoom.id,
    action: "set_target",
    actor_tg_id: tgUser.id,
    target_tg_id: targetId
  });
  if (data.inquiry) {
    document.getElementById("inquiryResult").innerText = data.inquiry;
  } else if (data.ok) {
    document.getElementById("inquiryResult").innerText = "هدف شب ثبت شد.";
  }
}

async function resolveNight() {
  document.getElementById("inquiryResult").innerText = "";
  await callApi("/api/night_action", { room_id: currentRoom.id, action: "resolve_night" });
}

function startCountdown(endsAtIso) {
  if (timerInterval) clearInterval(timerInterval);
  const el = document.getElementById("timerText");
  if (!endsAtIso) {
    el.innerText = "--:--";
    return;
  }
  const target = new Date(endsAtIso).getTime();
  timerInterval = setInterval(() => {
    const diff = Math.max(0, Math.floor((target - Date.now()) / 1000));
    const m = String(Math.floor(diff / 60)).padStart(2, "0");
    const s = String(diff % 60).padStart(2, "0");
    el.innerText = `${m}:${s}`;
  }, 500);
}

function subscribeRealtime(roomId) {
  if (realtimeChannel) sb.removeChannel(realtimeChannel);
  realtimeChannel = sb
    .channel("room-" + roomId)
    .on("postgres_changes", { event: "*", schema: "public", table: "rooms", filter: `id=eq.${roomId}` }, refreshAll)
    .on("postgres_changes", { event: "*", schema: "public", table: "players", filter: `room_id=eq.${roomId}` }, refreshAll)
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "messages", filter: `room_id=eq.${roomId}` }, refreshAll)
    .subscribe();
}

function leaveRoom() {
  if (realtimeChannel) sb.removeChannel(realtimeChannel);
  currentRoom = null;
  document.getElementById("roomSection").classList.add("hidden");
  document.getElementById("homeSection").classList.remove("hidden");
}

document.getElementById("createRoomBtn").addEventListener("click", createRoom);
document.getElementById("joinRoomBtn").addEventListener("click", joinRoomByCode);
document.getElementById("addBotsBtn").addEventListener("click", addTestBots);
document.getElementById("startGameBtn").addEventListener("click", startGame);
document.getElementById("startVoteBtn").addEventListener("click", startVote);
document.getElementById("castVoteBtn").addEventListener("click", castVote);
document.getElementById("finishVoteBtn").addEventListener("click", finishVote);
document.getElementById("nightActionBtn").addEventListener("click", submitNightAction);
document.getElementById("resolveNightBtn").addEventListener("click", resolveNight);
document.getElementById("sendMsgBtn").addEventListener("click", sendMessage);
document.getElementById("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
document.getElementById("leaveRoomBtn").addEventListener("click", leaveRoom);
                                                                       
