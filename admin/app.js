
(() => {
  "use strict";

  const TOKEN_STORAGE_KEY = "jo_admin_token";
  const PAGE_SIZE = 25;

  const SECTION_TITLES = {
    overview: "Overview",
    users: "User Management",
    safety: "Safety",
    conversations: "Conversations",
    media: "Media",
    referrals: "Referrals",
    engagement: "Broadcast / Engagement",
    "bot-status": "Bot Status",
    settings: "Settings",
    logs: "Logs / Errors",
  };

  const state = {
    token: sessionStorage.getItem(TOKEN_STORAGE_KEY) || "",
    section: "overview",
    pages: { users: 0, safety: 0, conversations: 0, media: 0, referrals: 0 },
    hasMore: { users: false, safety: false, conversations: false, media: false, referrals: false },
    totals: { users: 0, safety: 0, conversations: 0, media: 0, referrals: 0 },
    loaded: {
      overview: false,
      users: false,
      safety: false,
      conversations: false,
      media: false,
      referrals: false,
      engagement: false,
      botStatus: false,
      settings: false,
      logs: false,
    },
    statusConfig: null,
    selectedUserId: null,
    userProfile: null,
  };

  function byId(id) {
    return document.getElementById(id);
  }

  const refs = {
    loginOverlay: byId("loginOverlay"),
    loginSubtitle: byId("loginSubtitle"),
    loginHint: byId("loginHint"),
    loginError: byId("loginError"),
    tokenSigninInput: byId("tokenSigninInput"),
    tokenSigninBtn: byId("tokenSigninBtn"),
    telegramLoginBtn: byId("telegramLoginBtn"),
    telegramWidgetWrap: byId("telegramWidgetWrap"),

    shell: byId("shell"),
    navButtons: [...document.querySelectorAll(".nav-btn, .section-tab")],
    menuToggle: byId("menuToggle"),
    pageTitle: byId("pageTitle"),
    refreshBtn: byId("refreshBtn"),
    logoutBtn: byId("logoutBtn"),
    authChip: byId("authChip"),

    overviewSummary: byId("overviewSummary"),
    overviewRecent: byId("overviewRecent"),

    usersSearch: byId("usersSearch"),
    usersActiveWindow: byId("usersActiveWindow"),
    usersApply: byId("usersApply"),
    usersList: byId("usersList"),
    usersPrev: byId("usersPrev"),
    usersNext: byId("usersNext"),
    usersPageInfo: byId("usersPageInfo"),
    userProfileTitle: byId("userProfileTitle"),
    userProfileChip: byId("userProfileChip"),
    userProfileHint: byId("userProfileHint"),
    userProfileMeta: byId("userProfileMeta"),
    userActionReason: byId("userActionReason"),
    userWarnMessage: byId("userWarnMessage"),
    userWarnBtn: byId("userWarnBtn"),
    userBlockBtn: byId("userBlockBtn"),
    userUnblockBtn: byId("userUnblockBtn"),
    userKickBtn: byId("userKickBtn"),
    userDirectMessage: byId("userDirectMessage"),
    userSendMessageBtn: byId("userSendMessageBtn"),
    userProfileActivity: byId("userProfileActivity"),

    safetySearch: byId("safetySearch"),
    safetyApply: byId("safetyApply"),
    safetySummary: byId("safetySummary"),
    safetyList: byId("safetyList"),
    safetyPrev: byId("safetyPrev"),
    safetyNext: byId("safetyNext"),
    safetyPageInfo: byId("safetyPageInfo"),

    convSearch: byId("convSearch"),
    convType: byId("convType"),
    convFrontend: byId("convFrontend"),
    convDateFrom: byId("convDateFrom"),
    convDateTo: byId("convDateTo"),
    convApply: byId("convApply"),
    conversationsList: byId("conversationsList"),
    convPrev: byId("convPrev"),
    convNext: byId("convNext"),
    convPageInfo: byId("convPageInfo"),

    mediaSearch: byId("mediaSearch"),
    mediaApply: byId("mediaApply"),
    mediaSummary: byId("mediaSummary"),
    mediaList: byId("mediaList"),
    mediaPrev: byId("mediaPrev"),
    mediaNext: byId("mediaNext"),
    mediaPageInfo: byId("mediaPageInfo"),

    refSearch: byId("refSearch"),
    refApply: byId("refApply"),
    refSummary: byId("refSummary"),
    refList: byId("refList"),
    refPrev: byId("refPrev"),
    refNext: byId("refNext"),
    refPageInfo: byId("refPageInfo"),

    engEnabled: byId("engEnabled"),
    engInactivity: byId("engInactivity"),
    engCooldown: byId("engCooldown"),
    engBatch: byId("engBatch"),
    engMessage: byId("engMessage"),
    engSave: byId("engSave"),
    engUpdated: byId("engUpdated"),

    botStatusRefresh: byId("botStatusRefresh"),
    botStatusGrid: byId("botStatusGrid"),
    botWarnings: byId("botWarnings"),

    statusInfo: byId("statusInfo"),
    settingsLogout: byId("settingsLogout"),

    logsLevel: byId("logsLevel"),
    logsSearch: byId("logsSearch"),
    logsLimit: byId("logsLimit"),
    logsApply: byId("logsApply"),
    logsOutput: byId("logsOutput"),

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

  function formatDateTime(value) {
    if (!value) {
      return "-";
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
  }

  function userLabel(row) {
    const username = String(row.username || "").trim();
    const first = String(row.first_name || "").trim();
    const last = String(row.last_name || "").trim();
    const name = [first, last].filter(Boolean).join(" ").trim();
    const idPart = username ? `@${username}` : name || "unknown";
    return `${idPart} (${row.telegram_id || "?"})`;
  }

  function showToast(message, isError = false) {
    if (!refs.toast) {
      return;
    }
    refs.toast.hidden = false;
    refs.toast.textContent = String(message || "Done.");
    refs.toast.style.background = isError ? "#8a1f39" : "#143868";
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => {
      refs.toast.hidden = true;
    }, 3200);
  }

  function setAuthChip(authorized) {
    if (!refs.authChip) {
      return;
    }
    refs.authChip.textContent = authorized ? "Authorized" : "Locked";
    refs.authChip.style.background = authorized ? "#0f4b3b" : "#1b2b47";
    refs.authChip.style.color = authorized ? "#d8ffea" : "#c3d3f3";
    refs.authChip.style.borderColor = authorized ? "#1d6f58" : "#375789";
  }

  function showLogin(errorMessage = "") {
    if (refs.loginOverlay) refs.loginOverlay.hidden = false;
    if (refs.shell) refs.shell.hidden = true;
    if (refs.loginError) {
      refs.loginError.hidden = !errorMessage;
      refs.loginError.textContent = errorMessage;
    }
    setAuthChip(false);
  }

  function hideLogin() {
    if (refs.loginOverlay) refs.loginOverlay.hidden = true;
    if (refs.shell) refs.shell.hidden = false;
    if (refs.loginError) {
      refs.loginError.hidden = true;
      refs.loginError.textContent = "";
    }
    setAuthChip(true);
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
      const error = new Error(message || `Request failed (${response.status}).`);
      error.status = response.status;
      error.payload = payload;
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
    showToast("Admin session expired.", true);
    return true;
  }

  function metricCard(label, value) {
    return `<article class="metric"><p class="label">${escapeHtml(label)}</p><p class="value">${escapeHtml(value)}</p></article>`;
  }

  function renderEmpty(container, message) {
    if (!container) {
      return;
    }
    container.innerHTML = `<article class="list-item"><p>${escapeHtml(message)}</p></article>`;
  }

  function mediaRef(item) {
    const preview = String(item.preview_ref || "").trim();
    if (preview) return preview;
    const mediaUrl = String(item.media_url || "").trim();
    if (mediaUrl) return mediaUrl;
    const storagePath = String(item.storage_path || "").trim();
    if (storagePath.startsWith("telegram_file:")) {
      return `/api/admin/media/proxy?ref=${encodeURIComponent(storagePath)}`;
    }
    return storagePath || "";
  }

  function renderMediaBlock(row, altText) {
    const reference = mediaRef(row);
    if (!reference) {
      return "";
    }
    const mediaType = String(row.media_type || "").toLowerCase();
    if (mediaType.startsWith("video")) {
      return `<video class="media-video" src="${escapeHtml(reference)}" controls preload="metadata"></video>`;
    }
    return `<img class="media-thumb" src="${escapeHtml(reference)}" alt="${escapeHtml(altText || "Media preview")}" loading="lazy">`;
  }

  function sectionElement(name) {
    return byId(`section-${name}`);
  }

  function setSection(name) {
    state.section = name;
    for (const button of refs.navButtons) {
      button.classList.toggle("active", button.dataset.section === name);
    }
    for (const key of Object.keys(SECTION_TITLES)) {
      const section = sectionElement(key);
      if (section) {
        section.classList.toggle("active", key === name);
      }
    }
    if (refs.pageTitle) {
      refs.pageTitle.textContent = SECTION_TITLES[name] || "Admin";
    }
  }

  function resetPage(key) {
    state.pages[key] = 0;
    state.hasMore[key] = false;
  }

  function pageInfo(key, total) {
    const currentPage = state.pages[key] + 1;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    return `Page ${currentPage} / ${totalPages} (${formatNumber(total)} total)`;
  }

  async function copyText(value) {
    const text = String(value || "");
    if (!text) {
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      showToast("Copied.");
      return;
    }
    showToast("Copy is not available in this browser.", true);
  }

  function setUserControlsEnabled(enabled) {
    const allow = Boolean(enabled);
    if (refs.userWarnBtn) refs.userWarnBtn.disabled = !allow;
    if (refs.userWarnMessage) refs.userWarnMessage.disabled = !allow;
    if (refs.userBlockBtn) refs.userBlockBtn.disabled = !allow;
    if (refs.userUnblockBtn) refs.userUnblockBtn.disabled = !allow;
    if (refs.userKickBtn) refs.userKickBtn.disabled = !allow;
    if (refs.userDirectMessage) refs.userDirectMessage.disabled = !allow;
    if (refs.userSendMessageBtn) refs.userSendMessageBtn.disabled = !allow;
  }

  function renderUserProfileEmpty(message = "Select a user from the list to view details and actions.") {
    state.userProfile = null;
    if (refs.userProfileTitle) refs.userProfileTitle.textContent = "User Profile";
    if (refs.userProfileChip) {
      refs.userProfileChip.textContent = "No user selected";
      refs.userProfileChip.className = "chip muted-chip";
    }
    if (refs.userProfileHint) refs.userProfileHint.textContent = message;
    if (refs.userProfileMeta) refs.userProfileMeta.innerHTML = "";
    if (refs.userProfileActivity) renderEmpty(refs.userProfileActivity, "No user activity yet.");
    if (refs.userWarnMessage) refs.userWarnMessage.value = "";
    if (refs.userDirectMessage) refs.userDirectMessage.value = "";
    setUserControlsEnabled(false);
  }

  function setSelectedUserRow() {
    if (!refs.usersList) return;
    const selectedId = Number(state.selectedUserId || 0);
    const cards = refs.usersList.querySelectorAll(".list-item[data-user-id]");
    for (const card of cards) {
      const rowId = Number(card.getAttribute("data-user-id") || "0");
      card.classList.toggle("selected", selectedId > 0 && rowId === selectedId);
    }
  }

  function renderUserProfile(profilePayload) {
    const profile = profilePayload && typeof profilePayload === "object" ? profilePayload.user : null;
    const summary = profilePayload && typeof profilePayload === "object" ? profilePayload.summary || {} : {};
    const activityItems = profilePayload && typeof profilePayload === "object" && Array.isArray(profilePayload.recent_activity)
      ? profilePayload.recent_activity
      : [];
    if (!profile || !profile.telegram_id) {
      renderUserProfileEmpty("Unable to load user profile.");
      return;
    }
    state.userProfile = profilePayload;
    if (refs.userProfileTitle) refs.userProfileTitle.textContent = userLabel(profile);
    if (refs.userProfileChip) {
      const chipClass = profile.is_blocked ? "danger-chip" : profile.is_active ? "ok-chip" : "muted-chip";
      const chipLabel = profile.is_blocked ? profile.status || "blocked" : profile.is_active ? "active" : profile.status || "inactive";
      refs.userProfileChip.textContent = chipLabel;
      refs.userProfileChip.className = `chip ${chipClass}`;
    }
    if (refs.userProfileHint) {
      refs.userProfileHint.textContent = `Warnings sent: ${formatNumber(summary.warnings_sent_count)} | Blocked prompts: ${formatNumber(summary.blocked_prompt_count)} | Recent records: ${formatNumber(summary.recent_activity_count)}`;
    }
    if (refs.userProfileMeta) {
      refs.userProfileMeta.innerHTML = [
        `Telegram ID: ${escapeHtml(profile.telegram_id)}`,
        `Status: ${escapeHtml(profile.status || "-")}`,
        `First seen: ${escapeHtml(formatDateTime(profile.first_seen_at))}`,
        `Last seen: ${escapeHtml(formatDateTime(profile.last_seen_at))}`,
        `Messages: ${escapeHtml(formatNumber(profile.total_messages))}`,
        `Images: ${escapeHtml(formatNumber(profile.total_images))}`,
        `Unreachable: ${escapeHtml(formatNumber(profile.unreachable_count))}`,
        `Referral code: ${escapeHtml(profile.referral_code || "-")}`,
      ].map((item) => `<span>${item}</span>`).join("");
    }

    if (!activityItems.length) {
      renderEmpty(refs.userProfileActivity, "No recent user activity.");
    } else if (refs.userProfileActivity) {
      refs.userProfileActivity.innerHTML = activityItems.map((row) => {
        const preview = row.user_message || row.text_content || row.bot_reply || "-";
        return `<article class=\"list-item\"><div class=\"row-head\"><h4>${escapeHtml(row.feature_used || row.message_type || "-")}</h4><span class=\"chip ${row.success ? "ok-chip" : "danger-chip"}\">${row.success ? "success" : "failed"}</span></div><p>${escapeHtml(preview)}</p><div class=\"list-meta\"><span>${escapeHtml(formatDateTime(row.created_at))}</span><span>Type: ${escapeHtml(row.message_type || "-")}</span><span>Frontend: ${escapeHtml(row.frontend_source || "-")}</span></div></article>`;
      }).join("");
    }
    setUserControlsEnabled(true);
    if (refs.userWarnBtn) refs.userWarnBtn.disabled = false;
    if (refs.userBlockBtn) refs.userBlockBtn.disabled = Boolean(profile.is_blocked);
    if (refs.userUnblockBtn) refs.userUnblockBtn.disabled = !Boolean(profile.is_blocked);
    if (refs.userKickBtn) refs.userKickBtn.disabled = String(profile.status || "").toLowerCase() === "kicked";
    setSelectedUserRow();
  }

  async function loadStatusConfig(force = false) {
    if (state.statusConfig && !force) {
      return state.statusConfig;
    }
    try {
      const payload = await requestJson("/api/admin/status", { auth: false });
      state.statusConfig = payload;
      const tokenEnabled = Boolean(payload.token_auth_enabled);
      const telegramEnabled = Boolean(payload.telegram_auth_enabled);
      if (refs.loginSubtitle) {
        refs.loginSubtitle.textContent = tokenEnabled && telegramEnabled
          ? "Secure access via token or Telegram identity."
          : tokenEnabled
            ? "Secure access via admin token."
            : "Secure access via Telegram identity.";
      }
      if (refs.loginHint) {
        refs.loginHint.textContent = tokenEnabled
          ? "Token sign-in is enabled on this backend."
          : "Token sign-in is disabled in backend config.";
      }
      if (refs.tokenSigninBtn) refs.tokenSigninBtn.disabled = !tokenEnabled;
      if (refs.tokenSigninInput) refs.tokenSigninInput.disabled = !tokenEnabled;
      if (refs.telegramLoginBtn) refs.telegramLoginBtn.disabled = !telegramEnabled;
      if (refs.telegramWidgetWrap) {
        refs.telegramWidgetWrap.style.opacity = telegramEnabled ? "1" : "0.5";
        refs.telegramWidgetWrap.style.pointerEvents = telegramEnabled ? "auto" : "none";
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
      state.loaded.overview = false;
      await loadSection(state.section, true);
      showToast("Telegram admin login successful.");
    } catch (error) {
      showLogin(error.message || "Telegram admin login failed.");
      showToast(error.message || "Telegram admin login failed.", true);
    }
  }

  async function loginWithTelegramContext() {
    const context = telegramContext();
    if (!context.initData) {
      showLogin("Use Telegram login below or open this page from Telegram Mini App.");
      showToast("Telegram WebApp context not detected.", true);
      return;
    }
    await completeTelegramAuth({
      extraHeaders: {
        "x-telegram-init-data": context.initData,
        "x-telegram-id": context.telegramId,
      },
    });
  }

  async function loginWithTelegramWidget(user) {
    if (!user || typeof user !== "object") {
      showLogin("Invalid Telegram login payload.");
      return;
    }
    await completeTelegramAuth({ method: "POST", body: user });
  }

  async function loginWithToken() {
    const token = String(refs.tokenSigninInput ? refs.tokenSigninInput.value : "").trim();
    if (!token) {
      showLogin("Enter your admin sign-in token.");
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
      state.loaded.overview = false;
      await loadSection(state.section, true);
      showToast("Token sign-in successful.");
    } catch (error) {
      showLogin(error.message || "Token sign-in failed.");
      showToast(error.message || "Token sign-in failed.", true);
    }
  }

  async function logout() {
    try {
      await requestJson("/api/admin/auth/logout", {
        method: "POST",
        auth: Boolean(state.token),
        body: {},
      });
    } catch (_error) {
      // ignore
    }
    state.token = "";
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    state.selectedUserId = null;
    renderUserProfileEmpty();
    showLogin("Logged out.");
    showToast("Logged out.");
  }

  async function loadOverview(force = false) {
    if (!force && state.loaded.overview) return;
    try {
      const payload = await requestJson("/api/admin/overview");
      const summary = payload.summary || {};
      if (refs.overviewSummary) {
        refs.overviewSummary.innerHTML = [
          metricCard("Unique users", formatNumber(summary.unique_users)),
          metricCard("Started users", formatNumber(summary.total_started_users)),
          metricCard("Active users", formatNumber(summary.active_users)),
          metricCard("Blocked/unreachable", formatNumber(summary.blocked_users)),
          metricCard("New users today", formatNumber(summary.new_users_today)),
          metricCard("New users this week", formatNumber(summary.new_users_week)),
          metricCard("Referrals", formatNumber(summary.referrals_total)),
          metricCard("Messages", formatNumber(summary.total_messages)),
          metricCard("Images", formatNumber(summary.total_images)),
        ].join("");
      }
      const items = Array.isArray(payload.recent_activity) ? payload.recent_activity : [];
      if (!items.length) {
        renderEmpty(refs.overviewRecent, "No recent activity.");
      } else if (refs.overviewRecent) {
        refs.overviewRecent.innerHTML = items.map((item) => {
          const preview = item.preview || item.text_content || "";
          return `<article class="list-item"><div class="row-head"><h4>${escapeHtml(userLabel(item))}</h4><button class="btn small copy-btn" data-copy="${escapeHtml(preview)}">Copy</button></div><p>${escapeHtml(preview || "-")}</p><div class="list-meta"><span>${escapeHtml(formatDateTime(item.created_at))}</span><span>Type: ${escapeHtml(item.message_type || "-")}</span><span>Feature: ${escapeHtml(item.feature_used || "-")}</span><span>Frontend: ${escapeHtml(item.frontend_source || "-")}</span><span>Status: ${item.success ? "success" : "failed"}</span></div></article>`;
        }).join("");
      }
      state.loaded.overview = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      renderEmpty(refs.overviewRecent, "Failed to load overview.");
      showToast(error.message || "Failed to load overview.", true);
    }
  }

  async function loadUsers(force = false) {
    if (!force && state.loaded.users) return;
    try {
      const payload = await requestJson("/api/admin/users", {
        params: {
          limit: PAGE_SIZE,
          offset: state.pages.users * PAGE_SIZE,
          search: refs.usersSearch ? refs.usersSearch.value.trim() : "",
          active_days: refs.usersActiveWindow ? refs.usersActiveWindow.value : "7",
        },
      });
      const items = Array.isArray(payload.items) ? payload.items : [];
      state.totals.users = Number(payload.total || 0);
      state.hasMore.users = Boolean(payload.has_more);

      if (!items.length) {
        renderEmpty(refs.usersList, "No users found.");
      } else if (refs.usersList) {
        refs.usersList.innerHTML = items.map((row) => {
          const chipClass = row.is_blocked ? "danger-chip" : row.is_active ? "ok-chip" : "muted-chip";
          const chipLabel = row.is_blocked ? "blocked" : row.is_active ? "active" : "inactive";
          const selectedClass = Number(state.selectedUserId || 0) === Number(row.telegram_id) ? " selected" : "";
          const openButton = `<button class="btn small user-open-btn" data-user-id="${escapeHtml(row.telegram_id)}">Open</button>`;
          const warnButton = `<button class="btn small btn-warning user-action-btn" data-user-id="${escapeHtml(row.telegram_id)}" data-action="warn">Warn</button>`;
          const messageButton = `<button class="btn small user-action-btn" data-user-id="${escapeHtml(row.telegram_id)}" data-action="message">Message</button>`;
          const actionButtons = row.is_blocked
            ? `<button class="btn small user-action-btn" data-user-id="${escapeHtml(row.telegram_id)}" data-action="unblock">Unblock</button>`
            : `<button class="btn small btn-danger user-action-btn" data-user-id="${escapeHtml(row.telegram_id)}" data-action="block">Block</button>`;
          const kickButton = `<button class="btn small btn-danger user-action-btn" data-user-id="${escapeHtml(row.telegram_id)}" data-action="kick">Kick</button>`;
          return `<article class="list-item${selectedClass}" data-user-id="${escapeHtml(row.telegram_id)}"><div class="row-head"><h4>${escapeHtml(userLabel(row))}</h4><span class="chip ${chipClass}">${chipLabel}</span></div><div class="list-meta"><span>First seen: ${escapeHtml(formatDateTime(row.first_seen_at))}</span><span>Last seen: ${escapeHtml(formatDateTime(row.last_seen_at))}</span><span>Started: ${row.has_started ? "yes" : "no"}</span><span>Messages: ${escapeHtml(formatNumber(row.total_messages))}</span><span>Images: ${escapeHtml(formatNumber(row.total_images))}</span><span>Unreachable: ${escapeHtml(formatNumber(row.unreachable_count))}</span><span>Referral code: ${escapeHtml(row.referral_code || "-")}</span><span>Referred by: ${escapeHtml(row.referred_by || "-")}</span></div><div class="toolbar wrap">${openButton}${warnButton}${messageButton}${actionButtons}${kickButton}</div>${row.last_delivery_error ? `<p class="error">Last delivery error: ${escapeHtml(row.last_delivery_error)}</p>` : ""}</article>`;
        }).join("");
      }

      if (refs.usersPageInfo) refs.usersPageInfo.textContent = pageInfo("users", state.totals.users);
      if (refs.usersPrev) refs.usersPrev.disabled = state.pages.users <= 0;
      if (refs.usersNext) refs.usersNext.disabled = !state.hasMore.users;
      state.loaded.users = true;
      setSelectedUserRow();
    } catch (error) {
      if (handleAuthError(error)) return;
      renderEmpty(refs.usersList, "Failed to load users.");
      showToast(error.message || "Failed to load users.", true);
    }
  }

  async function loadUserProfile(userId, force = false) {
    const parsedId = Number(userId || 0);
    if (!parsedId) {
      renderUserProfileEmpty();
      return;
    }
    if (!force && state.userProfile && Number(state.userProfile.user?.telegram_id || 0) === parsedId) {
      return;
    }
    try {
      const payload = await requestJson(`/api/admin/users/${encodeURIComponent(String(parsedId))}`);
      state.selectedUserId = parsedId;
      renderUserProfile(payload);
      setSelectedUserRow();
    } catch (error) {
      if (handleAuthError(error)) return;
      renderUserProfileEmpty("Failed to load user profile.");
      showToast(error.message || "Failed to load user profile.", true);
    }
  }

  async function runUserAccessAction(action, userId) {
    const parsedId = Number(userId || state.selectedUserId || 0);
    if (!parsedId) {
      showToast("Select a user first.", true);
      return;
    }
    const actionLabel = String(action || "").trim().toLowerCase();
    if (!["block", "unblock", "kick"].includes(actionLabel)) {
      showToast("Unsupported action.", true);
      return;
    }
    const confirmed = window.confirm(`Confirm ${actionLabel} for user ${parsedId}?`);
    if (!confirmed) return;

    const reason = refs.userActionReason ? refs.userActionReason.value.trim() : "";
    try {
      await requestJson(`/api/admin/users/${encodeURIComponent(String(parsedId))}/${actionLabel}`, {
        method: "POST",
        body: { reason },
      });
      showToast(`User ${actionLabel} action applied.`);
      state.loaded.users = false;
      await Promise.all([
        loadUsers(true),
        loadUserProfile(parsedId, true),
      ]);
    } catch (error) {
      if (handleAuthError(error)) return;
      showToast(error.message || `Failed to ${actionLabel} user.`, true);
    }
  }

  async function sendWarningToUser(userId) {
    const parsedId = Number(userId || state.selectedUserId || 0);
    if (!parsedId) {
      showToast("Select a user first.", true);
      return;
    }
    const customWarning = refs.userWarnMessage ? refs.userWarnMessage.value.trim() : "";
    const confirmed = window.confirm(`Send warning to user ${parsedId}?`);
    if (!confirmed) return;
    try {
      await requestJson(`/api/admin/users/${encodeURIComponent(String(parsedId))}/warn`, {
        method: "POST",
        body: { message: customWarning || null },
      });
      if (refs.userWarnMessage) refs.userWarnMessage.value = "";
      showToast("Warning sent.");
      state.loaded.users = false;
      await Promise.all([
        loadUsers(true),
        loadUserProfile(parsedId, true),
      ]);
    } catch (error) {
      if (handleAuthError(error)) return;
      showToast(error.message || "Failed to send warning.", true);
    }
  }

  async function sendCustomMessageToUser(userId, messageText) {
    const parsedId = Number(userId || state.selectedUserId || 0);
    const message = String(messageText || "").trim();
    if (!parsedId) {
      showToast("Select a user first.", true);
      return false;
    }
    if (!message) {
      showToast("Message cannot be empty.", true);
      return false;
    }
    await requestJson(`/api/admin/users/${encodeURIComponent(String(parsedId))}/message`, {
      method: "POST",
      body: { message },
    });
    return true;
  }

  async function sendCustomMessagePrompt(userId) {
    const parsedId = Number(userId || state.selectedUserId || 0);
    if (!parsedId) {
      showToast("Select a user first.", true);
      return;
    }
    const selectedId = Number(state.selectedUserId || 0);
    const draft = refs.userDirectMessage && selectedId === parsedId ? refs.userDirectMessage.value.trim() : "";
    const entered = window.prompt(`Enter a custom message for user ${parsedId}:`, draft);
    if (entered === null) return;
    const message = String(entered || "").trim();
    if (!message) {
      showToast("Message cannot be empty.", true);
      return;
    }
    try {
      const sent = await sendCustomMessageToUser(parsedId, message);
      if (!sent) return;
      if (refs.userDirectMessage && selectedId === parsedId) refs.userDirectMessage.value = "";
      showToast("Custom message sent.");
      state.loaded.users = false;
      await Promise.all([
        loadUsers(true),
        loadUserProfile(parsedId, true),
      ]);
    } catch (error) {
      if (handleAuthError(error)) return;
      showToast(error.message || "Failed to send custom message.", true);
    }
  }

  async function sendDirectMessageToSelectedUser() {
    const parsedId = Number(state.selectedUserId || 0);
    if (!parsedId) {
      showToast("Select a user first.", true);
      return;
    }
    const message = refs.userDirectMessage ? refs.userDirectMessage.value.trim() : "";
    if (!message) {
      showToast("Write a message first.", true);
      return;
    }
    try {
      const sent = await sendCustomMessageToUser(parsedId, message);
      if (!sent) return;
      if (refs.userDirectMessage) refs.userDirectMessage.value = "";
      showToast("Custom message sent.");
      state.loaded.users = false;
      await Promise.all([
        loadUsers(true),
        loadUserProfile(parsedId, true),
      ]);
    } catch (error) {
      if (handleAuthError(error)) return;
      showToast(error.message || "Failed to send custom message.", true);
    }
  }

  async function loadSafety(force = false) {
    if (!force && state.loaded.safety) return;
    try {
      const payload = await requestJson("/api/admin/moderation", {
        params: {
          limit: PAGE_SIZE,
          offset: state.pages.safety * PAGE_SIZE,
          search: refs.safetySearch ? refs.safetySearch.value.trim() : "",
        },
      });
      const summary = payload.summary || {};
      const items = Array.isArray(payload.items) ? payload.items : [];
      state.totals.safety = Number(payload.total || 0);
      state.hasMore.safety = Boolean(payload.has_more);

      if (refs.safetySummary) {
        refs.safetySummary.innerHTML = [
          metricCard("Total blocked", formatNumber(summary.total_blocked)),
          metricCard("Blocked 24h", formatNumber(summary.blocked_last_24h)),
          metricCard("Blocked 7d", formatNumber(summary.blocked_last_7d)),
        ].join("");
      }
      if (!items.length) {
        renderEmpty(refs.safetyList, "No moderation blocks found.");
      } else if (refs.safetyList) {
        refs.safetyList.innerHTML = items.map((row) => {
          const copyTextValue = row.prompt || "";
          return `<article class="list-item"><div class="row-head"><h4>${escapeHtml(userLabel(row))}</h4><button class="btn small copy-btn" data-copy="${escapeHtml(copyTextValue)}">Copy prompt</button></div><p>${escapeHtml(row.prompt || "-")}</p><div class="list-meta"><span>${escapeHtml(formatDateTime(row.created_at))}</span><span>Reason: ${escapeHtml(row.moderation_reason || "-")}</span><span>Feature: ${escapeHtml(row.feature_used || "-")}</span><span>Model: ${escapeHtml(row.model_used || "-")}</span><span>Frontend: ${escapeHtml(row.frontend_source || "-")}</span></div></article>`;
        }).join("");
      }
      if (refs.safetyPageInfo) refs.safetyPageInfo.textContent = pageInfo("safety", state.totals.safety);
      if (refs.safetyPrev) refs.safetyPrev.disabled = state.pages.safety <= 0;
      if (refs.safetyNext) refs.safetyNext.disabled = !state.hasMore.safety;
      state.loaded.safety = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      renderEmpty(refs.safetyList, "Failed to load moderation logs.");
      showToast(error.message || "Failed to load moderation logs.", true);
    }
  }

  async function loadConversations(force = false) {
    if (!force && state.loaded.conversations) return;
    try {
      const payload = await requestJson("/api/admin/messages", {
        params: {
          limit: PAGE_SIZE,
          offset: state.pages.conversations * PAGE_SIZE,
          search: refs.convSearch ? refs.convSearch.value.trim() : "",
          message_type: refs.convType ? refs.convType.value : "all",
          frontend_source: refs.convFrontend ? refs.convFrontend.value : "all",
          date_from: refs.convDateFrom ? refs.convDateFrom.value : "",
          date_to: refs.convDateTo ? refs.convDateTo.value : "",
        },
      });
      const items = Array.isArray(payload.items) ? payload.items : [];
      state.totals.conversations = Number(payload.total || 0);
      state.hasMore.conversations = Boolean(payload.has_more);

      if (!items.length) {
        renderEmpty(refs.conversationsList, "No conversations found.");
      } else if (refs.conversationsList) {
        refs.conversationsList.innerHTML = items.map((row) => {
          const copyPayload = [`User: ${row.user_message || row.text_content || ""}`, `Assistant: ${row.bot_reply || ""}`].filter(Boolean).join("\n\n");
          return `<article class="list-item"><div class="row-head"><h4>${escapeHtml(userLabel(row))}</h4><button class="btn small copy-btn" data-copy="${escapeHtml(copyPayload)}">Copy chat</button></div><p><strong>User:</strong> ${escapeHtml(row.user_message || row.text_content || "-")}</p><p><strong>Assistant:</strong> ${escapeHtml(row.bot_reply || "-")}</p>${renderMediaBlock(row, "Conversation media")}<div class="list-meta"><span>${escapeHtml(formatDateTime(row.created_at))}</span><span>Feature: ${escapeHtml(row.feature_used || "-")}</span><span>Frontend: ${escapeHtml(row.frontend_source || "-")}</span><span>Type: ${escapeHtml(row.message_type || "-")}</span><span>Conversation: ${escapeHtml(row.conversation_id || "-")}</span><span>Model: ${escapeHtml(row.model_used || "-")}</span><span>Status: ${row.success ? "success" : "failed"}</span></div>${row.media_error_reason ? `<p class="error">Media issue: ${escapeHtml(row.media_error_reason)}</p>` : ""}</article>`;
        }).join("");
      }

      if (refs.convPageInfo) refs.convPageInfo.textContent = pageInfo("conversations", state.totals.conversations);
      if (refs.convPrev) refs.convPrev.disabled = state.pages.conversations <= 0;
      if (refs.convNext) refs.convNext.disabled = !state.hasMore.conversations;
      state.loaded.conversations = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      renderEmpty(refs.conversationsList, "Failed to load conversations.");
      showToast(error.message || "Failed to load conversations.", true);
    }
  }

  async function loadMedia(force = false) {
    if (!force && state.loaded.media) return;
    try {
      const payload = await requestJson("/api/admin/media", {
        params: {
          limit: PAGE_SIZE,
          offset: state.pages.media * PAGE_SIZE,
          search: refs.mediaSearch ? refs.mediaSearch.value.trim() : "",
        },
      });
      const summary = payload.summary || {};
      const items = Array.isArray(payload.items) ? payload.items : [];
      state.totals.media = Number(payload.total || 0);
      state.hasMore.media = Boolean(payload.has_more);

      if (refs.mediaSummary) {
        refs.mediaSummary.innerHTML = [
          metricCard("Total media", formatNumber(summary.total_media)),
          metricCard("Total images", formatNumber(summary.total_images)),
          metricCard("Total videos", formatNumber(summary.total_videos)),
          metricCard("Successful media", formatNumber(summary.successful_media)),
          metricCard("Successful images", formatNumber(summary.successful_images)),
          metricCard("Successful videos", formatNumber(summary.successful_videos)),
          metricCard("Media last 7 days", formatNumber(summary.media_last_7_days)),
          metricCard("Videos last 7 days", formatNumber(summary.videos_last_7_days)),
        ].join("");
      }

      if (!items.length) {
        renderEmpty(refs.mediaList, "No media records found.");
      } else if (refs.mediaList) {
        refs.mediaList.innerHTML = items.map((row) => {
          const mediaBlock = renderMediaBlock(row, "Media preview");
          const mediaIssue = row.media_error_reason || row.media_status || "media unavailable";
          return `<article class="list-item"><div class="row-head"><h4>${escapeHtml(userLabel(row))}</h4><span class="chip ${row.success ? "ok-chip" : "danger-chip"}">${row.success ? "success" : "failed"}</span></div>${mediaBlock || `<p class="error">No preview: ${escapeHtml(mediaIssue)}</p>`}<p><strong>Prompt:</strong> ${escapeHtml(row.prompt || row.text_content || "-")}</p><div class="list-meta"><span>${escapeHtml(formatDateTime(row.created_at))}</span><span>Type: ${escapeHtml(row.media_type || "-")}</span><span>Origin: ${escapeHtml(row.media_origin || "-")}</span><span>Provider: ${escapeHtml(row.provider_source || "-")}</span><span>MIME: ${escapeHtml(row.mime_type || "-")}</span><span>Size: ${escapeHtml(row.media_width || "-")}x${escapeHtml(row.media_height || "-")}</span><span>URL: ${escapeHtml(row.media_url || "-")}</span><span>Storage: ${escapeHtml(row.storage_path || "-")}</span></div></article>`;
        }).join("");
      }

      if (refs.mediaPageInfo) refs.mediaPageInfo.textContent = pageInfo("media", state.totals.media);
      if (refs.mediaPrev) refs.mediaPrev.disabled = state.pages.media <= 0;
      if (refs.mediaNext) refs.mediaNext.disabled = !state.hasMore.media;
      state.loaded.media = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      renderEmpty(refs.mediaList, "Failed to load media.");
      showToast(error.message || "Failed to load media.", true);
    }
  }

  async function loadReferrals(force = false) {
    if (!force && state.loaded.referrals) return;
    try {
      const payload = await requestJson("/api/admin/referrals", {
        params: {
          limit: PAGE_SIZE,
          offset: state.pages.referrals * PAGE_SIZE,
          search: refs.refSearch ? refs.refSearch.value.trim() : "",
        },
      });
      const summary = payload.summary || {};
      const items = Array.isArray(payload.items) ? payload.items : [];
      state.totals.referrals = Number(payload.total || 0);
      state.hasMore.referrals = Boolean(payload.has_more);

      if (refs.refSummary) {
        refs.refSummary.innerHTML = [
          metricCard("Total referrals", formatNumber(summary.total_referrals)),
          metricCard("Unique inviters", formatNumber(summary.unique_inviters)),
          metricCard("Unique invitees", formatNumber(summary.unique_invitees)),
        ].join("");
      }

      if (!items.length) {
        renderEmpty(refs.refList, "No referral records found.");
      } else if (refs.refList) {
        refs.refList.innerHTML = items.map((row) => `<article class="list-item"><div class="row-head"><h4>${escapeHtml(row.referral_code || "-")}</h4><span class="chip muted-chip">${escapeHtml(row.frontend_source || "unknown")}</span></div><p><strong>Inviter:</strong> ${escapeHtml(row.inviter_username ? `@${row.inviter_username}` : row.inviter_first_name || "unknown")} (${escapeHtml(row.inviter_telegram_id || "-")})<br><strong>Invitee:</strong> ${escapeHtml(row.invitee_username ? `@${row.invitee_username}` : row.invitee_first_name || "unknown")} (${escapeHtml(row.invitee_telegram_id || "-")})</p><div class="list-meta"><span>${escapeHtml(formatDateTime(row.created_at))}</span><span>ID: ${escapeHtml(row.id || "-")}</span></div></article>`).join("");
      }

      if (refs.refPageInfo) refs.refPageInfo.textContent = pageInfo("referrals", state.totals.referrals);
      if (refs.refPrev) refs.refPrev.disabled = state.pages.referrals <= 0;
      if (refs.refNext) refs.refNext.disabled = !state.hasMore.referrals;
      state.loaded.referrals = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      renderEmpty(refs.refList, "Failed to load referrals.");
      showToast(error.message || "Failed to load referrals.", true);
    }
  }

  async function loadEngagement(force = false) {
    if (!force && state.loaded.engagement) return;
    try {
      const payload = await requestJson("/api/admin/engagement");
      const config = payload.config || {};
      if (refs.engEnabled) refs.engEnabled.checked = Boolean(config.enabled);
      if (refs.engInactivity) refs.engInactivity.value = String(config.inactivity_minutes || 240);
      if (refs.engCooldown) refs.engCooldown.value = String(config.cooldown_minutes || 720);
      if (refs.engBatch) refs.engBatch.value = String(config.batch_size || 30);
      if (refs.engMessage) refs.engMessage.value = String(config.message_template || "");
      if (refs.engUpdated) refs.engUpdated.textContent = payload.updated_at ? `Last updated: ${formatDateTime(payload.updated_at)}` : "Using defaults";
      state.loaded.engagement = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      showToast(error.message || "Failed to load engagement settings.", true);
    }
  }

  async function saveEngagement() {
    const body = {
      enabled: Boolean(refs.engEnabled && refs.engEnabled.checked),
      inactivity_minutes: Number(refs.engInactivity ? refs.engInactivity.value : 240),
      cooldown_minutes: Number(refs.engCooldown ? refs.engCooldown.value : 720),
      batch_size: Number(refs.engBatch ? refs.engBatch.value : 30),
      message_template: refs.engMessage ? refs.engMessage.value.trim() : "",
    };
    try {
      const payload = await requestJson("/api/admin/engagement", { method: "POST", body });
      if (refs.engUpdated) refs.engUpdated.textContent = payload.updated_at ? `Last updated: ${formatDateTime(payload.updated_at)}` : "Saved";
      state.loaded.engagement = true;
      showToast("Engagement settings saved.");
    } catch (error) {
      if (handleAuthError(error)) return;
      showToast(error.message || "Failed to save engagement settings.", true);
    }
  }

  async function loadBotStatus(force = false) {
    if (!force && state.loaded.botStatus) return;
    try {
      const payload = await requestJson("/api/admin/bot-status");
      if (refs.botStatusGrid) {
        refs.botStatusGrid.innerHTML = [
          metricCard("Runtime ready", payload.runtime_ready ? "yes" : "no"),
          metricCard("Telegram ready", payload.telegram_ready ? "yes" : "no"),
          metricCard("Webhook configured", payload.webhook_configured ? "yes" : "no"),
          metricCard("Menu button configured", payload.menu_button_configured ? "yes" : "no"),
          metricCard("Startup task running", payload.startup_task_running ? "yes" : "no"),
          metricCard("Keepalive task", payload.keepalive_task_running ? "running" : "stopped"),
          metricCard("Heartbeat task", payload.heartbeat_task_running ? "running" : "stopped"),
          metricCard("Engagement task", payload.engagement_task_running ? "running" : "stopped"),
          metricCard("Uptime seconds", String(payload.uptime_seconds || 0)),
        ].join("");
      }
      const warnings = [];
      if (payload.last_startup_error) warnings.push(`Last startup error: ${payload.last_startup_error}`);
      if (Array.isArray(payload.startup_warnings)) {
        for (const warning of payload.startup_warnings) if (warning) warnings.push(String(warning));
      }
      if (!warnings.length) {
        renderEmpty(refs.botWarnings, "No runtime warnings.");
      } else if (refs.botWarnings) {
        refs.botWarnings.innerHTML = warnings.map((warning) => `<article class="list-item"><p>${escapeHtml(warning)}</p></article>`).join("");
      }
      state.loaded.botStatus = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      renderEmpty(refs.botWarnings, "Failed to load bot status.");
      showToast(error.message || "Failed to load bot status.", true);
    }
  }

  async function loadSettings(force = false) {
    if (!force && state.loaded.settings) return;
    try {
      const payload = await requestJson("/api/admin/status", { auth: false });
      const parts = [
        `Telegram admin login: ${payload.telegram_auth_enabled ? "enabled" : "disabled"}`,
        `Token sign-in: ${payload.token_auth_enabled ? "enabled" : "disabled"}`,
        `Owner Telegram ID configured: ${payload.owner_telegram_id_configured ? "yes" : "no"}`,
        `Allowlist count: ${formatNumber(payload.allowlist_count)}`,
        `Admin data service: ${payload.service_enabled ? "enabled" : "disabled"}`,
      ];
      if (payload.owner_telegram_id) parts.push(`Owner ID: ${payload.owner_telegram_id}`);
      if (!payload.service_enabled && payload.service_reason) parts.push(`Reason: ${payload.service_reason}`);
      if (refs.statusInfo) refs.statusInfo.textContent = parts.join(" | ");
      state.loaded.settings = true;
    } catch (_error) {
      if (refs.statusInfo) refs.statusInfo.textContent = "Failed to load settings status.";
    }
  }

  async function loadLogs(force = false) {
    if (!force && state.loaded.logs) return;
    try {
      const payload = await requestJson("/api/admin/logs", {
        params: {
          level: refs.logsLevel ? refs.logsLevel.value : "",
          search: refs.logsSearch ? refs.logsSearch.value.trim() : "",
          limit: refs.logsLimit ? refs.logsLimit.value : "200",
        },
      });
      const items = Array.isArray(payload.items) ? payload.items : [];
      if (refs.logsOutput) refs.logsOutput.textContent = items.length ? items.join("\n") : "No logs for current filters.";
      state.loaded.logs = true;
    } catch (error) {
      if (handleAuthError(error)) return;
      if (refs.logsOutput) refs.logsOutput.textContent = `Failed to load logs. ${error.message || ""}`;
      showToast(error.message || "Failed to load logs.", true);
    }
  }

  async function loadSection(name, force = false) {
    if (name === "overview") return loadOverview(force);
    if (name === "users") return loadUsers(force);
    if (name === "safety") return loadSafety(force);
    if (name === "conversations") return loadConversations(force);
    if (name === "media") return loadMedia(force);
    if (name === "referrals") return loadReferrals(force);
    if (name === "engagement") return loadEngagement(force);
    if (name === "bot-status") return loadBotStatus(force);
    if (name === "settings") return loadSettings(force);
    if (name === "logs") return loadLogs(force);
    return Promise.resolve();
  }
  function bind() {
    for (const button of refs.navButtons) {
      button.addEventListener("click", async () => {
        const name = button.dataset.section || "overview";
        setSection(name);
        document.body.classList.remove("sidebar-open");
        await loadSection(name);
      });
    }

    if (refs.menuToggle) refs.menuToggle.addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
    if (refs.telegramLoginBtn) refs.telegramLoginBtn.addEventListener("click", () => loginWithTelegramContext());
    if (refs.tokenSigninBtn) refs.tokenSigninBtn.addEventListener("click", () => loginWithToken());
    if (refs.tokenSigninInput) {
      refs.tokenSigninInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          loginWithToken();
        }
      });
    }

    if (refs.logoutBtn) refs.logoutBtn.addEventListener("click", () => logout());
    if (refs.settingsLogout) refs.settingsLogout.addEventListener("click", () => logout());
    if (refs.refreshBtn) {
      refs.refreshBtn.addEventListener("click", async () => {
        const loadedKey = state.section === "bot-status" ? "botStatus" : state.section;
        state.loaded[loadedKey] = false;
        await loadSection(state.section, true);
      });
    }

    if (refs.usersApply) refs.usersApply.addEventListener("click", async () => { resetPage("users"); state.loaded.users = false; await loadUsers(true); });
    if (refs.safetyApply) refs.safetyApply.addEventListener("click", async () => { resetPage("safety"); state.loaded.safety = false; await loadSafety(true); });
    if (refs.convApply) refs.convApply.addEventListener("click", async () => { resetPage("conversations"); state.loaded.conversations = false; await loadConversations(true); });
    if (refs.mediaApply) refs.mediaApply.addEventListener("click", async () => { resetPage("media"); state.loaded.media = false; await loadMedia(true); });
    if (refs.refApply) refs.refApply.addEventListener("click", async () => { resetPage("referrals"); state.loaded.referrals = false; await loadReferrals(true); });
    if (refs.engSave) refs.engSave.addEventListener("click", () => saveEngagement());
    if (refs.botStatusRefresh) refs.botStatusRefresh.addEventListener("click", async () => { state.loaded.botStatus = false; await loadBotStatus(true); });
    if (refs.logsApply) refs.logsApply.addEventListener("click", async () => { state.loaded.logs = false; await loadLogs(true); });

    if (refs.usersPrev) refs.usersPrev.addEventListener("click", async () => { if (state.pages.users > 0) { state.pages.users -= 1; state.loaded.users = false; await loadUsers(true); } });
    if (refs.usersNext) refs.usersNext.addEventListener("click", async () => { if (state.hasMore.users) { state.pages.users += 1; state.loaded.users = false; await loadUsers(true); } });
    if (refs.safetyPrev) refs.safetyPrev.addEventListener("click", async () => { if (state.pages.safety > 0) { state.pages.safety -= 1; state.loaded.safety = false; await loadSafety(true); } });
    if (refs.safetyNext) refs.safetyNext.addEventListener("click", async () => { if (state.hasMore.safety) { state.pages.safety += 1; state.loaded.safety = false; await loadSafety(true); } });

    if (refs.convPrev) refs.convPrev.addEventListener("click", async () => { if (state.pages.conversations > 0) { state.pages.conversations -= 1; state.loaded.conversations = false; await loadConversations(true); } });
    if (refs.convNext) refs.convNext.addEventListener("click", async () => { if (state.hasMore.conversations) { state.pages.conversations += 1; state.loaded.conversations = false; await loadConversations(true); } });

    if (refs.mediaPrev) refs.mediaPrev.addEventListener("click", async () => { if (state.pages.media > 0) { state.pages.media -= 1; state.loaded.media = false; await loadMedia(true); } });
    if (refs.mediaNext) refs.mediaNext.addEventListener("click", async () => { if (state.hasMore.media) { state.pages.media += 1; state.loaded.media = false; await loadMedia(true); } });

    if (refs.refPrev) refs.refPrev.addEventListener("click", async () => { if (state.pages.referrals > 0) { state.pages.referrals -= 1; state.loaded.referrals = false; await loadReferrals(true); } });
    if (refs.refNext) refs.refNext.addEventListener("click", async () => { if (state.hasMore.referrals) { state.pages.referrals += 1; state.loaded.referrals = false; await loadReferrals(true); } });

    if (refs.userWarnBtn) refs.userWarnBtn.addEventListener("click", async () => sendWarningToUser());
    if (refs.userBlockBtn) refs.userBlockBtn.addEventListener("click", async () => runUserAccessAction("block"));
    if (refs.userUnblockBtn) refs.userUnblockBtn.addEventListener("click", async () => runUserAccessAction("unblock"));
    if (refs.userKickBtn) refs.userKickBtn.addEventListener("click", async () => runUserAccessAction("kick"));
    if (refs.userSendMessageBtn) refs.userSendMessageBtn.addEventListener("click", async () => sendDirectMessageToSelectedUser());

    document.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      const openButton = target.closest(".user-open-btn");
      if (openButton instanceof HTMLElement) {
        const userId = Number(openButton.getAttribute("data-user-id") || "0");
        if (userId > 0) {
          loadUserProfile(userId, true);
        }
        return;
      }

      const actionButton = target.closest(".user-action-btn");
      if (actionButton instanceof HTMLElement) {
        const action = String(actionButton.getAttribute("data-action") || "").trim().toLowerCase();
        const userId = Number(actionButton.getAttribute("data-user-id") || "0");
        if (userId > 0 && action) {
          if (action === "warn") {
            sendWarningToUser(userId);
          } else if (action === "message") {
            sendCustomMessagePrompt(userId);
          } else {
            runUserAccessAction(action, userId);
          }
        }
        return;
      }

      const userCard = target.closest(".list-item[data-user-id]");
      if (userCard instanceof HTMLElement && userCard.parentElement === refs.usersList) {
        const userId = Number(userCard.getAttribute("data-user-id") || "0");
        if (userId > 0) {
          loadUserProfile(userId, true);
        }
        return;
      }

      const button = target.closest(".copy-btn");
      if (!button) return;
      copyText(button.getAttribute("data-copy") || "");
    });
  }

  async function init() {
    setSection("overview");
    bind();
    renderUserProfileEmpty();
    await loadStatusConfig(true);
    await loadSettings(true);

    if (state.token) {
      try {
        await verifySession();
        hideLogin();
        await loadSection("overview", true);
        return;
      } catch (_error) {
        state.token = "";
        sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      }
    }

    try {
      await verifySession();
      hideLogin();
      await loadSection("overview", true);
      showToast("Admin session restored.");
      return;
    } catch (_error) {
      showLogin();
    }
  }

  window.onTelegramAuth = (user) => {
    loginWithTelegramWidget(user);
  };

  window.addEventListener("DOMContentLoaded", init);
})();
