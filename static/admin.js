const accessList = document.getElementById("access-list");
const accessEmpty = document.getElementById("access-empty");

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
  try {
    payload = await response.json();
  } catch (_) {
    payload = {};
  }
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Требуется повторный вход.");
  }
  if (response.status === 403) {
    window.location.assign("/");
    throw new Error("Недостаточно прав.");
  }
  if (!response.ok) {
    throw new Error(payload.detail || "Запрос завершился ошибкой.");
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

function calendarText(user) {
  if (user.allow_all) return "Все календари";
  const calendars = user.allowed_calendars || [];
  return calendars.length ? calendars.join(", ") : "Нет доступных календарей";
}

function parseCalendarInput(value) {
  return String(value || "")
    .split(/[\s,;]+/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function renderAccessUsers(items) {
  accessEmpty.classList.toggle("hidden", items.length > 0);
  accessList.innerHTML = items.map((user) => `
    <article class="access-row">
      <div class="access-identity">
        <input class="access-login-input" type="text" value="${escapeHtml(user.email)}" data-access-email="${user.id}" aria-label="Учетка пользователя" />
        ${user.full_name ? `<p class="person-detail">${escapeHtml(user.full_name)}</p>` : ""}
      </div>
      <div class="access-controls">
        <select class="role-select" data-access-role="${user.id}" aria-label="Роль ${escapeHtml(user.email)}">
          <option value="user" ${user.role === "user" ? "selected" : ""}>Пользователь</option>
          <option value="admin" ${user.role === "admin" ? "selected" : ""}>Админ</option>
        </select>
        <label class="checkbox-field compact">
          <input type="checkbox" data-access-all="${user.id}" ${user.allow_all ? "checked" : ""} />
          <span>Все</span>
        </label>
        <textarea data-access-calendars="${user.id}" rows="2" aria-label="Календари ${escapeHtml(user.email)}" ${user.allow_all ? "disabled" : ""}>${escapeHtml((user.allowed_calendars || []).join("\\n"))}</textarea>
        <span class="access-summary">${escapeHtml(calendarText(user))}</span>
      </div>
      <div class="access-actions">
        <button class="secondary-button" type="button" data-access-save="${user.id}">Сохранить</button>
        <button class="delete-button" type="button" data-access-delete="${user.id}">Удалить</button>
      </div>
    </article>
  `).join("");
}

async function reloadAccessUsers(items = null) {
  const payload = items ? { items } : await requestJson("/api/admin/access-users");
  renderAccessUsers(payload.items);
}

function rowPayload(id) {
  return {
    email: document.querySelector(`[data-access-email="${id}"]`).value,
    role: document.querySelector(`[data-access-role="${id}"]`).value,
    allow_all: document.querySelector(`[data-access-all="${id}"]`).checked,
    allowed_calendars: parseCalendarInput(document.querySelector(`[data-access-calendars="${id}"]`).value),
  };
}

document.getElementById("access-allow-all").addEventListener("change", (event) => {
  document.getElementById("access-calendars").disabled = event.target.checked;
});

document.getElementById("access-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("access-email");
  const role = document.getElementById("access-role");
  const allowAll = document.getElementById("access-allow-all");
  const calendars = document.getElementById("access-calendars");
  try {
    const payload = await requestJson("/api/admin/access-users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.value,
        role: role.value,
        allow_all: allowAll.checked,
        allowed_calendars: parseCalendarInput(calendars.value),
      }),
    });
    email.value = "";
    role.value = "user";
    allowAll.checked = false;
    calendars.value = "";
    calendars.disabled = false;
    await reloadAccessUsers(payload.items);
    toast("Доступ добавлен.");
  } catch (error) {
    toast(error.message, "error");
  }
});

accessList.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-access-all]");
  if (!checkbox) return;
  document.querySelector(`[data-access-calendars="${checkbox.dataset.accessAll}"]`).disabled = checkbox.checked;
});

accessList.addEventListener("click", async (event) => {
  const saveButton = event.target.closest("[data-access-save]");
  const deleteButton = event.target.closest("[data-access-delete]");
  try {
    if (saveButton) {
      const payload = await requestJson(`/api/admin/access-users/${saveButton.dataset.accessSave}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(rowPayload(saveButton.dataset.accessSave)),
      });
      await reloadAccessUsers(payload.items);
      toast("Доступ обновлен.");
    }
    if (deleteButton) {
      const payload = await requestJson(`/api/admin/access-users/${deleteButton.dataset.accessDelete}`, {
        method: "DELETE",
      });
      await reloadAccessUsers(payload.items);
      toast("Доступ удален.");
    }
  } catch (error) {
    toast(error.message, "error");
  }
});

reloadAccessUsers().catch((error) => toast(error.message, "error"));
