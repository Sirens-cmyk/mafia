const SUPABASE_URL = "https://gdinatfzwqqxjrozkmtp.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_..."; // کلید Publishable خودت رو اینجا بذار

const ROLE_FA = {
  godfather: "پدرخوانده (مافیا)",
  mafia: "مافیای ساده",
  detective: "کارآگاه (شهروند)",
  doctor: "دکتر (شهروند)",
  sniper: "تک‌تیرانداز (شهروند)",
  citizen: "شهروند ساده"
};

const STATUS_FA = {
  lobby: "در انتظار بازیکن",
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

  const { data: room, error } = await sb
    .from("rooms")
    .select("*")
    .eq("code", code)
    .single();

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

  if (pErr) return alert("خطا در ورود به اتاق: " + pErr.message);

  currentRoom = room;
  document.getElementById("homeSection").classList.add("hidden");
  document.getElementById("roomSection").classList.remove("hidden");
  document.getElementById("roomCodeText").innerText = room.code;

  await refreshAll();
  subscribeRealtime(room.id);
}

async function refreshAll() {
  if (!currentRoom) return;

  const { data: room } = await sb
    .from("rooms")
    .select("*")
    .eq("id", currentRoom.id)
    .single();

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

  renderPlayers(players || []);

  const { data: msgs } = await sb
    .from("messages")
    .select("*")
    .eq("room_id", currentRoom.id)
    .order("created_at", { ascending: true })
    .limit(50);

  renderMessages(msgs || []);
}

function renderPlayers(players) {
  document.getElementById("playerCount").innerText = players.length;
  const listEl = document.getElementById("playersList");
  listEl.innerHTML = "";

  const isHost = Number(currentRoom.host_tg_id) === Number(tgUser.id);
  const startBtn = document.getElementById("startGameBtn");
  if (isHost && currentRoom.status === "lobby" && players.length === 8) {
    startBtn.classList.remove("hidden");
  } else {
    startBtn.classList.add("hidden");
  }

  let myRole = null;
  for (const p of players) {
    if (Number(p.tg_id) === Number(tgUser.id) && p.role) {
      myRole = p.role;
    }
    const div = document.createElement("div");
    div.className = "player-box";
    const statusTag = p.is_alive ? "زنده" : "حذف شده";
    div.innerText = `${p.full_name} (${statusTag})`;
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

async function startGame() {
  if (!currentRoom) return;
  const res = await fetch("/api/start_game", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      room_id: currentRoom.id,
      host_tg_id: tgUser.id
    })
  });
  const data = await res.json();
  if (!res.ok) alert(data.error || "خطا در شروع بازی");
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
document.getElementById("sendMsgBtn").addEventListener("click", sendMessage);
document.getElementById("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
document.getElementById("startGameBtn").addEventListener("click", startGame);
document.getElementById("leaveRoomBtn").addEventListener("click", leaveRoom);
    
