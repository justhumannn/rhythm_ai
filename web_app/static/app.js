const state = {
  song: null,
  chart: null,
  chartId: null,
  events: [],
  activeHolds: new Map(),
  hitEvents: new Set(),
  pressedLanes: new Set(),
  missedHoldHeads: new Set(),
  earnedScoreUnits: 0,
  maxScoreUnits: 0,
  score: 0,
  combo: 0,
  judgement: "-",
  running: false,
  animationId: null,
  scrollSpeed: 1,
  hitEffects: [],
  hitEffectMode: "burst",
  hitEffectSize: 1,
  hitEffectDuration: 0.25,
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
const songBpm = document.querySelector("#songBpm");
const manualBpm = document.querySelector("#manualBpm");
const analyzeBpmButton = document.querySelector("#analyzeBpmButton");
const existingCharts = document.querySelector("#existingCharts");
const chartButtons = document.querySelector("#chartButtons");
const generateButton = document.querySelector("#generateButton");
const chartName = document.querySelector("#chartName");
const scoreEl = document.querySelector("#score");
const comboEl = document.querySelector("#combo");
const judgementEl = document.querySelector("#judgement");
const rankEl = document.querySelector("#rank");
const tapRatio = document.querySelector("#tapRatio");
const holdRatio = document.querySelector("#holdRatio");
const tapRatioValue = document.querySelector("#tapRatioValue");
const holdRatioValue = document.querySelector("#holdRatioValue");
const scrollSpeed = document.querySelector("#scrollSpeed");
const scrollSpeedValue = document.querySelector("#scrollSpeedValue");
const volumeControl = document.querySelector("#volumeControl");
const volumeValue = document.querySelector("#volumeValue");
const hitEffectMode = document.querySelector("#hitEffectMode");
const hitEffectSize = document.querySelector("#hitEffectSize");
const hitEffectSizeValue = document.querySelector("#hitEffectSizeValue");
const hitEffectDuration = document.querySelector("#hitEffectDuration");
const hitEffectDurationValue = document.querySelector("#hitEffectDurationValue");
const keyBindButtons = [...document.querySelectorAll(".key-bind-button")];

audioPlayer.volume = Number(volumeControl.value) / 100;

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

volumeControl.addEventListener("input", () => {
  audioPlayer.volume = Number(volumeControl.value) / 100;
  volumeValue.value = `${volumeControl.value}%`;
});

hitEffectMode.addEventListener("change", () => {
  state.hitEffectMode = hitEffectMode.value;
});

hitEffectSize.addEventListener("input", () => {
  state.hitEffectSize = Number(hitEffectSize.value);
  hitEffectSizeValue.value = `${state.hitEffectSize.toFixed(1)}x`;
});

hitEffectDuration.addEventListener("input", () => {
  state.hitEffectDuration = Number(hitEffectDuration.value);
  hitEffectDurationValue.value = `${state.hitEffectDuration.toFixed(2)}s`;
});

keyBindButtons.forEach((button) => {
  button.addEventListener("click", () => captureKeyBinding(button));
});

analyzeBpmButton.addEventListener("click", async () => {
  if (!state.song) return;
  try {
    await applySongBpm({ manageBusy: true });
  } catch (error) {
    showError(error);
  }
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
    if (manualBpm.value || state.song.bpm === null || state.song.bpm === undefined) {
      await applySongBpm({ manageBusy: false });
      setStatus("생성 중");
    }
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
  releaseHold(lane, audioPlayer.currentTime);
  state.pressedLanes.delete(lane);
});

audioPlayer.addEventListener("ended", stopPlayback);

function loadSong(song, autoLoadExisting = true) {
  const changedSong = state.song?.id !== song.id;
  state.song = song;
  songInfo.classList.remove("hidden");
  songTitle.textContent = song.title;
  renderSongBpm(song);
  if (changedSong) {
    manualBpm.value = "";
  }
  generateButton.disabled = false;
  audioPlayer.src = `/api/songs/${song.id}/audio`;
  renderChartButtons(song.charts);
  if (autoLoadExisting && song.charts.length > 0) {
    getJson(`/api/charts/${song.charts[0].id}`).then(loadChart).catch(showError);
  }
}

async function applySongBpm({ manageBusy }) {
  const rawBpm = manualBpm.value.trim();
  const bpm = rawBpm === "" ? null : Number(rawBpm);
  if (bpm !== null && (!Number.isFinite(bpm) || bpm < 30 || bpm > 400)) {
    throw new Error("BPM은 30에서 400 사이로 입력해 주세요.");
  }

  setStatus(bpm === null ? "BPM 분석 중" : "BPM 적용 중");
  if (manageBusy) setBusy(true);
  analyzeBpmButton.disabled = true;
  try {
    const song = await postJson(`/api/songs/${state.song.id}/bpm`, { bpm });
    state.song = song;
    renderSongBpm(song);
    renderChartButtons(song.charts);
    if (state.chart) {
      clearChart();
    }
    manualBpm.value = "";
    setStatus(bpm === null ? "BPM 재분석됨" : "BPM 적용됨");
    songBpm.textContent += " · 새 채보부터 적용";
    return song;
  } finally {
    if (manageBusy) {
      setBusy(false);
    } else {
      analyzeBpmButton.disabled = false;
    }
  }
}

function renderSongBpm(song) {
  if (song.bpm === null || song.bpm === undefined) {
    songBpm.textContent = "BPM 미분석";
    return;
  }
  const source = song.bpm_source === "manual" ? "직접 입력" : "자동 분석";
  const confidence = song.bpm_confidence === null || song.bpm_confidence === undefined
    ? ""
    : ` · 신뢰도 ${Math.round(Number(song.bpm_confidence) * 100)}%`;
  const warning = song.bpm_ambiguous ? " · 배수박 후보 있음" : "";
  songBpm.textContent = `${formatBpm(song.bpm)} BPM · ${source}${confidence}${warning}`;
}

function formatBpm(value) {
  const bpm = Number(value);
  return Number.isInteger(bpm) ? String(bpm) : bpm.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
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
  state.maxScoreUnits = state.events.reduce(
    (total, event) => total + (event.type === "hold" ? 2 : 1),
    0,
  );
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
  processMissedNotes(currentTime);
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

  drawHitEffects(currentTime, laneWidth, receptorY);
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
      state.activeHolds.set(lane, startHoldState(recoveredHold, currentTime, true));
      state.combo += 1;
      addScoreUnits(0.25, "BAD");
      spawnHitEffect(lane, "BAD", currentTime);
      updateScore();
    }
    return;
  }
  const judgement = judgementForDelta(best.delta);
  if (best.event.type === "hold") {
    state.activeHolds.set(lane, startHoldState(best.event, currentTime));
    state.combo += 1;
    addScoreUnits(judgement.weight, judgement.label);
    spawnHitEffect(lane, judgement.label, currentTime);
  } else {
    state.hitEvents.add(best.event.id);
    state.combo += 1;
    addScoreUnits(judgement.weight, judgement.label);
    spawnHitEffect(lane, judgement.label, currentTime);
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

function processMissedNotes(currentTime) {
  const missWindow = 0.14;
  const releaseWindow = 0.16;

  for (const event of state.events) {
    if (state.hitEvents.has(event.id)) continue;

    if (event.type === "hold") {
      const lane = String(event.lane);
      const isActive = state.activeHolds.get(lane)?.id === event.id;
      if (!isActive && !state.missedHoldHeads.has(event.id) && currentTime > event.timeSeconds + missWindow) {
        state.missedHoldHeads.add(event.id);
        registerMiss();
      }
      if (!isActive && currentTime > event.endTimeSeconds + releaseWindow) {
        state.hitEvents.add(event.id);
        registerMiss();
      }
      continue;
    }

    if (currentTime > event.timeSeconds + missWindow) {
      state.hitEvents.add(event.id);
      registerMiss();
    }
  }
}

function updateActiveHolds(currentTime) {
  const releaseWindow = 0.16;
  for (const [lane, hold] of state.activeHolds.entries()) {
    updateHoldProgress(lane, hold, currentTime);
    if (currentTime >= hold.endTimeSeconds - releaseWindow) {
      completeHold(lane, hold, currentTime);
    }
  }
}

function releaseHold(lane, currentTime) {
  const hold = state.activeHolds.get(lane);
  if (!hold) return;
  updateHoldProgress(lane, hold, currentTime);
  const releaseWindow = 0.16;
  if (currentTime >= hold.endTimeSeconds - releaseWindow) {
    completeHold(lane, hold, currentTime);
  }
}

function completeHold(lane, event, currentTime) {
  updateHoldProgress(lane, event, currentTime);
  state.activeHolds.delete(lane);
  state.hitEvents.add(event.id);
  const judgement = judgementForHoldRatio(holdPressRatio(event));
  if (judgement.weight > 0) {
    state.combo += 1;
    const weight = event.recovered
      ? Math.min(judgement.weight, 0.7)
      : judgement.weight;
    addScoreUnits(weight, judgement.label);
    spawnHitEffect(lane, judgement.label, currentTime);
  } else {
    registerMiss();
  }
  updateScore();
}

function failHold(lane, event) {
  state.activeHolds.delete(lane);
  state.hitEvents.add(event.id);
  registerMiss();
  updateScore();
}

function startHoldState(event, currentTime, recovered = false) {
  return {
    ...event,
    recovered,
    heldSeconds: 0,
    lastProgressTime: Math.max(currentTime, event.timeSeconds),
  };
}

function updateHoldProgress(lane, hold, currentTime) {
  const from = Math.max(hold.lastProgressTime, hold.timeSeconds);
  const to = Math.min(currentTime, hold.endTimeSeconds);
  if (to > from && state.pressedLanes.has(lane)) {
    hold.heldSeconds += to - from;
  }
  hold.lastProgressTime = Math.max(hold.lastProgressTime, currentTime);
}

function holdPressRatio(event) {
  const duration = Math.max(0.001, event.endTimeSeconds - event.timeSeconds);
  return Math.max(0, Math.min(1, event.heldSeconds / duration));
}

function judgementForHoldRatio(ratio) {
  if (ratio >= 0.9) return { label: "PERFECT", weight: 1 };
  if (ratio >= 0.75) return { label: "GREAT", weight: ratio };
  if (ratio >= 0.5) return { label: "GOOD", weight: ratio };
  if (ratio > 0) return { label: "BAD", weight: ratio };
  return { label: "MISS", weight: 0 };
}

function spawnHitEffect(lane, judgement, currentTime) {
  if (state.hitEffectMode === "off") return;
  state.hitEffects.push({
    lane: Number(lane) - 1,
    judgement,
    startTime: currentTime,
    duration: state.hitEffectDuration,
  });
}

function drawHitEffects(currentTime, laneWidth, receptorY) {
  if (state.hitEffects.length === 0) return;
  state.hitEffects = state.hitEffects.filter((effect) => currentTime - effect.startTime <= effect.duration);
  for (const effect of state.hitEffects) {
    const elapsed = Math.max(0, currentTime - effect.startTime);
    const progress = Math.min(1, elapsed / effect.duration);
    const alpha = 1 - progress;
    const centerX = effect.lane * laneWidth + laneWidth / 2;
    const baseRadius = laneWidth * 0.28 * state.hitEffectSize;
    const radius = baseRadius + baseRadius * 0.9 * progress;
    const color = effectColor(effect.judgement);

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(2, 5 * state.hitEffectSize * (1 - progress * 0.35));
    ctx.beginPath();
    ctx.arc(centerX, receptorY, radius, 0, Math.PI * 2);
    ctx.stroke();

    if (state.hitEffectMode === "burst") {
      ctx.fillStyle = color;
      for (let index = 0; index < 8; index += 1) {
        const angle = (Math.PI * 2 * index) / 8;
        const distance = radius * (0.75 + progress * 0.7);
        const x = centerX + Math.cos(angle) * distance;
        const y = receptorY + Math.sin(angle) * distance;
        ctx.beginPath();
        ctx.arc(x, y, Math.max(2, 4 * state.hitEffectSize * alpha), 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.restore();
  }
}

function effectColor(judgement) {
  if (judgement === "PERFECT") return "#43c7b8";
  if (judgement === "GREAT") return "#9ed9f4";
  if (judgement === "GOOD") return "#f0b85a";
  return "#ff9da6";
}

function resetScore() {
  state.hitEvents = new Set();
  state.activeHolds = new Map();
  state.pressedLanes = new Set();
  state.missedHoldHeads = new Set();
  state.hitEffects = [];
  state.earnedScoreUnits = 0;
  state.score = 0;
  state.combo = 0;
  state.judgement = "-";
  updateScore();
}

function clearChart() {
  stopPlayback();
  state.chartId = null;
  state.chart = null;
  state.events = [];
  state.maxScoreUnits = 0;
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
  state.score = state.maxScoreUnits > 0
    ? Math.min(1000000, Math.round(state.earnedScoreUnits / state.maxScoreUnits * 1000000))
    : 0;
  scoreEl.textContent = state.score.toLocaleString("ko-KR");
  comboEl.textContent = String(state.combo);
  judgementEl.textContent = state.judgement;
  rankEl.textContent = rankForScore(state.score);
}

function judgementForDelta(delta) {
  if (delta <= 0.035) return { label: "PERFECT", weight: 1 };
  if (delta <= 0.07) return { label: "GREAT", weight: 0.9 };
  if (delta <= 0.105) return { label: "GOOD", weight: 0.7 };
  return { label: "BAD", weight: 0.4 };
}

function addScoreUnits(weight, judgement) {
  state.earnedScoreUnits += weight;
  state.judgement = judgement;
}

function registerMiss() {
  state.combo = 0;
  state.judgement = "MISS";
  updateScore();
}

function rankForScore(score) {
  if (score >= 995000) return "SSS";
  if (score >= 990000) return "SS+";
  if (score >= 985000) return "SS";
  if (score >= 980000) return "S";
  if (score >= 970000) return "AAA";
  if (score >= 960000) return "AA";
  if (score >= 900000) return "A";
  return "-";
}

function stopPlayback() {
  state.running = false;
  playButton.textContent = "재생";
  cancelAnimationFrame(state.animationId);
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
  state.activeHolds = new Map();
  state.pressedLanes = new Set();
  state.hitEffects = [];
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
  const contentType = response.headers.get("content-type") || "";
  const body = await response.text();
  let data = null;

  if (body && contentType.includes("application/json")) {
    try {
      data = JSON.parse(body);
    } catch {
      throw new Error(
        `서버가 올바르지 않은 JSON을 반환했습니다. (HTTP ${response.status})`
      );
    }
  }

  if (!response.ok) {
    const detail = data?.detail;
    if (detail) {
      throw new Error(detail);
    }
    if (response.status === 502 || response.status === 503) {
      throw new Error(
        `배포 서버가 실행 중이 아닙니다. Render 배포 로그를 확인해 주세요. (HTTP ${response.status})`
      );
    }
    throw new Error(`서버 요청에 실패했습니다. (HTTP ${response.status})`);
  }
  if (data === null) {
    throw new Error(
      `서버가 JSON 대신 빈 응답 또는 HTML을 반환했습니다. (HTTP ${response.status})`
    );
  }
  return data;
}

function setStatus(text) {
  statusBadge.textContent = text;
}

function setBusy(isBusy) {
  songForm.querySelector("button").disabled = isBusy;
  generateButton.disabled = isBusy || !state.song;
  analyzeBpmButton.disabled = isBusy || !state.song;
}

function showError(error) {
  setStatus("오류");
  window.alert(error.message || error);
}

drawGame(0);
