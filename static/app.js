import { generatePeriod } from "./scheduler.js";
import { buildScheduleWorkbook, MIME_TYPE } from "./excel.js";

"use strict";

const CONFIG = window.SCHEDULER_CONFIG;
const TYPE_LABELS = {
  NORMAL: "一般日",
  BIG: "大日",
  OFF: "停爐",
  CUSTOM: "其他",
};
const WEEKDAY_LABELS = ["日", "一", "二", "三", "四", "五", "六"];
const STORAGE_KEY = "crematorium-scheduler-offline-v1";
const STORAGE_VERSION = 1;

const state = {
  days: [],
  vacations: Object.fromEntries(CONFIG.employees.map((name) => [name, new Set()])),
  activeEmployee: CONFIG.employees[0],
  lastPayload: null,
  lastResult: null,
  busy: false,
};

const elements = {
  startDate: document.getElementById("start-date"),
  endDate: document.getElementById("end-date"),
  buildPeriod: document.getElementById("build-period-btn"),
  daysEmpty: document.getElementById("days-empty"),
  daysGrid: document.getElementById("days-grid"),
  periodStatus: document.getElementById("period-status"),
  vacationSection: document.getElementById("vacation-section"),
  vacationStatus: document.getElementById("vacation-status"),
  employeeRows: document.getElementById("employee-rows"),
  activeEmployeeName: document.getElementById("active-employee-name"),
  activeEmployeeRule: document.getElementById("active-employee-rule"),
  vacationCounter: document.getElementById("vacation-counter"),
  vacationCalendar: document.getElementById("vacation-calendar"),
  clearVacation: document.getElementById("clear-vacation-btn"),
  readinessTitle: document.getElementById("readiness-title"),
  readinessDetail: document.getElementById("readiness-detail"),
  readinessProgress: document.getElementById("readiness-progress"),
  generateSection: document.getElementById("generate-section"),
  validationMessage: document.getElementById("validation-message"),
  generate: document.getElementById("generate-btn"),
  reroll: document.getElementById("reroll-btn"),
  export: document.getElementById("export-btn"),
  resultSection: document.getElementById("result-section"),
  resultPeriodLabel: document.getElementById("result-period-label"),
  balanceScore: document.getElementById("balance-score"),
  balanceCards: document.getElementById("balance-cards"),
  scheduleTable: document.getElementById("schedule-table"),
  statsTable: document.getElementById("stats-table"),
  toast: document.getElementById("toast"),
  connectionStatus: document.getElementById("connection-status"),
  installCard: document.getElementById("install-card"),
};

let toastTimer = null;
let saveTimer = null;
let offlineReady = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function localDateString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateFromString(value) {
  return new Date(`${value}T00:00:00`);
}

function addDays(date, amount) {
  const next = new Date(date.getTime());
  next.setDate(next.getDate() + amount);
  return next;
}

function makeSeed() {
  if (window.crypto?.getRandomValues) {
    const values = new Uint32Array(1);
    window.crypto.getRandomValues(values);
    return values[0] & 0x7fffffff;
  }
  return Math.floor((Date.now() * Math.random()) % 0x7fffffff);
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("is-visible"), 2800);
}

function updateConnectionStatus() {
  const offline = !navigator.onLine;
  elements.connectionStatus.textContent = offline ? "離線運作" : (offlineReady ? "可離線" : "已連線");
  elements.connectionStatus.parentElement.classList.toggle("is-offline", offline);
}

function setupPwa() {
  updateConnectionStatus();
  window.addEventListener("online", updateConnectionStatus);
  window.addEventListener("offline", updateConnectionStatus);
  if (window.navigator.standalone === true) elements.installCard.hidden = true;
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./service-worker.js")
      .then(() => navigator.serviceWorker.ready)
      .then(() => {
        offlineReady = true;
        updateConnectionStatus();
      })
      .catch(() => {
        elements.connectionStatus.textContent = "需先連線";
      });
  } else {
    elements.connectionStatus.textContent = "需 HTTPS";
  }
}

function stateSnapshot() {
  return {
    version: STORAGE_VERSION,
    employees: [...CONFIG.employees],
    days: state.days,
    vacations: Object.fromEntries(
      CONFIG.employees.map((name) => [name, [...state.vacations[name]].sort()]),
    ),
    activeEmployee: state.activeEmployee,
    lastPayload: state.lastPayload,
    lastResult: state.lastResult,
  };
}

function saveStateNow() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stateSnapshot()));
  } catch {
    showToast("這台裝置無法保存資料，請確認 Safari 未使用私密瀏覽。");
  }
}

function scheduleSave() {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(saveStateNow, 120);
}

function restoreState() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  } catch {
    return false;
  }
  if (!saved || saved.version !== STORAGE_VERSION) return false;
  if (JSON.stringify(saved.employees) !== JSON.stringify(CONFIG.employees)) return false;
  if (!Array.isArray(saved.days) || saved.days.length !== CONFIG.periodDays) return false;

  const dayDates = new Set(saved.days.map((day) => day.date));
  if (dayDates.size !== CONFIG.periodDays) return false;
  state.days = saved.days.map((day) => ({
    date: String(day.date),
    dayType: TYPE_LABELS[day.dayType] ? day.dayType : "NORMAL",
    label: String(day.label || "").slice(0, 40),
    requirements: {
      A: Number(day.requirements?.A || 0),
      B: Number(day.requirements?.B || 0),
      C: Number(day.requirements?.C || 0),
    },
  }));
  state.vacations = Object.fromEntries(CONFIG.employees.map((name) => {
    const dates = Array.isArray(saved.vacations?.[name])
      ? saved.vacations[name].filter((date) => dayDates.has(date))
      : [];
    return [name, new Set(dates)];
  }));
  state.activeEmployee = CONFIG.employees.includes(saved.activeEmployee)
    ? saved.activeEmployee
    : CONFIG.employees[0];
  state.lastPayload = saved.lastPayload || null;
  state.lastResult = saved.lastResult || null;

  elements.startDate.value = state.days[0].date;
  elements.endDate.value = state.days[state.days.length - 1].date;
  elements.daysEmpty.hidden = true;
  elements.vacationSection.classList.remove("is-locked");
  setStepState(1, "complete");
  renderDaysGrid();
  renderEmployeeRows();
  renderVacationCalendar();
  updateReadiness();

  if (state.lastResult?.schedule?.length === CONFIG.periodDays) {
    renderResult(state.lastResult);
    elements.reroll.disabled = false;
    elements.export.disabled = false;
    setStepState(3, "complete");
    setStepState(4, "active");
  }
  return true;
}

function setStepState(step, mode) {
  const item = document.querySelector(`[data-step-indicator="${step}"]`);
  if (!item) return;
  item.classList.toggle("is-active", mode === "active");
  item.classList.toggle("is-complete", mode === "complete");
}

function invalidateResult(notify = false) {
  const hadResult = Boolean(state.lastResult);
  state.lastPayload = null;
  state.lastResult = null;
  elements.resultSection.hidden = true;
  elements.reroll.disabled = true;
  elements.export.disabled = true;
  setStepState(4, "idle");
  if (notify && hadResult) showToast("設定已變更，請重新產生班表。");
  scheduleSave();
}

function updateEndDatePreview() {
  if (!elements.startDate.value) {
    elements.endDate.value = "";
    return;
  }
  const start = dateFromString(elements.startDate.value);
  if (Number.isNaN(start.getTime())) {
    elements.endDate.value = "";
    return;
  }
  elements.endDate.value = localDateString(addDays(start, CONFIG.periodDays - 1));
}

function buildPeriod() {
  if (!elements.startDate.value) {
    showToast("請先選擇起始日期。");
    elements.startDate.focus();
    return;
  }

  const start = dateFromString(elements.startDate.value);
  if (Number.isNaN(start.getTime())) {
    showToast("起始日期格式不正確。");
    return;
  }

  if (state.days.length) {
    const confirmed = window.confirm("重新建立日期模板會清除目前所有日期標記與休假，確定繼續嗎？");
    if (!confirmed) return;
  }

  state.days = Array.from({ length: CONFIG.periodDays }, (_, index) => {
    const date = addDays(start, index);
    return {
      date: localDateString(date),
      dayType: "NORMAL",
      label: "",
      requirements: { A: 0, B: 2, C: 0 },
    };
  });
  state.vacations = Object.fromEntries(CONFIG.employees.map((name) => [name, new Set()]));
  state.activeEmployee = CONFIG.employees[0];
  elements.endDate.value = state.days[state.days.length - 1].date;

  invalidateResult(false);
  elements.daysEmpty.hidden = true;
  elements.vacationSection.classList.remove("is-locked");
  setStepState(1, "complete");
  setStepState(2, "active");
  renderDaysGrid();
  renderEmployeeRows();
  renderVacationCalendar();
  updateReadiness();
  showToast("28 天模板已建立，接著標記日期並選擇休假。");
}

function dayRuleText(day) {
  if (day.dayType === "NORMAL") return "2A · 2C · 其餘 B";
  if (day.dayType === "BIG") return "同一般日，加強避免連 B";
  if (day.dayType === "OFF") return "全日不排班";
  const { A, B, C } = day.requirements;
  return `自訂 A${A} · B${B} · C${C}`;
}

function renderDaysGrid() {
  elements.daysGrid.innerHTML = state.days.map((day, index) => {
    const date = dateFromString(day.date);
    const monthDay = `${date.getMonth() + 1}/${date.getDate()}`;
    const customHidden = day.dayType === "CUSTOM" ? "" : "hidden";
    return `
      <article class="day-card" data-day-index="${index}" data-type="${day.dayType}">
        <div class="day-card-header">
          <strong>${monthDay}</strong>
          <span>Day ${index + 1} · 週${WEEKDAY_LABELS[date.getDay()]}</span>
        </div>
        <select class="day-type-select" data-action="day-type" aria-label="${day.date} 日期類型">
          ${Object.entries(TYPE_LABELS).map(([value, label]) => (
            `<option value="${value}" ${day.dayType === value ? "selected" : ""}>${label}</option>`
          )).join("")}
        </select>
        <p class="day-rule">${escapeHtml(dayRuleText(day))}</p>
        <div class="custom-settings" ${customHidden}>
          <input class="custom-label" data-action="custom-label" type="text" maxlength="40"
                 value="${escapeHtml(day.label)}" placeholder="標記名稱，例如：停爐留守"
                 aria-label="${day.date} 自訂標記名稱">
          <div class="custom-counts">
            ${["A", "B", "C"].map((role) => `
              <label>${role}
                <input data-action="custom-count" data-role="${role}" type="number" min="0" max="${CONFIG.employees.length}"
                       value="${day.requirements[role]}" aria-label="${day.date} ${role} 人數">
              </label>
            `).join("")}
          </div>
        </div>
      </article>
    `;
  }).join("");
  updatePeriodStatus();
}

function updatePeriodStatus() {
  const counts = { BIG: 0, OFF: 0, CUSTOM: 0 };
  state.days.forEach((day) => {
    if (Object.hasOwn(counts, day.dayType)) counts[day.dayType] += 1;
  });
  elements.periodStatus.textContent = `大日 ${counts.BIG} · 停爐 ${counts.OFF} · 其他 ${counts.CUSTOM}`;
  elements.periodStatus.classList.add("is-ready");
}

function handleDaysGridChange(event) {
  const card = event.target.closest("[data-day-index]");
  if (!card) return;
  const index = Number(card.dataset.dayIndex);
  const day = state.days[index];
  if (!day) return;

  const action = event.target.dataset.action;
  if (action === "day-type") {
    day.dayType = event.target.value;
    if (day.dayType === "OFF") {
      CONFIG.employees.forEach((name) => state.vacations[name].delete(day.date));
    }
    invalidateResult(true);
    renderDaysGrid();
    renderEmployeeRows();
    renderVacationCalendar();
    updateReadiness();
    return;
  }

  if (action === "custom-label") {
    day.label = event.target.value.slice(0, 40);
    invalidateResult(true);
    return;
  }

  if (action === "custom-count") {
    const role = event.target.dataset.role;
    const parsed = Number.parseInt(event.target.value, 10);
    day.requirements[role] = Number.isFinite(parsed)
      ? Math.max(0, Math.min(CONFIG.employees.length, parsed))
      : 0;
    event.target.value = day.requirements[role];
    const rule = card.querySelector(".day-rule");
    if (rule) rule.textContent = dayRuleText(day);
    invalidateResult(true);
  }
}

function renderEmployeeRows() {
  elements.employeeRows.innerHTML = CONFIG.employeeRows.map((row) => `
    <div class="employee-row">
      ${row.map((name) => {
        const count = state.vacations[name].size;
        const active = name === state.activeEmployee;
        const complete = count >= CONFIG.minVacationDays;
        return `
          <button type="button" class="employee-tab ${active ? "is-active" : ""} ${complete ? "is-complete" : ""}"
                  data-employee="${escapeHtml(name)}" aria-pressed="${active}">
            <strong>${escapeHtml(name)}</strong><span>${count}天</span>
          </button>
        `;
      }).join("")}
    </div>
  `).join("");
}

function selectEmployee(name) {
  if (!CONFIG.employees.includes(name)) return;
  state.activeEmployee = name;
  renderEmployeeRows();
  renderVacationCalendar();
  scheduleSave();
}

function renderVacationCalendar() {
  const name = state.activeEmployee;
  const selected = state.vacations[name];
  const restricted = CONFIG.restrictedRoles[name];
  const offCount = state.days.filter((day) => day.dayType === "OFF").length;
  const availableCount = CONFIG.periodDays - offCount - selected.size;

  elements.activeEmployeeName.textContent = name;
  elements.activeEmployeeRule.textContent = restricted
    ? "僅排 B／C，且 B 的分配權重大於 C。"
    : "可排 A／B／C。";
  elements.vacationCounter.innerHTML = `
    <strong>${selected.size}</strong>
    <span>休假天數</span>
    <small>可排 ${availableCount} 天 · 至少 ${CONFIG.minVacationDays} 天休假</small>
  `;

  elements.vacationCalendar.innerHTML = state.days.map((day, index) => {
    const date = dateFromString(day.date);
    const isOff = day.dayType === "OFF";
    const isSelected = selected.has(day.date);
    let stateLabel = TYPE_LABELS[day.dayType];
    if (isSelected) stateLabel = "休假";
    const title = day.dayType === "CUSTOM" && day.label ? day.label : TYPE_LABELS[day.dayType];
    return `
      <button type="button" class="vacation-day ${isSelected ? "is-selected" : ""}"
              data-vacation-date="${day.date}" aria-pressed="${isSelected}" ${isOff ? "disabled" : ""}
              title="${escapeHtml(title)}">
        <span class="vacation-day-date">
          <strong>${date.getMonth() + 1}/${date.getDate()}</strong>
          <span>Day ${index + 1} · 週${WEEKDAY_LABELS[date.getDay()]}</span>
        </span>
        <span class="vacation-day-state">${escapeHtml(stateLabel)}</span>
      </button>
    `;
  }).join("");
}

function toggleVacation(date) {
  const day = state.days.find((item) => item.date === date);
  if (!day || day.dayType === "OFF") return;
  const selected = state.vacations[state.activeEmployee];
  if (selected.has(date)) selected.delete(date);
  else selected.add(date);

  invalidateResult(true);
  renderEmployeeRows();
  renderVacationCalendar();
  updateReadiness();
}

function clearActiveVacation() {
  const selected = state.vacations[state.activeEmployee];
  if (!selected.size) return;
  selected.clear();
  invalidateResult(true);
  renderEmployeeRows();
  renderVacationCalendar();
  updateReadiness();
}

function incompleteEmployees() {
  return CONFIG.employees.filter((name) => state.vacations[name].size < CONFIG.minVacationDays);
}

function customDayErrors() {
  const errors = [];
  state.days.forEach((day) => {
    if (day.dayType !== "CUSTOM") return;
    const vacationCount = CONFIG.employees.filter((name) => state.vacations[name].has(day.date)).length;
    const available = CONFIG.employees.length - vacationCount;
    const needed = day.requirements.A + day.requirements.B + day.requirements.C;
    if (needed > available) {
      errors.push(`${day.date} 自訂需求 ${needed} 人，但只有 ${available} 人可排`);
    }
  });
  return errors;
}

function updateReadiness() {
  if (!state.days.length) return;
  const incomplete = incompleteEmployees();
  const completed = CONFIG.employees.length - incomplete.length;
  const ready = incomplete.length === 0;
  const progress = (completed / CONFIG.employees.length) * 100;

  elements.vacationStatus.textContent = `${completed} / ${CONFIG.employees.length} 人完成`;
  elements.vacationStatus.classList.toggle("is-ready", ready);
  elements.readinessProgress.style.width = `${progress}%`;
  elements.readinessTitle.textContent = ready ? "所有人員休假設定完成" : `還有 ${incomplete.length} 人未完成`;
  elements.readinessDetail.textContent = ready
    ? "現在可以產生班表；之後仍可回來調整。"
    : `${incomplete.join("、")} 尚未選滿 ${CONFIG.minVacationDays} 天。`;

  elements.generateSection.classList.toggle("is-locked", !ready);
  elements.generate.disabled = !ready || state.busy;
  elements.validationMessage.textContent = ready
    ? "日期模板與休假資料已就緒。"
    : `請先完成：${incomplete.join("、")}`;
  elements.validationMessage.classList.remove("is-error");

  setStepState(2, ready ? "complete" : "active");
  setStepState(3, ready ? "active" : "idle");
}

function buildPayload(seed) {
  const vacations = {};
  CONFIG.employees.forEach((name) => {
    vacations[name] = Array.from(state.vacations[name]).sort();
  });
  return {
    seed,
    days: state.days.map((day) => ({
      date: day.date,
      day_type: day.dayType,
      label: day.label,
      requirements: day.dayType === "CUSTOM" ? { ...day.requirements } : {},
    })),
    vacations,
  };
}

function setBusy(busy) {
  state.busy = busy;
  const ready = state.days.length && incompleteEmployees().length === 0;
  elements.generate.disabled = busy || !ready;
  elements.reroll.disabled = busy || !state.lastResult;
  elements.export.disabled = busy || !state.lastResult;
  elements.generate.textContent = busy ? "正在平衡班表…" : "產生四週班表";
}

async function generateSchedule(isReroll) {
  const incomplete = incompleteEmployees();
  if (incomplete.length) {
    showValidationError(`下列人員尚未選滿 ${CONFIG.minVacationDays} 天：${incomplete.join("、")}`);
    return;
  }
  const customErrors = customDayErrors();
  if (customErrors.length) {
    showValidationError(customErrors.join("；"));
    return;
  }

  const payload = buildPayload(makeSeed());
  setBusy(true);
  elements.validationMessage.textContent = isReroll ? "正在重新尋找另一組均衡配置…" : "正在計算四週配置…";
  elements.validationMessage.classList.remove("is-error");

  try {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    const data = generatePeriod(payload.days, payload.vacations, payload.seed, CONFIG);

    state.lastPayload = payload;
    state.lastResult = data;
    renderResult(data);
    elements.reroll.disabled = false;
    elements.export.disabled = false;
    elements.validationMessage.textContent = isReroll
      ? "已完成重新安排；日期與休假設定均保留。"
      : "班表產生完成。";
    setStepState(3, "complete");
    setStepState(4, "active");
    saveStateNow();
    showToast(isReroll ? "已換成另一組符合規則的班表。" : "四週班表已產生。");
    elements.resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showValidationError(error.message || "產生班表時發生錯誤");
  } finally {
    setBusy(false);
  }
}

function showValidationError(message) {
  elements.validationMessage.textContent = message;
  elements.validationMessage.classList.add("is-error");
  showToast(message);
}

function roleCell(day, name) {
  if (day.day_type === "OFF") return ["停", "role-off"];
  if (day.vacations.includes(name)) return ["休", "role-vacation"];
  const role = day.assignment[name];
  if (role) return [role, `role-${role.toLowerCase()}`];
  return ["—", "role-unassigned"];
}

function renderResult(data) {
  const schedule = data.schedule;
  const stats = data.stats;
  elements.resultSection.hidden = false;
  elements.resultPeriodLabel.textContent = `${schedule[0].date} ～ ${schedule[schedule.length - 1].date} · 工作日 ${stats.working_days} · 停爐 ${stats.off_days} · 大日 ${stats.big_days} · 其他 ${stats.custom_days}`;
  elements.balanceScore.textContent = Number(stats.balance.overall_score).toFixed(1);

  elements.balanceCards.innerHTML = ["A", "B", "C"].map((role) => {
    const item = stats.balance.roles[role];
    return `
      <div class="balance-card">
        <div class="balance-card-header"><strong>${role} 崗</strong><span>${Number(item.score).toFixed(1)} 分</span></div>
        <p>個人可排日比例落差 ${(item.spread * 100).toFixed(1)} 個百分點</p>
      </div>
    `;
  }).join("");

  const scheduleHead = `
    <thead><tr><th>日期</th><th>類型</th>${CONFIG.employees.map((name) => `<th>${escapeHtml(name)}</th>`).join("")}</tr></thead>
  `;
  const scheduleBody = schedule.map((day) => {
    const date = dateFromString(day.date);
    const rowClass = `is-${day.day_type.toLowerCase()}`;
    const typeLabel = day.day_type === "CUSTOM" && day.label
      ? `${TYPE_LABELS[day.day_type]}·${escapeHtml(day.label)}`
      : TYPE_LABELS[day.day_type];
    return `
      <tr class="${rowClass}">
        <td><strong>${date.getMonth() + 1}/${date.getDate()}</strong><br><small>週${WEEKDAY_LABELS[date.getDay()]}</small></td>
        <td>${typeLabel}</td>
        ${CONFIG.employees.map((name) => {
          const [value, className] = roleCell(day, name);
          return `<td><span class="role-badge ${className}">${value}</span></td>`;
        }).join("")}
      </tr>
    `;
  }).join("");
  elements.scheduleTable.innerHTML = `<table class="schedule-table">${scheduleHead}<tbody>${scheduleBody}</tbody></table>`;

  const statsHead = `
    <thead><tr>
      <th>人員</th><th>休假</th><th>可排</th><th>實排</th><th>未排</th>
      <th>A</th><th>B</th><th>C</th><th>B比例</th><th>連B次數</th><th>最長連B</th><th>期末連B</th>
    </tr></thead>
  `;
  const statsBody = stats.employees.map((item) => `
    <tr>
      <td><strong>${escapeHtml(item.name)}</strong></td>
      <td>${item.vacation_days}</td>
      <td>${item.available_days}</td>
      <td>${item.assigned_days}</td>
      <td>${item.unassigned_days}</td>
      <td>${item.role_counts.A}</td>
      <td>${item.role_counts.B}</td>
      <td>${item.role_counts.C}</td>
      <td>${(item.role_percentages.B * 100).toFixed(1)}%</td>
      <td>${item.consecutive_b_occurrences}</td>
      <td>${item.longest_b_streak}</td>
      <td>${item.ending_b_streak}</td>
    </tr>
  `).join("");
  elements.statsTable.innerHTML = `<table>${statsHead}<tbody>${statsBody}</tbody></table>`;
}

async function exportExcel() {
  if (!state.lastPayload || !state.lastResult) {
    showToast("請先產生班表再下載。");
    return;
  }

  setBusy(true);
  try {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    const blob = buildScheduleWorkbook(
      state.lastResult,
      state.lastPayload.vacations,
      CONFIG,
    );
    const filename = `schedule_${state.days[0].date}_to_${state.days[state.days.length - 1].date}.xlsx`;
    const file = new File([blob], filename, { type: MIME_TYPE });

    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({
          files: [file],
          title: "新廠四週班表",
        });
        showToast("Excel 已交給 iPhone 分享選單。");
        return;
      } catch (error) {
        if (error?.name === "AbortError") {
          showToast("已取消分享 Excel。");
          return;
        }
      }
    }

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    showToast("Excel 已開始下載。");
  } catch (error) {
    showValidationError(error.message || "Excel 下載失敗");
  } finally {
    setBusy(false);
  }
}

elements.startDate.addEventListener("change", updateEndDatePreview);
elements.buildPeriod.addEventListener("click", buildPeriod);
elements.daysGrid.addEventListener("change", handleDaysGridChange);
elements.daysGrid.addEventListener("input", handleDaysGridChange);
elements.employeeRows.addEventListener("click", (event) => {
  const button = event.target.closest("[data-employee]");
  if (button) selectEmployee(button.dataset.employee);
});
elements.vacationCalendar.addEventListener("click", (event) => {
  const button = event.target.closest("[data-vacation-date]");
  if (button) toggleVacation(button.dataset.vacationDate);
});
elements.clearVacation.addEventListener("click", clearActiveVacation);
elements.generate.addEventListener("click", () => generateSchedule(false));
elements.reroll.addEventListener("click", () => generateSchedule(true));
elements.export.addEventListener("click", exportExcel);

const restored = restoreState();
if (!restored) {
  const today = new Date();
  elements.startDate.value = localDateString(today);
  updateEndDatePreview();
}
setupPwa();
