const SUPABASE_URL = "https://gdinatfzwqqxjrozkmtp.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_9dzG5wwNBQZS9DkFtdvDvg_lQse46j7"; // کلید Publishable خودت رو قرار بده
const STARS_INVOICE_URL = "https://t.me/$3_iuhhbDUVCkCAAATIgP4ueLkb0";
window.STARS_INVOICE_URL = STARS_INVOICE_URL;

const ROLE_FA = {
  godfather: "پدرخوانده (مافیا)",
  mafia: "مافیای ساده",
  negotiator: "مذاکره‌کننده (مافیا)",
  detective: "کارآگاه (شهروند)",
  doctor: "دکتر (شهروند)",
  sniper: "تک‌تیرانداز (شهروند)",
  bodyguard: "بادیگارد / محافظ (شهروند)",
  citizen: "شهروند ساده"
};

const STATUS_FA = {
  lobby: "لابی",
  day_talk: "روز - گفتگو",
  day_vote: "روز - رای‌گیری",
  night: "شب",
  ended: "پایان بازی"
};

const VALID_SIZES = [8, 10, 12];

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const tgUser = tg?.initDataUnsafe?.user || {
  id: 8464735969,
  first_name: "Хусеин",
  username: "player",
  photo_url: ""
};

document.getElementById("myName").textContent = tgUser.first_name || "بازیکن";
document.getElementById("myIdText").textContent = `ID: ${tgUser.id}`;
document.getElementById("myAvatar").textContent = (tgUser.first_name || "م")[0];

const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

let selectedSize = 8;
let selectedMode = "free";
let currentRoom = null;
let currentPlayers = [];
let realtimeChannel = null;
let timerInterval = null;
let phaseDuration = 90;
let prevAliveIds = null;

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2800);
}

function randomCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let out = "MAF";
  for (let i = 0; i < 4; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out;
}

document.querySelectorAll("#sizeChips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const sz = Number(chip.dataset.size);
    if (!VALID_SIZES.includes(sz)) return;
    document.querySelectorAll("#sizeChips .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    selectedSize = sz;
  });
});

document.querySelectorAll("#modeChips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#modeChips .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    selectedMode = chip.dataset.mode || "free";
  });
});

async function createRoom() {
  if (!VALID_SIZES.includes(selectedSize)) {
    return showToast("فقط میزهای استاندارد ۸، ۱۰ و ۱۲ نفره مجاز هستند");
  }
  const code = randomCode();
  const payload = {
    code,
    host_tg_id: tgUser.id,
    max_players: selectedSize,
    status: "lobby",
    entry_fee_stars: selectedMode === "stars20" ? 20 : 0,
    prize_pool_stars: 0,
    admin_revenue_stars: 0
  };

  let { data: room, error } = await sb.from("rooms").insert(payload).select().single();
  if (error) {
    const fallback = await sb.from("rooms").insert({ code, host_tg_id: tgUser.id, status: "lobby" }).select().single();
    room = fallback.data;
    error = fallback.error;
  }
  if (error || !room) return showToast("خطا در ساخت اتاق: " + (error?.message || ""));
  await joinRoomByObject(room);
}

async function joinRoomByCode(explicitCode = null) {
  const raw = explicitCode || document.getElementById("roomCodeInput").value;
  const code = String(raw || "").trim().toUpperCase();
  if (!code) return showToast("کد اتاق را وارد کنید");

  const { data: room, error } = await sb.from("rooms").select("*").eq("code", code).single();
  if (error || !room) return showToast("اتاقی با این کد پیدا نشد");
  await joinRoomByObject(room);
}

async function joinRoomByObject(room) {
  const { data: existingPlayers } = await sb.from("players").select("id,tg_id").eq("room_id", room.id);
  const cap = VALID_SIZES.includes(Number(room.max_players)) ? Number(room.max_players) : selectedSize;
  const alreadyIn = (existingPlayers || []).some((p) => Number(p.tg_id) === Number(tgUser.id));
  if (!alreadyIn && (existingPlayers || []).length >= cap) {
    return showToast(`ظرفیت میز استاندارد (${cap} نفر) تکمیل است`);
  }

  const fee = Number(room.entry_fee_stars || 0);
if (fee >= 20 && !alreadyIn) {
  const { data: usedCredit } = await sb.rpc("consume_wallet_for_room", {
    p_tg_id: tgUser.id,
    p_cost: fee
  });

  if (!usedCredit) {
    const paid = await requestStarsInvoice();
    if (!paid) {
      return;
    }
  } else {
    showToast(`${fee} استارز از اعتبار میز بعدی شما کسر شد`);
  }

  await sb.from("rooms").update({
    prize_pool_stars: Number(room.prize_pool_stars || 0) + 10,
    admin_revenue_stars: Number(room.admin_revenue_stars || 0) + 10
  }).eq("id", room.id);
}
  

  const { error: pErr } = await sb.from("players").upsert(
    {
      room_id: room.id,
      tg_id: tgUser.id,
      full_name: tgUser.first_name || "بازیکن",
      username: tgUser.username || "",
      photo_url: tgUser.photo_url || "",
      is_alive: true
    },
    { onConflict: "room_id,tg_id" }
  );
  if (pErr) return showToast("خطا در ورود به اتاق: " + pErr.message);

  currentRoom = room;
  selectedSize = cap;
  document.getElementById("lobbySection").classList.add("hidden");
  document.getElementById("roomSection").classList.remove("hidden");
  document.getElementById("roomCodeText").textContent = room.code;

  await refreshAll();
  subscribeRealtime(room.id);
}

function copyInviteLink() {
  if (!currentRoom) return;
  const link = `${window.location.origin}${window.location.pathname}?room=${encodeURIComponent(currentRoom.code)}`;
  navigator.clipboard?.writeText(link).then(
    () => showToast("لینک دعوت کپی شد"),
    () => prompt("لینک دعوت:", link)
  );
}

async function addTestBots() {
  if (!currentRoom) return;
  const desired = VALID_SIZES.includes(Number(currentRoom.max_players)) ? Number(currentRoom.max_players) : selectedSize;
  const needed = desired - currentPlayers.length;
  if (needed <= 0) return showToast("میز به ظرفیت استاندارد رسیده است");

  const rows = [];
  for (let i = 1; i <= needed; i++) {
    rows.push({
      room_id: currentRoom.id,
      tg_id: 900000000 + Math.floor(Math.random() * 90000000) + i,
      full_name: `بات تست ${currentPlayers.length + i}`,
      username: `bot_test_${Date.now()}_${i}`,
      is_alive: true
    });
  }
  const { error } = await sb.from("players").insert(rows);
  if (error) return showToast("خطا در افزودن بات: " + error.message);
  await refreshAll();
}

function applyThemeByStatus(status) {
  const isNight = status === "night";
  document.body.classList.toggle("night", isNight);
  document.body.classList.toggle("day", !isNight);
  document.getElementById("phaseIcon").textContent = isNight ? "🌙" : "☀️";
  document.getElementById("phaseText").textContent = STATUS_FA[status] || status;
}

function triggerEliminationFX(playerId) {
  const card = document.querySelector(`.player-card[data-id="${playerId}"]`);
  const flash = document.getElementById("flash");
  const main = document.getElementById("main");
  if (flash) {
    flash.classList.remove("active");
    void flash.offsetWidth;
    flash.classList.add("active");
  }
  if (main) {
    main.classList.remove("shake");
    void main.offsetWidth;
    main.classList.add("shake");
  }
  if (card) {
    card.classList.add("eliminating");
    setTimeout(() => card.classList.remove("eliminating"), 1100);
  }
}

async function refreshAll() {
  if (!currentRoom) return;
  const { data: room } = await sb.from("rooms").select("*").eq("id", currentRoom.id).single();
  if (room) {
    currentRoom = room;
    applyThemeByStatus(room.status);
    document.getElementById("prizePoolText").textContent = Number(room.entry_fee_stars || 0) >= 20
      ? `${Number(room.prize_pool_stars || 0)} ⭐`
      : "رایگان";
    startCountdown(room.phase_ends_at, room.status);
  }

  const { data: players } = await sb
    .from("players")
    .select("*")
    .eq("room_id", currentRoom.id)
    .order("joined_at", { ascending: true });

  currentPlayers = players || [];

  const aliveIds = new Set(currentPlayers.filter((p) => p.is_alive).map((p) => Number(p.tg_id)));
  if (prevAliveIds) {
    for (const prevId of prevAliveIds) {
      if (!aliveIds.has(prevId)) triggerEliminationFX(prevId);
    }
  }
  prevAliveIds = aliveIds;

  renderPlayers(currentPlayers);
  renderControls();

  const { data: msgs } = await sb
    .from("messages")
    .select("*")
    .eq("room_id", currentRoom.id)
    .order("created_at", { ascending: true })
    .limit(100);

  renderMessages(msgs || []);
    await renderWinnerRewardBox();
  
}

function getMe() {
  return currentPlayers.find((p) => Number(p.tg_id) === Number(tgUser.id)) || null;
}

function renderPlayers(players) {
  const aliveCount = players.filter((p) => p.is_alive).length;
  const cap = VALID_SIZES.includes(Number(currentRoom?.max_players)) ? Number(currentRoom.max_players) : selectedSize;
  document.getElementById("playerCount").textContent = `${aliveCount} زنده / ${players.length}`;
  document.getElementById("maxPlayerCount").textContent = cap;

  const grid = document.getElementById("playersList");
  grid.innerHTML = "";
  const me = getMe();
  const isEnded = currentRoom?.status === "ended";

  for (const p of players) {
    const div = document.createElement("div");
    div.className = `player-card ${p.is_alive ? "alive" : "dead"}`;
    div.dataset.id = p.tg_id;
    const initial = (p.full_name || "ب")[0];
    const endRole = isEnded && p.role ? ` • ${ROLE_FA[p.role] || p.role}` : "";
    const voteTag = p.voted_for_tg_id ? " • رای داد" : "";
    div.innerHTML = `
      <div class="player-avatar">${initial}</div>
      <div style="min-width:0;">
        <div class="player-card-name">${p.full_name}</div>
        <div class="player-status">${p.is_alive ? "زنده" : "حذف"}${endRole}${voteTag}</div>
      </div>
    `;
    grid.appendChild(div);
  }

  const badge = document.getElementById("myRoleBadge");
  if (me?.role) {
    badge.classList.remove("hidden");
    badge.textContent = ROLE_FA[me.role] || me.role;
  } else {
    badge.classList.add("hidden");
  }
}

function renderControls() {
  const me = getMe();
  const isHost = Number(currentRoom.host_tg_id) === Number(tgUser.id);
  const status = currentRoom.status;
  const cap = VALID_SIZES.includes(Number(currentRoom.max_players)) ? Number(currentRoom.max_players) : selectedSize;
  const validStart = VALID_SIZES.includes(currentPlayers.length) && currentPlayers.length === cap;

  document.getElementById("addBotsBtn").classList.toggle("hidden", !(isHost && status === "lobby" && currentPlayers.length < cap));
  document.getElementById("startGameBtn").classList.toggle("hidden", !(isHost && status === "lobby" && validStart));
  document.getElementById("startVoteBtn").classList.toggle("hidden", !(isHost && status === "day_talk"));
  document.getElementById("botsVoteBtn").classList.toggle("hidden", !(isHost && status === "day_vote"));
  document.getElementById("finishVoteBtn").classList.toggle("hidden", !(isHost && status === "day_vote"));
  document.getElementById("botsNightBtn").classList.toggle("hidden", !(isHost && status === "night"));
  document.getElementById("resolveNightBtn").classList.toggle("hidden", !(isHost && status === "night"));

  const aliveTargets = currentPlayers.filter((p) => p.is_alive);

  const voteSec = document.getElementById("voteSection");
  voteSec.classList.toggle("hidden", !(status === "day_vote" && me && me.is_alive));
  const voteSel = document.getElementById("voteTargetSelect");
  voteSel.innerHTML = "";
  for (const t of aliveTargets) {
    const opt = document.createElement("option");
    opt.value = t.tg_id;
    opt.textContent = t.full_name;
    voteSel.appendChild(opt);
  }

  const nightSec = document.getElementById("nightSection");
  const canNight = status === "night" && me && me.is_alive && ["godfather", "mafia", "negotiator", "detective", "doctor", "bodyguard", "sniper"].includes(me.role);
  nightSec.classList.toggle("hidden", !canNight);
  const nightSel = document.getElementById("nightTargetSelect");
  nightSel.innerHTML = "";
  for (const t of aliveTargets) {
    const opt = document.createElement("option");
    opt.value = t.tg_id;
    opt.textContent = t.full_name;
    nightSel.appendChild(opt);
  }
}

function renderMessages(msgs) {
  const me = getMe();
  const isMafia = ["godfather", "mafia", "negotiator"].includes(me?.role);
  const box = document.getElementById("chatBox");
  box.innerHTML = "";

  for (const m of msgs) {
    if (m.channel === "mafia_night" && !isMafia) continue;
    const div = document.createElement("div");
    div.className = `msg ${m.channel === "system" ? "system" : (m.channel === "mafia_night" ? "mafia-chat" : "")}`;
    if (m.channel === "system") div.textContent = `🔔 ${m.content}`;
    else if (m.channel === "mafia_night") div.textContent = `🕶️ [مافیا] ${m.sender_name}: ${m.content}`;
    else div.textContent = `${m.sender_name}: ${m.content}`;
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

async function sendMessage() {
  const me = getMe();
  if (currentRoom?.status !== "lobby" && (!me || !me.is_alive)) {
    return showToast("بازیکنان حذف‌شده اجازه ارسال پیام در چت بازی را ندارند");
  }
  const input = document.getElementById("chatInput");
  const channel = document.getElementById("chatChannelSelect").value;
  const text = input.value.trim();
  if (!text || !currentRoom) return;

  const isMafia = ["godfather", "mafia", "negotiator"].includes(me?.role);
  if (channel === "mafia_night" && (!isMafia || currentRoom.status !== "night")) {
    return showToast("چت شب مافیا فقط در فاز شب برای اعضای مافیا باز است");
  }

  await sb.from("messages").insert({
    room_id: currentRoom.id,
    sender_tg_id: tgUser.id,
    sender_name: tgUser.first_name || "بازیکن",
    channel,
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
  const text = await res.text();
  let data = {};
  try { data = JSON.parse(text); } catch { data = { error: text || "خطای سرور" }; }
  if (!res.ok) showToast(data.error || "خطا در عملیات");
  return data;
}

function startCountdown(endsAtIso, status) {
  if (timerInterval) clearInterval(timerInterval);
  const el = document.getElementById("timerText");
  const bar = document.getElementById("phaseBar");
  if (!endsAtIso) {
    el.textContent = "--:--";
    bar.style.width = "0%";
    return;
  }
  phaseDuration = status === "day_talk" ? 90 : 60;
  const target = new Date(endsAtIso).getTime();
  timerInterval = setInterval(() => {
    const diff = Math.max(0, Math.floor((target - Date.now()) / 1000));
    const m = String(Math.floor(diff / 60)).padStart(2, "0");
    const s = String(diff % 60).padStart(2, "0");
    el.textContent = `${m}:${s}`;
    const pct = Math.min(100, Math.max(0, ((phaseDuration - diff) / phaseDuration) * 100));
    bar.style.width = `${pct}%`;
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
  prevAliveIds = null;
  document.getElementById("roomSection").classList.add("hidden");
  document.getElementById("lobbySection").classList.remove("hidden");
}

document.getElementById("createRoomBtn").addEventListener("click", createRoom);
document.getElementById("joinRoomBtn").addEventListener("click", () => joinRoomByCode());
document.getElementById("roomCodeInput").addEventListener("input", (e) => { e.target.value = e.target.value.toUpperCase(); });
document.getElementById("roomCodeInput").addEventListener("keypress", (e) => { if (e.key === "Enter") joinRoomByCode(); });
document.getElementById("copyInviteBtn").addEventListener("click", copyInviteLink);
document.getElementById("addBotsBtn").addEventListener("click", addTestBots);
document.getElementById("startGameBtn").addEventListener("click", async () => {
  const d = await callApi("/api/start_game", { room_id: currentRoom.id, actor_tg_id: tgUser.id });
  if (d.ok) await refreshAll();
});
document.getElementById("startVoteBtn").addEventListener("click", () => callApi("/api/day_vote", { room_id: currentRoom.id, action: "start_vote", actor_tg_id: tgUser.id }));
document.getElementById("botsVoteBtn").addEventListener("click", () => callApi("/api/day_vote", { room_id: currentRoom.id, action: "bots_vote", actor_tg_id: tgUser.id }));
document.getElementById("finishVoteBtn").addEventListener("click", () => callApi("/api/day_vote", { room_id: currentRoom.id, action: "finish_vote", actor_tg_id: tgUser.id }));
document.getElementById("castVoteBtn").addEventListener("click", async () => {
  const targetId = document.getElementById("voteTargetSelect").value;
  const d = await callApi("/api/day_vote", { room_id: currentRoom.id, action: "cast_vote", actor_tg_id: tgUser.id, target_tg_id: targetId });
  if (d.ok) showToast("رای شما ثبت شد");
});
document.getElementById("nightActionBtn").addEventListener("click", async () => {
  const targetId = document.getElementById("nightTargetSelect").value;
  const d = await callApi("/api/night_action", { room_id: currentRoom.id, action: "set_target", actor_tg_id: tgUser.id, target_tg_id: targetId });
  if (d.inquiry) document.getElementById("inquiryResult").textContent = d.inquiry;
  else if (d.ok) document.getElementById("inquiryResult").textContent = "هدف شب ثبت شد.";
});
document.getElementById("botsNightBtn").addEventListener("click", () => callApi("/api/night_action", { room_id: currentRoom.id, action: "bots_night", actor_tg_id: tgUser.id }));
document.getElementById("resolveNightBtn").addEventListener("click", async () => {
  document.getElementById("inquiryResult").textContent = "";
  await callApi("/api/night_action", { room_id: currentRoom.id, action: "resolve_night", actor_tg_id: tgUser.id });
});
document.getElementById("sendMsgBtn").addEventListener("click", sendMessage);
document.getElementById("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });
document.getElementById("leaveRoomBtn").addEventListener("click", leaveRoom);
document.getElementById("topBackBtn").addEventListener("click", () => {
  if (currentRoom) leaveRoom();
  else tg?.close();
});

const roomFromUrl = new URLSearchParams(window.location.search).get("room") || tg?.initDataUnsafe?.start_param;
if (roomFromUrl) joinRoomByCode(roomFromUrl);
function requestStarsInvoice() {
  return new Promise((resolve) => {
    const invoiceUrl = window.STARS_INVOICE_URL || STARS_INVOICE_URL;
    if (!window.Telegram?.WebApp?.openInvoice || !invoiceUrl) {
      resolve(false);
      return;
    }
    window.Telegram.WebApp.openInvoice(invoiceUrl, (status) => {
      resolve(status === "paid");
    });
  });
}

async function getMyWalletCredit() {
  if (!tgUser?.id) return 0;
  const { data } = await sb
    .from("player_wallets")
    .select("credit_stars")
    .eq("tg_id", tgUser.id)
    .maybeSingle();
  return Number(data?.credit_stars || 0);
}

function calculateMyPrizeShare(room, playersList) {
  if (!room || room.status !== "ended" || !tgUser?.id) return 0;
  const pool = Number(room.prize_pool_stars || 0);
  if (pool <= 0) return 0;

  const listPlayers = Array.isArray(playersList) && playersList.length
    ? playersList
    : (Array.isArray(currentPlayers) ? currentPlayers : []);

  const myPlayer = listPlayers.find((p) => Number(p.tg_id) === Number(tgUser.id));
  if (!myPlayer) return 0;

  const listMsgs = Array.isArray(window.messages)
    ? window.messages
    : (Array.isArray(window.lastMessages) ? window.lastMessages : []);

  const lastMsg = listMsgs
    .slice()
    .reverse()
    .find((m) => (m.text || "").includes("برنده") || (m.text || "").includes("پیروز"));
  const msgText = lastMsg?.text || "";
  const mafiaWon = msgText.includes("مافیا") && !msgText.includes("شهروند");
  const townWon = msgText.includes("شهروند") || msgText.includes("شهر");

  const mafiaRoles = ["godfather", "mafia", "simple_mafia", "mafia_doctor", "negotiator"];
  let winners = [];

  if (mafiaWon) {
    winners = listPlayers.filter((p) =>
      mafiaRoles.includes(String(p.role || "").toLowerCase())
    );
  } else if (townWon) {
    winners = listPlayers.filter(
      (p) => !mafiaRoles.includes(String(p.role || "").toLowerCase())
    );
  } else {
    winners = listPlayers.filter((p) => Boolean(p.is_alive));
  }

  const amIWinner = winners.some((w) => Number(w.tg_id) === Number(tgUser.id));
  if (!amIWinner || winners.length === 0) return 0;

  return Math.max(1, Math.floor(pool / winners.length));
}

async function renderWinnerRewardBox() {
  const box = document.getElementById("winnerRewardBox");
  const badge = document.getElementById("winnerRewardAmountBadge");
  const actions = document.getElementById("winnerRewardActions");
  const statusEl = document.getElementById("winnerRewardStatusText");
  if (!box || !currentRoom || !tgUser?.id) return;

  const share = calculateMyPrizeShare(currentRoom, currentPlayers);
  if (share <= 0) {
    box.classList.add("hidden");
    return;
  }

  box.classList.remove("hidden");
  badge.textContent = `${share} ⭐`;

  const { data: existingClaim } = await sb
    .from("reward_claims")
    .select("choice, amount_stars")
    .eq("room_id", currentRoom.id)
    .eq("tg_id", tgUser.id)
    .maybeSingle();

  if (existingClaim) {
    actions.classList.add("hidden");
    statusEl.classList.remove("hidden");
    statusEl.textContent =
      existingClaim.choice === "keep_next_table"
        ? `✓ ${existingClaim.amount_stars} استارز برای ورود به میز بعدی ذخیره شده است.`
        : `✓ درخواست برداشت ${existingClaim.amount_stars} استارز ثبت شده است.`;
    return;
  }

  actions.classList.remove("hidden");
  statusEl.classList.add("hidden");

  document.getElementById("btnKeepNextTable").onclick = () => submitRewardChoice(share, "keep_next_table");
  document.getElementById("btnRequestWithdraw").onclick = () => submitRewardChoice(share, "withdraw");
}

async function submitRewardChoice(amount, choice) {
  if (!currentRoom || !tgUser?.id) return;
  const { data, error } = await sb.rpc("claim_winner_reward", {
    p_room_id: currentRoom.id,
    p_room_code: currentRoom.code || "",
    p_tg_id: tgUser.id,
    p_full_name: tgUser.first_name || "بازیکن",
    p_username: tgUser.username || "",
    p_amount: amount,
    p_choice: choice
  });

  if (error) return showToast("خطا در ثبت انتخاب: " + error.message);
  if (!data?.ok) return showToast(data?.error || "امکان ثبت انتخاب وجود ندارد");

  showToast(data.message);
  await renderWinnerRewardBox();
}
