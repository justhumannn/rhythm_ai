const state = {
  song: null,
  chart: null,
  chartId: null,
  events: [],
  activeHolds: new Map(),
  hitEvents: new Set(),
  pressedLanes: new Set(),
  score: 0,
  combo: 0,
  running: false,
  animationId: null,
  scrollSpeed: 1,
  keyBindings: ["KeyD", "KeyF", "KeyJ", "KeyK"],
  keyLabels: ["D", "F", "J", "K"],
};

const songForm = document.querySelector("#songForm");
const generateForm = document.querySelector("#generateForm");
const playButton = document.querySelector("#playButton");
const audioPlayer = document.querySelector("#audioPlayer");
const canvas = document.querySelector("#gameCanvas");
const ctx = canvas.getContext("2d");

const statusBadge = document.querySelector("#statusBadge");
const songInfo = document.querySelector("#songInfo");
const songTitle = document.querySelector("#songTitle");
const existingCharts = document.querySelector("#existingCharts");
const chartButtons = document.querySelector("#chartButtons");
const generateButton = document.querySelector("#generateButton");
const chartName = document.querySelector("#chartName");
const scoreEl = document.querySelector("#score");
const comboEl = document.querySelector("#combo");
const tapRatio = document.querySelector("#tapRatio");
const holdRatio = document.querySelector("#holdRatio");
const tapRatioValue = document.querySelector("#tapRatioValue");
const holdRatioValue = document.querySelector("#holdRatioValue");
const scrollSpeed = document.querySelector("#scrollSpeed");
const scrollSpeedValue = document.querySelector("#scrollSpeedValue");
const keyBindButtons = [...document.querySelectorAll(".key-bind-button")];

tapRatio.addEventListener("input", () => {
  tapRatioValue.value = tapRatio.value;
});

holdRatio.addEventListener("input", () => {
  holdRatioValue.value = holdRatio.value;
});

scrollSpeed.addEventListener("input", () => {
  state.scrollSpeed = Number(scrollSpeed.value);
  scrollSpeedValue.value = `${state.scrollSpeed.toFixed(1)}x`;
  drawGame(audioPlayer.currentTime || 0);
});

keyBindButtons.forEach((button) => {
  button.addEventListener("click", () => captureKeyBinding(button));
});

songForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("다운로드");
  setBusy(true);
  try {
    const youtubeUrl = document.querySelector("#youtubeUrl").value;
    const song = await postJson("/api/songs", { youtube_url: youtubeUrl });
    loadSong(song);
    setStatus(song.charts.length ? "저장됨" : "준비됨");
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

generateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.song) return;
  setStatus("생성 중");
  setBusy(true);
  try {
    const chart = await postJson("/api/charts", {
      song_id: state.song.id,
      chart_name: document.querySelector("#chartNameInput").value,
      password: document.querySelector("#chartPassword").value,
      difficulty: document.querySelector("#difficulty").value,
      tap_ratio: Number(tapRatio.value),
      hold_ratio: Number(holdRatio.value),
      key_count: 4,
      key_bindings: state.keyBindings,
    });
    document.querySelector("#chartPassword").value = "";
    await loadChart(chart);
    const refreshed = await getJson(`/api/songs/${state.song.id}`);
    loadSong(refreshed, false);
    setStatus("생성됨");
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

playButton.addEventListener("click", async () => {
  if (!state.chart) return;
  if (state.running) {
    stopPlayback();
    return;
  }
  resetScore();
  state.running = true;
  playButton.textContent = "정지";
  await audioPlayer.play();
  loop();
});

window.addEventListener("keydown", (event) => {
  const lane = laneForCode(event.code);
  if (!lane || !state.running) return;
  if (event.repeat) return;
  state.pressedLanes.add(lane);
  hitLane(lane);
});

window.addEventListener("keyup", (event) => {
  const lane = laneForCode(event.code);
  if (!lane) return;
  state.pressedLanes.delete(lane);
  releaseHold(lane, audioPlayer.currentTime);
});

audioPlayer.addEventListener("ended", stopPlayback);

function loadSong(song, autoLoadExisting = true) {
  state.song = song;
  songInfo.classList.remove("hidden");
  songTitle.textContent = song.title;
  generateButton.disabled = false;
  audioPlayer.src = `/api/songs/${song.id}/audio`;
  renderChartButtons(song.charts);
  if (autoLoadExisting && song.charts.length > 0) {
    getJson(`/api/charts/${song.charts[0].id}`).then(loadChart).catch(showError);
  }
}

function renderChartButtons(charts) {
  chartButtons.innerHTML = "";
  existingCharts.classList.toggle("hidden", charts.length === 0);
  charts.forEach((chart) => {
    const row = document.createElement("div");
    row.className = "chart-list-row";

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "chart-select-button";
    selectButton.innerHTML = `<span>${escapeHtml(chart.name)}</span><span>${bpmLabel(chart)} · ${chart.note_count} notes</span>`;
    selectButton.addEventListener("click", async () => {
      const fullChart = await getJson(`/api/charts/${chart.id}`);
      await loadChart(fullChart);
    });

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "chart-edit-button";
    editButton.textContent = "수정";
    editButton.title = "채보 이름 변경";
    editButton.disabled = !chart.manageable;
    editButton.addEventListener("click", () => renameChart(chart));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "chart-delete-button";
    deleteButton.textContent = "삭제";
    deleteButton.title = "채보 삭제";
    deleteButton.disabled = !chart.manageable;
    deleteButton.addEventListener("click", () => deleteChart(chart));

    row.append(selectButton, editButton, deleteButton);
    chartButtons.appendChild(row);
  });
}

async function loadChart(payload) {
  state.chartId = payload.id;
  state.chart = payload.chart;
  setKeyBindings(payload.key_bindings);
  state.events = payload.chart.events.map((event, index) => ({
    ...event,
    id: index,
    timeSeconds: Number(event.timeSeconds ?? beatToSeconds(event.beat, payload.chart.bpm.max)),
    endTimeSeconds: Number(event.endTimeSeconds ?? event.timeSeconds ?? beatToSeconds(event.endBeat ?? event.beat, payload.chart.bpm.max)),
  }));
  chartName.textContent = `${payload.name} · ${bpmLabel(payload)}`;
  playButton.disabled = false;
  resetScore();
  drawGame(0);
}

function bpmLabel(chart) {
  const bpm = `${chart.bpm} BPM`;
  if (chart.bpm_confidence === null || chart.bpm_confidence === undefined) {
    return bpm;
  }
  const confidence = Math.round(Number(chart.bpm_confidence) * 100);
  const warning = chart.bpm_ambiguous ? " · 배수박 후보 있음" : "";
  return `${bpm} · 신뢰도 ${confidence}%${warning}`;
}

async function deleteChart(chart) {
  const password = window.prompt(`"${chart.name}" 채보의 관리 비밀번호를 입력하세요.`);
  if (password === null) return;
  const confirmed = window.confirm(`"${chart.name}" 채보를 삭제할까요?`);
  if (!confirmed) return;

  setStatus("삭제 중");
  try {
    await deleteJson(`/api/charts/${chart.id}`, { password });
    const deletedCurrentChart = state.chartId === chart.id;
    if (deletedCurrentChart) {
      clearChart();
    }

    const refreshed = await getJson(`/api/songs/${state.song.id}`);
    loadSong(refreshed, false);
    if (deletedCurrentChart && refreshed.charts.length > 0) {
      const nextChart = await getJson(`/api/charts/${refreshed.charts[0].id}`);
      await loadChart(nextChart);
    }
    setStatus("삭제됨");
  } catch (error) {
    showError(error);
  }
}

async function renameChart(chart) {
  const name = window.prompt("새 채보 이름을 입력하세요.", chart.name);
  if (name === null || !name.trim()) return;
  const password = window.prompt(`"${chart.name}" 채보의 관리 비밀번호를 입력하세요.`);
  if (password === null) return;

  setStatus("변경 중");
  try {
    const updated = await patchJson(`/api/charts/${chart.id}`, {
      name: name.trim(),
      password,
    });
    const refreshed = await getJson(`/api/songs/${state.song.id}`);
    loadSong(refreshed, false);
    if (state.chartId === chart.id) {
      await loadChart(updated);
    }
    setStatus("변경됨");
  } catch (error) {
    showError(error);
  }
}

function loop() {
  if (!state.running) return;
  const currentTime = audioPlayer.currentTime;
  updateActiveHolds(currentTime);
  drawGame(currentTime);
  state.animationId = requestAnimationFrame(loop);
}

function drawGame(currentTime) {
  const width = canvas.width;
  const height = canvas.height;
  const laneCount = 4;
  const laneWidth = width / laneCount;
  const receptorY = height - 96;
  const travelSeconds = 2.2 / state.scrollSpeed;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#08090c";
  ctx.fillRect(0, 0, width, height);

  for (let lane = 0; lane < laneCount; lane += 1) {
    const x = lane * laneWidth;
    ctx.fillStyle = lane % 2 === 0 ? "#10151d" : "#121922";
    ctx.fillRect(x, 0, laneWidth, height);
    ctx.strokeStyle = "#303642";
    ctx.strokeRect(x, 0, laneWidth, height);
  }

  ctx.fillStyle = "#43c7b8";
  ctx.fillRect(0, receptorY, width, 5);

  for (const event of state.events) {
    const isActiveHold = state.activeHolds.has(String(event.lane)) && state.activeHolds.get(String(event.lane)).id === event.id;
    if (state.hitEvents.has(event.id) && !isActiveHold) continue;
    const y = receptorY - (event.timeSeconds - currentTime) / travelSeconds * receptorY;
    const lane = Number(event.lane) - 1;
    const x = lane * laneWidth + 10;
    const noteWidth = laneWidth - 20;

    if (event.type === "hold") {
      const endY = receptorY - (event.endTimeSeconds - currentTime) / travelSeconds * receptorY;
      const headY = isActiveHold ? receptorY : y;
      if (Math.max(headY, endY) < -80 || Math.min(headY, endY) > height + 80) continue;
      ctx.fillStyle = isActiveHold ? "rgba(67, 199, 184, 0.65)" : "rgba(240, 184, 90, 0.55)";
      ctx.fillRect(x, Math.min(headY, endY), noteWidth, Math.max(14, Math.abs(endY - headY)));
      ctx.fillStyle = "#f0b85a";
    } else {
      if (y < -80 || y > height + 80) continue;
      ctx.fillStyle = "#f4f6f8";
    }
    ctx.fillRect(x, y - 9, noteWidth, 18);
  }
}

function hitLane(lane) {
  const currentTime = audioPlayer.currentTime;
  const windowSeconds = 0.14;
  let best = null;
  for (const event of state.events) {
    if (state.hitEvents.has(event.id) || String(event.lane) !== lane) continue;
    const delta = Math.abs(event.timeSeconds - currentTime);
    if (delta <= windowSeconds && (!best || delta < best.delta)) {
      best = { event, delta };
    }
  }
  if (!best) {
    const recoveredHold = findRecoverableHold(lane, currentTime);
    if (recoveredHold) {
      state.activeHolds.set(lane, { ...recoveredHold, recovered: true });
      state.combo += 1;
      state.score += 150;
      updateScore();
      return;
    }
    state.combo = 0;
    updateScore();
    return;
  }
  if (best.event.type === "hold") {
    state.activeHolds.set(lane, best.event);
    state.combo += 1;
    state.score += best.delta < 0.06 ? 600 : 300;
  } else {
    state.hitEvents.add(best.event.id);
    state.combo += 1;
    state.score += best.delta < 0.06 ? 1000 : 500;
  }
  updateScore();
}

function findRecoverableHold(lane, currentTime) {
  const releaseWindow = 0.16;
  if (state.activeHolds.has(lane)) return null;

  let best = null;
  for (const event of state.events) {
    if (event.type !== "hold") continue;
    if (state.hitEvents.has(event.id) || String(event.lane) !== lane) continue;
    if (currentTime <= event.timeSeconds + 0.14) continue;
    if (currentTime >= event.endTimeSeconds - releaseWindow) continue;
    if (!best || event.timeSeconds < best.timeSeconds) {
      best = event;
    }
  }
  return best;
}

function updateActiveHolds(currentTime) {
  const releaseWindow = 0.16;
  for (const [lane, event] of state.activeHolds.entries()) {
    if (!state.pressedLanes.has(lane) && currentTime < event.endTimeSeconds - releaseWindow) {
      failHold(lane, event);
      continue;
    }
    if (currentTime >= event.endTimeSeconds - releaseWindow) {
      completeHold(lane, event, currentTime);
    }
  }
}

function releaseHold(lane, currentTime) {
  const event = state.activeHolds.get(lane);
  if (!event) return;
  const releaseWindow = 0.16;
  if (currentTime >= event.endTimeSeconds - releaseWindow) {
    completeHold(lane, event, currentTime);
  } else {
    failHold(lane, event);
  }
}

function completeHold(lane, event, currentTime) {
  const delta = Math.abs(event.endTimeSeconds - currentTime);
  state.activeHolds.delete(lane);
  state.hitEvents.add(event.id);
  state.combo += 1;
  if (event.recovered) {
    state.score += delta < 0.08 ? 400 : 250;
  } else {
    state.score += delta < 0.08 ? 1000 : 700;
  }
  updateScore();
}

function failHold(lane, event) {
  state.activeHolds.delete(lane);
  state.hitEvents.add(event.id);
  state.combo = 0;
  updateScore();
}

function resetScore() {
  state.hitEvents = new Set();
  state.activeHolds = new Map();
  state.pressedLanes = new Set();
  state.score = 0;
  state.combo = 0;
  updateScore();
}

function clearChart() {
  stopPlayback();
  state.chartId = null;
  state.chart = null;
  state.events = [];
  chartName.textContent = "없음";
  playButton.disabled = true;
  resetScore();
  drawGame(0);
}

function captureKeyBinding(button) {
  const laneIndex = Number(button.dataset.lane) - 1;
  button.textContent = "입력...";
  button.classList.add("capturing");

  const capture = (event) => {
    event.preventDefault();
    if (event.code === "Escape") {
      button.textContent = state.keyLabels[laneIndex];
      button.classList.remove("capturing");
      return;
    }
    if (state.keyBindings.some((code, index) => code === event.code && index !== laneIndex)) {
      window.alert("이미 다른 레인에서 사용 중인 키입니다.");
      button.textContent = state.keyLabels[laneIndex];
      button.classList.remove("capturing");
      return;
    }
    state.keyBindings[laneIndex] = event.code;
    state.keyLabels[laneIndex] = keyLabel(event);
    button.textContent = state.keyLabels[laneIndex];
    button.classList.remove("capturing");
    updateKeyGuide();
  };
  window.addEventListener("keydown", capture, { once: true });
}

function setKeyBindings(bindings) {
  const safeBindings = Array.isArray(bindings) && bindings.length === 4
    ? bindings
    : ["KeyD", "KeyF", "KeyJ", "KeyK"];
  state.keyBindings = [...safeBindings];
  state.keyLabels = safeBindings.map(labelForCode);
  keyBindButtons.forEach((button, index) => {
    button.textContent = state.keyLabels[index];
  });
  updateKeyGuide();
}

function updateKeyGuide() {
  state.keyLabels.forEach((label, index) => {
    document.querySelector(`[data-key-guide="${index + 1}"]`).textContent = label;
  });
}

function laneForCode(code) {
  const index = state.keyBindings.indexOf(code);
  return index >= 0 ? String(index + 1) : null;
}

function keyLabel(event) {
  return event.key.length === 1 ? event.key.toUpperCase() : labelForCode(event.code);
}

function labelForCode(code) {
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  if (code.startsWith("Numpad")) return `N${code.slice(6)}`;
  return code.replace("Arrow", "");
}

function updateScore() {
  scoreEl.textContent = String(state.score);
  comboEl.textContent = String(state.combo);
}

function stopPlayback() {
  state.running = false;
  playButton.textContent = "재생";
  cancelAnimationFrame(state.animationId);
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
  state.activeHolds = new Map();
  state.pressedLanes = new Set();
  drawGame(0);
}

function beatToSeconds(beat, bpm) {
  return Number(beat) * 60 / Number(bpm);
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJsonResponse(response);
}

async function getJson(url) {
  const response = await fetch(url);
  return readJsonResponse(response);
}

async function patchJson(url, payload) {
  const response = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJsonResponse(response);
}

async function deleteJson(url, payload) {
  const response = await fetch(url, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return readJsonResponse(response);
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

async function readJsonResponse(response) {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "요청에 실패했습니다.");
  }
  return data;
}

function setStatus(text) {
  statusBadge.textContent = text;
}

function setBusy(isBusy) {
  songForm.querySelector("button").disabled = isBusy;
  generateButton.disabled = isBusy || !state.song;
}

function showError(error) {
  setStatus("오류");
  window.alert(error.message || error);
}

drawGame(0);
