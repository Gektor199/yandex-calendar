const state = {
  events: [],
  employees: storedEmployees(),
  employeeNames: storedEmployeeNames(),
  weekStart: document.getElementById("week-start").value,
  timeZone: document.getElementById("time-zone").value,
};

const dayNames = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
const colors = ["event-blue", "event-cyan", "event-green", "event-violet", "event-pink"];
const calendarGrid = document.getElementById("calendar-grid");
const employeeList = document.getElementById("employee-list");
const dayStartHour = 0;
const dayEndHour = 23;
const hourHeight = 48;
const headerHeight = 72;
let shouldScrollToWorkHours = true;

function storedEmployees() {
  try {
    const parsed = JSON.parse(localStorage.getItem("calendarEmployees") || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
  } catch (_) {
    return [];
  }
}

function storedEmployeeNames() {
  try {
    const parsed = JSON.parse(localStorage.getItem("calendarEmployeeNames") || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[character]));
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  let fallbackText = "";
  try {
    const rawText = await response.text();
    fallbackText = rawText;
    payload = rawText ? JSON.parse(rawText) : {};
  } catch (_) {
    payload = {};
  }
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Требуется повторный вход.");
  }
  if (!response.ok) {
    throw new Error(payload.detail || fallbackText || "Запрос завершился ошибкой.");
  }
  return payload;
}

function toast(message, tone = "success") {
  const root = document.getElementById("toast-root");
  const element = document.createElement("article");
  element.className = `toast ${tone}`;
  element.innerHTML = `<p class="toast-title">${tone === "error" ? "Ошибка" : "Статус"}</p><p class="toast-message">${escapeHtml(message)}</p>`;
  root.appendChild(element);
  window.setTimeout(() => element.remove(), 4300);
}

function dateFromInput(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function isoDate(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function addDays(value, days) {
  const date = dateFromInput(value);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

function formatDate(value) {
  return dateFromInput(value).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

function formatMonth(value) {
  return dateFromInput(value).toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
}

function monthLabel(value) {
  return dateFromInput(value).toLocaleDateString("ru-RU", { month: "short" }).replace(".", "");
}

function formatTime(minutes) {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function eventTimeLabel(event) {
  return `${formatTime(event.start_minutes)} - ${formatTime(event.end_minutes)}`;
}

function weekDays() {
  return Array.from({ length: 7 }, (_, index) => addDays(state.weekStart, index));
}

function normalizeEmail(value) {
  return value.trim().toLowerCase();
}

function employeeColorClass(email) {
  const index = state.employees.indexOf(email);
  return colors[Math.max(0, index) % colors.length];
}

function employeeDisplayName(email) {
  return state.employeeNames[email] || email;
}

function rememberEmployeeName(email, name) {
  const cleanName = String(name || "").trim();
  if (!email || !cleanName || cleanName.includes("@")) return;
  state.employeeNames[email] = cleanName;
  localStorage.setItem("calendarEmployeeNames", JSON.stringify(state.employeeNames));
}

function renderEmployees() {
  localStorage.setItem("calendarEmployees", JSON.stringify(state.employees));
  if (!state.employees.length) {
    employeeList.innerHTML = "";
    return;
  }
  employeeList.innerHTML = state.employees.map((email) => `
    <span class="employee-chip ${employeeColorClass(email)}">
      <span>${escapeHtml(employeeDisplayName(email))}</span>
      <button type="button" data-remove-employee="${escapeHtml(email)}" aria-label="Убрать ${escapeHtml(email)}">×</button>
    </span>
  `).join("");
}

function renderMiniCalendar() {
  const selected = dateFromInput(state.weekStart);
  const year = selected.getFullYear();
  const month = selected.getMonth();
  const first = new Date(year, month, 1);
  const startOffset = (first.getDay() + 6) % 7;
  const gridStart = new Date(year, month, 1 - startOffset);
  const selectedWeek = new Set(weekDays());
  let html = `
    <div class="mini-calendar-head">
      <button type="button" data-month-step="-1" aria-label="Предыдущий месяц">‹</button>
      <strong>${formatMonth(state.weekStart)}</strong>
      <button type="button" data-month-step="1" aria-label="Следующий месяц">›</button>
    </div>
    <div class="mini-calendar-weekdays">
      ${["пн", "вт", "ср", "чт", "пт", "сб", "вс"].map((day) => `<span>${day}</span>`).join("")}
    </div>
    <div class="mini-calendar-days">
  `;
  for (let index = 0; index < 42; index += 1) {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + index);
    const iso = isoDate(date);
    html += `<button type="button" class="${date.getMonth() !== month ? "muted" : ""} ${selectedWeek.has(iso) ? "selected-week" : ""} ${iso === state.weekStart ? "selected-day" : ""} ${iso === isoDate(new Date()) ? "today" : ""}" data-mini-date="${iso}">${date.getDate()}</button>`;
  }
  html += "</div>";
  document.getElementById("mini-calendar").innerHTML = html;
}

function addEmployeeFromInput() {
  const input = document.getElementById("employee-email");
  const email = normalizeEmail(input.value);
  if (!email) return false;
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    toast("Укажите корректный email сотрудника.", "error");
    return false;
  }
  if (!state.employees.includes(email)) {
    state.employees.push(email);
    renderEmployees();
  }
  input.value = "";
  return true;
}

function renderCalendar(options = {}) {
  const wrap = document.querySelector(".calendar-wrap");
  const previousScrollTop = wrap?.scrollTop || 0;
  const previousScrollLeft = wrap?.scrollLeft || 0;
  if (!options.keepDetails) closeEventDetails();
  const days = weekDays();
  renderMiniCalendar();
  document.getElementById("week-label").textContent = "Неделя";
  document.getElementById("month-label").textContent = formatMonth(days[0]);
  document.getElementById("event-count").textContent = state.employees.length
    ? `${state.events.length} событий найдено`
    : "Добавьте email сотрудника";

  const hourRows = Array.from({ length: dayEndHour - dayStartHour + 1 }, (_, index) => dayStartHour + index);
  let html = '<div class="time-header"></div>';
  html += days.map((day, index) => `
    <div class="day-header ${day === isoDate(new Date()) ? "today" : ""}">
      <span>${dayNames[index]}</span>
      <strong>${dateFromInput(day).getDate()}</strong>
      <small>${monthLabel(day)}</small>
    </div>
  `).join("");
  html += hourRows.map((hour) => `<div class="time-cell">${hour === 0 ? "" : `${String(hour).padStart(2, "0")}:00`}</div>${days.map(() => '<div class="slot-cell"></div>').join("")}`).join("");
  html += renderCurrentTimeLine(days);
  html += days.map((day, dayIndex) => {
    return layoutDayEvents(state.events.filter((event) => event.day === day)).map(({ event, lane, laneCount }) => {
      const start = Math.max(dayStartHour * 60, event.start_minutes);
      const end = Math.min((dayEndHour + 1) * 60, event.end_minutes);
      const top = headerHeight + ((start - dayStartHour * 60) / 60) * hourHeight;
      const durationHeight = ((end - start) / 60) * hourHeight - 4;
      const isCompact = durationHeight < 54;
      const height = Math.max(isCompact ? 28 : 42, durationHeight);
      const columnWidth = `(100% - 58px) / ${days.length}`;
      const laneGap = laneCount > 1 ? 2 : 0;
      const left = `calc(58px + ${dayIndex} * (${columnWidth}) + 4px + ${lane} * ((${columnWidth} - 8px) / ${laneCount}))`;
      const width = `calc(((${columnWidth} - 8px) / ${laneCount}) - ${laneGap}px)`;
      const acceptedClass = ownerAccepted(event) ? "event-accepted" : "event-unaccepted";
      return `
        <button class="event-card ${employeeColorClass(event.owner_email)} ${acceptedClass} ${isCompact ? "event-compact" : ""}" type="button" data-event-key="${escapeHtml(event.key)}" style="top:${top}px; left:${left}; width:${width}; height:${height}px">
          <span class="event-time">${eventTimeLabel(event)}</span>
          <strong>${escapeHtml(event.title)}</strong>
          ${event.location && !isCompact ? `<small>${escapeHtml(event.location)}</small>` : ""}
        </button>
      `;
    }).join("");
  }).join("");
  if (!state.events.length) {
    html += '<div class="calendar-empty">Событий на выбранной неделе нет.</div>';
  }
  calendarGrid.innerHTML = html;
  if (options.preserveScroll && wrap) {
    wrap.scrollTop = previousScrollTop;
    wrap.scrollLeft = previousScrollLeft;
  } else {
    scrollToWorkHours();
  }
}

function layoutDayEvents(events) {
  const sorted = [...events].sort((left, right) =>
    left.start_minutes - right.start_minutes ||
    right.end_minutes - left.end_minutes ||
    left.title.localeCompare(right.title)
  );
  const groups = [];
  let current = [];
  let currentEnd = -1;

  sorted.forEach((event) => {
    if (!current.length || event.start_minutes < currentEnd) {
      current.push(event);
      currentEnd = Math.max(currentEnd, event.end_minutes);
      return;
    }
    groups.push(current);
    current = [event];
    currentEnd = event.end_minutes;
  });
  if (current.length) groups.push(current);

  return groups.flatMap((group) => {
    const laneEnds = [];
    const placements = group.map((event) => {
      let lane = laneEnds.findIndex((end) => end <= event.start_minutes);
      if (lane === -1) {
        lane = laneEnds.length;
        laneEnds.push(event.end_minutes);
      } else {
        laneEnds[lane] = event.end_minutes;
      }
      return { event, lane };
    });
    const laneCount = Math.max(1, laneEnds.length);
    return placements.map((placement) => ({ ...placement, laneCount }));
  });
}

function renderCurrentTimeLine(days) {
  const now = new Date();
  const today = isoDate(now);
  if (!days.includes(today)) return "";
  const minutes = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
  const top = headerHeight + ((minutes - dayStartHour * 60) / 60) * hourHeight;
  if (top < headerHeight || top > headerHeight + (dayEndHour - dayStartHour + 1) * hourHeight) {
    return "";
  }
  return `<div class="current-time-line" style="top:${top}px"></div>`;
}

function scrollToWorkHours() {
  if (!shouldScrollToWorkHours) return;
  const wrap = document.querySelector(".calendar-wrap");
  wrap.scrollTop = 7 * hourHeight;
  shouldScrollToWorkHours = false;
}

function linkify(value) {
  const escaped = escapeHtml(value);
  return escaped.replace(/https?:\/\/[^\s<]+/g, (url) => `<a href="${url}" target="_blank" rel="noreferrer">${url}</a>`);
}

function closeEventDetails() {
  document.getElementById("event-popover")?.remove();
}

function showEventDetails(event, anchor) {
  closeEventDetails();
  const popover = document.createElement("article");
  popover.id = "event-popover";
  popover.className = "event-popover";
  popover.innerHTML = `
    <button class="event-popover-close" type="button" aria-label="Закрыть">×</button>
    <h3>${escapeHtml(event.title)}</h3>
    ${event.description ? `<div class="event-description">${linkify(event.description).replace(/\n/g, "<br>")}</div>` : ""}
    <dl class="event-meta">
      <div><dt>Календарь</dt><dd>${escapeHtml(event.owner_email || "")}</dd></div>
      ${event.location ? `<div><dt>Место</dt><dd>${escapeHtml(event.location)}</dd></div>` : ""}
      <div><dt>Время</dt><dd>${eventTimeLabel(event)}</dd></div>
      <div><dt>Дата</dt><dd>${formatDate(event.day)}</dd></div>
    </dl>
    ${renderParticipants(event.participants || [])}
  `;
  const wrap = document.querySelector(".calendar-wrap");
  popover.style.maxHeight = `${Math.max(260, wrap.clientHeight - 32)}px`;
  wrap.appendChild(popover);

  const wrapRect = wrap.getBoundingClientRect();
  const anchorRect = anchor.getBoundingClientRect();
  const popoverRect = popover.getBoundingClientRect();
  let left = anchorRect.right - wrapRect.left + wrap.scrollLeft + 12;
  if (left + popoverRect.width > wrap.scrollLeft + wrap.clientWidth - 16) {
    left = anchorRect.left - wrapRect.left + wrap.scrollLeft - popoverRect.width - 12;
  }
  left = Math.max(wrap.scrollLeft + 16, Math.min(left, wrap.scrollLeft + wrap.clientWidth - popoverRect.width - 16));
  let top = anchorRect.top - wrapRect.top + wrap.scrollTop - 12;
  top = Math.max(
    wrap.scrollTop + 16,
    Math.min(top, wrap.scrollTop + wrap.clientHeight - popoverRect.height - 16)
  );
  popover.style.left = `${Math.max(16, left)}px`;
  popover.style.top = `${top}px`;
  popover.querySelector(".event-popover-close").addEventListener("click", closeEventDetails);
}

calendarGrid.addEventListener("click", (event) => {
  const eventCard = event.target.closest("[data-event-key]");
  if (!eventCard) return;
  const calendarEvent = state.events.find((item) => item.key === eventCard.dataset.eventKey);
  if (!calendarEvent) return;
  showEventDetails(calendarEvent, eventCard);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeEventDetails();
});

async function loadEvents(options = {}) {
  if (!options.silent && !options.manualRefresh) addEmployeeFromInput();
  state.weekStart = document.getElementById("week-start").value;
  state.timeZone = document.getElementById("time-zone").value.trim();
  if (!state.employees.length) {
    if (!options.silent) toast("Добавьте хотя бы одного сотрудника.", "error");
    return;
  }
  const refreshButton = document.getElementById("refresh-calendar");
  if (!options.silent) document.getElementById("show-button").disabled = true;
  if (options.manualRefresh) {
    refreshButton.disabled = true;
    refreshButton.classList.add("refreshing");
  }
  try {
    const payloads = await Promise.all(state.employees.map((email) => {
      const params = new URLSearchParams({
        email,
        from_date: state.weekStart,
        to_date: addDays(state.weekStart, 6),
        time_zone: state.timeZone,
      });
      if (options.manualRefresh) params.set("refresh", "true");
      return requestJson(`/api/calendar/events?${params.toString()}`);
    }));
    state.events = payloads.flatMap((payload) => payload.items.map((event, index) => ({
      ...event,
      owner_email: payload.email,
      key: `${payload.email}:${event.id}:${event.start}:${index}`,
    })));
    payloads.forEach((payload) => updateEmployeeNameFromEvents(payload.email, payload.items));
    state.events.sort((left, right) => `${left.start}${left.title}`.localeCompare(`${right.start}${right.title}`));
    renderEmployees();
    renderCalendar({
      keepDetails: options.silent || options.manualRefresh,
      preserveScroll: options.silent || options.manualRefresh,
    });
  } catch (error) {
    if (!options.silent && !options.manualRefresh) {
      state.events = [];
      renderCalendar();
    }
    if (!options.silent) toast(error.message, "error");
  } finally {
    if (!options.silent) document.getElementById("show-button").disabled = false;
    if (options.manualRefresh) {
      refreshButton.disabled = false;
      refreshButton.classList.remove("refreshing");
    }
  }
}

document.getElementById("calendar-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadEvents();
});

document.getElementById("add-employee").addEventListener("click", () => {
  if (addEmployeeFromInput()) loadEvents();
});

employeeList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-employee]");
  if (!button) return;
  state.employees = state.employees.filter((email) => email !== button.dataset.removeEmployee);
  state.events = state.events.filter((item) => item.owner_email !== button.dataset.removeEmployee);
  renderEmployees();
  renderCalendar();
});

document.getElementById("prev-week").addEventListener("click", () => {
  document.getElementById("week-start").value = addDays(document.getElementById("week-start").value, -7);
  shouldScrollToWorkHours = true;
  loadEvents();
});

document.getElementById("next-week").addEventListener("click", () => {
  document.getElementById("week-start").value = addDays(document.getElementById("week-start").value, 7);
  shouldScrollToWorkHours = true;
  loadEvents();
});

document.getElementById("refresh-calendar").addEventListener("click", () => {
  loadEvents({ manualRefresh: true });
});

document.getElementById("week-start").addEventListener("change", () => {
  state.weekStart = document.getElementById("week-start").value;
  shouldScrollToWorkHours = true;
  loadEvents();
});

document.getElementById("mini-calendar").addEventListener("click", (event) => {
  const monthButton = event.target.closest("[data-month-step]");
  if (monthButton) {
    const base = dateFromInput(state.weekStart);
    base.setMonth(base.getMonth() + Number(monthButton.dataset.monthStep));
    document.getElementById("week-start").value = isoDate(base);
    state.weekStart = isoDate(base);
    renderCalendar();
    return;
  }
  const dayButton = event.target.closest("[data-mini-date]");
  if (!dayButton) return;
  const clicked = dateFromInput(dayButton.dataset.miniDate);
  clicked.setDate(clicked.getDate() - ((clicked.getDay() + 6) % 7));
  document.getElementById("week-start").value = isoDate(clicked);
  shouldScrollToWorkHours = true;
  loadEvents();
});

function updateEmployeeNameFromEvents(email, events) {
  for (const event of events) {
    for (const participant of event.participants || []) {
      if (String(participant.email || "").toLowerCase() === email && participant.name) {
        rememberEmployeeName(email, participant.name);
        return;
      }
    }
  }
}

function ownerAccepted(event) {
  const owner = String(event.owner_email || "").toLowerCase();
  const participant = (event.participants || []).find((item) => String(item.email || "").toLowerCase() === owner);
  if (!participant) return false;
  return String(participant.status || "").toLowerCase() === "придет";
}

function renderParticipants(participants) {
  if (!participants.length) return "";
  return `
    <section class="participants">
      <h4>Участники</h4>
      <div class="participant-list">
        ${participants.map((participant) => {
          const status = String(participant.status || "").toLowerCase();
          const statusClass = status.includes("не") ? "declined" : status.includes("придет") ? "accepted" : status.includes("вопрос") ? "tentative" : "";
          const icon = statusClass === "accepted" ? "✓" : statusClass === "declined" ? "×" : statusClass === "tentative" ? "?" : "";
          return `
            <div class="participant-row ${statusClass}">
              ${icon ? `<span class="participant-status">${icon}</span>` : '<span class="participant-status empty"></span>'}
              <span class="participant-name">${escapeHtml(participant.name)}</span>
              ${participant.status ? `<span class="participant-label">${escapeHtml(participant.status)}</span>` : ""}
            </div>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

renderEmployees();
renderCalendar();
if (state.employees.length) {
  loadEvents();
}
