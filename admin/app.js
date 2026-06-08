(() => {
  "use strict";

  const TOKEN_STORAGE_KEY = "jo_admin_token";
  const PAGE_SIZE = 50;

  const state = {
    token: sessionStorage.getItem(TOKEN_STORAGE_KEY) || "",
    page: 0,
    hasMore: false,
    totalUsers: 0,
    startedUsers: 0,
  };

  function byId(id) {
    return document.getElementById(id);
  }

  const refs = {
    loginOverlay: byId("loginOverlay"),
    loginForm: byId("loginForm"),
    loginSubtitle: byId("loginSubtitle"),
    loginHint: byId("loginHint"),
    loginError: byId("loginError"),
    tokenSigninInput: byId("tokenSigninInput"),
    tokenSigninBtn: byId("tokenSigninBtn"),
    telegramLoginBtn: byId("telegramLoginBtn"),
    shell: byId("shell"),
    refreshBtn: byId("refreshBtn"),
    logoutBtn: byId("logoutBtn"),
    startedUsersCount: byId("startedUsersCount"),
    totalUsersCount: byId("totalUsersCount"),
    usersSearch: byId("usersSearch"),
    usersApply: byId("usersApply"),
    usersTableBody: byId("usersTableBody"),
    usersPrev: byId("usersPrev"),
    usersNext: byId("usersNext"),
    usersPageInfo: byId("usersPageInfo"),
    toast: byId("toast"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatNumber(value) {
    const parsed = Number(value ?? 0);
    return Number.isFinite(parsed) ? parsed.toLocaleString() : "0";
  }

  function userName(row) {
    const username = String(row.username || "").trim();
    const first = String(row.first_name || "").trim();
    const last = String(row.last_name || "").trim();
    const fullName = [first, last].filter(Boolean).join(" ").trim();
    if (fullName && username) {
      return `${fullName} (@${username})`;
    }
    if (fullName) {
      return fullName;
    }
    if (username) {
      return `@${username}`;
    }
    return "Unknown";
  }

  function showToast(message, isError = false) {
    if (!refs.toast) {
      return;
    }
    refs.toast.hidden = false;
    refs.toast.textContent = String(message || "Done.");
    refs.toast.classList.toggle("error", Boolean(isError));
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => {
      refs.toast.hidden = true;
    }, 3200);
  }

  function showLogin(message = "") {
    if (refs.loginOverlay) refs.loginOverlay.hidden = false;
    if (refs.shell) refs.shell.hidden = true;
    if (refs.loginError) {
      refs.loginError.hidden = !message;
      refs.loginError.textContent = message;
    }
  }

  function hideLogin() {
    if (refs.loginOverlay) refs.loginOverlay.hidden = true;
    if (refs.shell) refs.shell.hidden = false;
    if (refs.loginError) {
      refs.loginError.hidden = true;
      refs.loginError.textContent = "";
    }
  }

  function requestHeaders(auth = true) {
    const headers = { Accept: "application/json" };
    if (auth && state.token) {
      headers["x-admin-token"] = state.token;
    }
    return headers;
  }

  async function requestJson(path, { method = "GET", params = null, body = null, auth = true, extraHeaders = {} } = {}) {
    const url = new URL(path, window.location.origin);
    url.searchParams.set("_ts", String(Date.now()));
    if (params && typeof params === "object") {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== "") {
          url.searchParams.set(key, String(value));
        }
      }
    }

    const headers = { ...requestHeaders(auth), ...extraHeaders };
    if (method !== "GET" && body !== null) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetch(url.toString(), {
      method,
      headers,
      credentials: "same-origin",
      body: method !== "GET" && body !== null ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });

    const raw = await response.text();
    let payload = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch (_error) {
        payload = { error: raw.slice(0, 320) };
      }
    }

    if (!response.ok) {
      const message = String(payload.error || payload.detail || payload.message || `Request failed (${response.status}).`);
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }

    return payload;
  }

  function handleAuthError(error) {
    if (!error || (error.status !== 401 && error.status !== 403)) {
      return false;
    }
    state.token = "";
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    showLogin("Session expired. Please sign in again.");
    return true;
  }

  function renderUsers(items) {
    if (!refs.usersTableBody) {
      return;
    }
    if (!Array.isArray(items) || !items.length) {
      refs.usersTableBody.innerHTML = `<tr><td colspan="2">No users found.</td></tr>`;
      return;
    }
    refs.usersTableBody.innerHTML = items.map((row) => {
      const name = userName(row);
      const id = String(row.telegram_id || "-");
      return `<tr><td>${escapeHtml(name)}</td><td><code>${escapeHtml(id)}</code></td></tr>`;
    }).join("");
  }

  function renderCounts() {
    if (refs.startedUsersCount) refs.startedUsersCount.textContent = formatNumber(state.startedUsers);
    if (refs.totalUsersCount) refs.totalUsersCount.textContent = formatNumber(state.totalUsers);
  }

  function renderPager() {
    const totalPages = Math.max(1, Math.ceil(state.totalUsers / PAGE_SIZE));
    const currentPage = state.page + 1;
    if (refs.usersPageInfo) {
      refs.usersPageInfo.textContent = `Page ${formatNumber(currentPage)} of ${formatNumber(totalPages)}`;
    }
    if (refs.usersPrev) refs.usersPrev.disabled = state.page <= 0;
    if (refs.usersNext) refs.usersNext.disabled = !state.hasMore;
  }

  async function loadStatusConfig() {
    try {
      const payload = await requestJson("/api/admin/status", { auth: false });
      if (refs.loginSubtitle) {
        refs.loginSubtitle.textContent = payload.token_auth_enabled || payload.telegram_auth_enabled
          ? "Sign in to view bot users."
          : "Admin authentication is not configured.";
      }
      if (refs.loginHint) {
        refs.loginHint.textContent = payload.telegram_auth_enabled
          ? "Approved admins can use token or Telegram login."
          : "Use the configured admin token.";
      }
      return payload;
    } catch (_error) {
      return null;
    }
  }

  async function verifySession() {
    const payload = await requestJson("/api/admin/auth", { auth: Boolean(state.token) });
    if (payload.ok !== true) {
      throw new Error("Admin session check failed.");
    }
    return payload;
  }

  function telegramContext() {
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (!tg) return { initData: "", telegramId: "" };
    const initData = typeof tg.initData === "string" ? tg.initData.trim() : "";
    const unsafe = tg.initDataUnsafe && typeof tg.initDataUnsafe === "object" ? tg.initDataUnsafe : null;
    const telegramId = unsafe && unsafe.user && typeof unsafe.user.id !== "undefined" ? String(unsafe.user.id) : "";
    return { initData, telegramId };
  }

  async function loginWithToken() {
    const token = String(refs.tokenSigninInput ? refs.tokenSigninInput.value : "").trim();
    if (!token) {
      showLogin("Enter your admin token.");
      return;
    }
    try {
      const payload = await requestJson("/api/admin/auth/token", {
        method: "POST",
        auth: false,
        body: { token },
      });
      const sessionToken = String(payload.token || "").trim();
      if (!sessionToken) {
        throw new Error("Token sign-in failed.");
      }
      state.token = sessionToken;
      sessionStorage.setItem(TOKEN_STORAGE_KEY, sessionToken);
      if (refs.tokenSigninInput) refs.tokenSigninInput.value = "";
      await verifySession();
      hideLogin();
      await loadDashboard(true);
    } catch (error) {
      showLogin(error.message || "Token sign-in failed.");
      showToast(error.message || "Token sign-in failed.", true);
    }
  }

  async function completeTelegramAuth(requestOptions) {
    try {
      const payload = await requestJson("/api/admin/auth/telegram", {
        auth: false,
        ...requestOptions,
      });
      const token = String(payload.token || "").trim();
      if (token) {
        state.token = token;
        sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
      }
      await verifySession();
      hideLogin();
      await loadDashboard(true);
    } catch (error) {
      showLogin(error.message || "Telegram login failed.");
      showToast(error.message || "Telegram login failed.", true);
    }
  }

  async function loginWithTelegramContext() {
    const context = telegramContext();
    if (!context.initData) {
      showLogin("Use Telegram login below or open this page from Telegram.");
      showToast("Telegram context not detected.", true);
      return;
    }
    await completeTelegramAuth({
      extraHeaders: {
        "x-telegram-init-data": context.initData,
        "x-telegram-id": context.telegramId,
      },
    });
  }

  async function logout() {
    try {
      await requestJson("/api/admin/auth/logout", {
        method: "POST",
        auth: Boolean(state.token),
        body: {},
      });
    } catch (_error) {
      // Ignore logout errors so local session is still cleared.
    }
    state.token = "";
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    showLogin("Logged out.");
  }

  async function loadOverview() {
    const payload = await requestJson("/api/admin/overview");
    const summary = payload && typeof payload === "object" ? payload.summary || {} : {};
    state.startedUsers = Number(summary.total_started_users ?? 0);
    renderCounts();
  }

  async function loadUsers() {
    const payload = await requestJson("/api/admin/users", {
      params: {
        limit: PAGE_SIZE,
        offset: state.page * PAGE_SIZE,
        search: refs.usersSearch ? refs.usersSearch.value.trim() : "",
        active_days: 60,
      },
    });
    const items = Array.isArray(payload.items) ? payload.items : [];
    state.totalUsers = Number(payload.total || 0);
    state.hasMore = Boolean(payload.has_more);
    if (!state.startedUsers && items.length) {
      state.startedUsers = items.filter((row) => row.has_started).length;
    }
    renderCounts();
    renderUsers(items);
    renderPager();
  }

  async function loadDashboard(force = false) {
    void force;
    if (refs.usersTableBody) {
      refs.usersTableBody.innerHTML = `<tr><td colspan="2">Loading users...</td></tr>`;
    }
    try {
      await Promise.all([loadOverview(), loadUsers()]);
    } catch (error) {
      if (handleAuthError(error)) return;
      renderUsers([]);
      showToast(error.message || "Failed to load users.", true);
    }
  }

  function bindEvents() {
    if (refs.loginForm) {
      refs.loginForm.addEventListener("submit", (event) => {
        event.preventDefault();
        loginWithToken();
      });
    }
    if (refs.telegramLoginBtn) refs.telegramLoginBtn.addEventListener("click", () => loginWithTelegramContext());
    if (refs.logoutBtn) refs.logoutBtn.addEventListener("click", () => logout());
    if (refs.refreshBtn) refs.refreshBtn.addEventListener("click", () => loadDashboard(true));
    if (refs.usersApply) {
      refs.usersApply.addEventListener("click", () => {
        state.page = 0;
        loadDashboard(true);
      });
    }
    if (refs.usersSearch) {
      refs.usersSearch.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          state.page = 0;
          loadDashboard(true);
        }
      });
    }
    if (refs.usersPrev) {
      refs.usersPrev.addEventListener("click", () => {
        if (state.page <= 0) return;
        state.page -= 1;
        loadDashboard(true);
      });
    }
    if (refs.usersNext) {
      refs.usersNext.addEventListener("click", () => {
        if (!state.hasMore) return;
        state.page += 1;
        loadDashboard(true);
      });
    }
  }

  async function init() {
    bindEvents();
    await loadStatusConfig();
    if (!state.token) {
      showLogin();
      return;
    }
    try {
      await verifySession();
      hideLogin();
      await loadDashboard(true);
    } catch (error) {
      if (!handleAuthError(error)) {
        showLogin(error.message || "Please sign in again.");
      }
    }
  }

  window.onTelegramAuth = function onTelegramAuth(user) {
    if (!user || typeof user !== "object") {
      showLogin("Invalid Telegram login payload.");
      return;
    }
    completeTelegramAuth({ method: "POST", body: user });
  };

  window.addEventListener("DOMContentLoaded", init);
})();
