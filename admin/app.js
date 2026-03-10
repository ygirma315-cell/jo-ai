(() => {
  "use strict";

  const state = {
    token: sessionStorage.getItem("jo_admin_token") || "",
    activeSection: "overview",
    globalDays: 14,
    pageSize: 25,
    statusLoaded: false,
    loaded: {
      overview: false,
      messages: false,
      users: false,
      media: false,
      analytics: false,
    },
    pages: {
      messages: { offset: 0, total: 0, hasMore: false },
      users: { offset: 0, total: 0, hasMore: false },
      media: { offset: 0, total: 0, hasMore: false },
    },
  };

  const SECTION_TITLES = {
    overview: "Dashboard overview",
    messages: "Messages monitor",
    users: "Users monitor",
    media: "Media and images",
    analytics: "Usage analytics",
    settings: "Admin settings",
  };

  const elements = {
    loginOverlay: document.getElementById("loginOverlay"),
    loginForm: document.getElementById("loginForm"),
    loginToken: document.getElementById("loginToken"),
    loginError: document.getElementById("loginError"),
    navLinks: Array.from(document.querySelectorAll(".nav-link")),
    pageHeading: document.getElementById("pageHeading"),
    authStateChip: document.getElementById("authStateChip"),
    menuToggle: document.getElementById("menuToggle"),
    refreshBtn: document.getElementById("refreshBtn"),
    globalDays: document.getElementById("globalDays"),
    logoutBtn: document.getElementById("logoutBtn"),
    settingsLogout: document.getElementById("settingsLogout"),
    settingsStatus: document.getElementById("settingsStatus"),
    settingsTokenInput: document.getElementById("settingsTokenInput"),
    settingsTokenSave: document.getElementById("settingsTokenSave"),
    settingsTokenTest: document.getElementById("settingsTokenTest"),
    toast: document.getElementById("toast"),
    summaryTotalUsers: document.getElementById("summaryTotalUsers"),
    summaryActiveToday: document.getElementById("summaryActiveToday"),
    summaryTotalMessages: document.getElementById("summaryTotalMessages"),
    summaryTotalImages: document.getElementById("summaryTotalImages"),
    summaryTotalAudio: document.getElementById("summaryTotalAudio"),
    overviewMessagesChart: document.getElementById("overviewMessagesChart"),
    overviewActiveChart: document.getElementById("overviewActiveChart"),
    overviewRecentBody: document.getElementById("overviewRecentBody"),
    messagesSearch: document.getElementById("messagesSearch"),
    messagesScope: document.getElementById("messagesScope"),
    messagesType: document.getElementById("messagesType"),
    messagesApply: document.getElementById("messagesApply"),
    messagesBody: document.getElementById("messagesBody"),
    messagesPrev: document.getElementById("messagesPrev"),
    messagesNext: document.getElementById("messagesNext"),
    messagesPageInfo: document.getElementById("messagesPageInfo"),
    usersSearch: document.getElementById("usersSearch"),
    usersActiveWindow: document.getElementById("usersActiveWindow"),
    usersApply: document.getElementById("usersApply"),
    usersBody: document.getElementById("usersBody"),
    usersPrev: document.getElementById("usersPrev"),
    usersNext: document.getElementById("usersNext"),
    usersPageInfo: document.getElementById("usersPageInfo"),
    mediaSearch: document.getElementById("mediaSearch"),
    mediaApply: document.getElementById("mediaApply"),
    mediaBody: document.getElementById("mediaBody"),
    mediaPrev: document.getElementById("mediaPrev"),
    mediaNext: document.getElementById("mediaNext"),
    mediaPageInfo: document.getElementById("mediaPageInfo"),
    mediaTotalImages: document.getElementById("mediaTotalImages"),
    mediaSuccessfulImages: document.getElementById("mediaSuccessfulImages"),
    mediaLast7Days: document.getElementById("mediaLast7Days"),
    analyticsDays: document.getElementById("analyticsDays"),
    analyticsApply: document.getElementById("analyticsApply"),
    analyticsMessagesChart: document.getElementById("analyticsMessagesChart"),
    analyticsUsersChart: document.getElementById("analyticsUsersChart"),
    analyticsImagesChart: document.getElementById("analyticsImagesChart"),
    analyticsTopUsersBody: document.getElementById("analyticsTopUsersBody"),
    analyticsTypeBreakdown: document.getElementById("analyticsTypeBreakdown"),
    analyticsTopModels: document.getElementById("analyticsTopModels"),
  };

  function htmlEscape(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatNumber(value) {
    const parsed = Number(value || 0);
    return Number.isFinite(parsed) ? parsed.toLocaleString() : "0";
  }

  function formatDateTime(value) {
    if (!value) {
      return "-";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return String(value);
    }
    return parsed.toLocaleString();
  }

  function userLabel(item) {
    const username = String(item.username || "").trim();
    const firstName = String(item.first_name || "").trim();
    const lastName = String(item.last_name || "").trim();
    const fullName = [firstName, lastName].filter(Boolean).join(" ").trim();
    const identity = username ? `@${username}` : fullName || "unknown";
    return `${identity} (${item.telegram_id || "?"})`;
  }

  function setAuthStateChip(locked) {
    if (!elements.authStateChip) {
      return;
    }
    elements.authStateChip.textContent = locked ? "Locked" : "Authorized";
    elements.authStateChip.style.borderColor = locked ? "rgba(255, 144, 144, 0.5)" : "rgba(94, 226, 166, 0.52)";
  }

  function showToast(message, type = "") {
    if (!elements.toast) {
      return;
    }
    elements.toast.hidden = false;
    elements.toast.className = `toast${type ? ` ${type}` : ""}`;
    elements.toast.textContent = String(message || "Done.");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      elements.toast.hidden = true;
    }, 2800);
  }

  function showLogin(message = "") {
    if (elements.loginOverlay) {
      elements.loginOverlay.hidden = false;
    }
    if (elements.loginError) {
      if (message) {
        elements.loginError.hidden = false;
        elements.loginError.textContent = message;
      } else {
        elements.loginError.hidden = true;
        elements.loginError.textContent = "";
      }
    }
    setAuthStateChip(true);
  }

  function hideLogin() {
    if (elements.loginOverlay) {
      elements.loginOverlay.hidden = true;
    }
    if (elements.loginError) {
      elements.loginError.hidden = true;
      elements.loginError.textContent = "";
    }
    setAuthStateChip(false);
  }

  async function fetchJson(path, { auth = true, params = null, tokenOverride = "" } = {}) {
    const target = new URL(path, window.location.origin);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null || value === "") {
          continue;
        }
        target.searchParams.set(key, String(value));
      }
    }

    const headers = { Accept: "application/json" };
    const token = tokenOverride || state.token;
    if (auth && token) {
      headers["x-admin-token"] = token;
    }

    const response = await fetch(target.toString(), { method: "GET", headers });
    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        payload = { error: text.slice(0, 200) };
      }
    }
    if (!response.ok) {
      const message =
        (payload && (payload.error || payload.detail || payload.message)) ||
        `Request failed with status ${response.status}.`;
      const error = new Error(String(message));
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  function renderEmptyTableBody(body, message, columnCount) {
    if (!body) {
      return;
    }
    body.innerHTML = `<tr><td colspan="${columnCount}">${htmlEscape(message)}</td></tr>`;
  }

  function renderBarChart(container, labels, values, options = {}) {
    if (!container) {
      return;
    }
    const safeLabels = Array.isArray(labels) ? labels : [];
    const safeValues = Array.isArray(values) ? values : [];
    if (!safeLabels.length || !safeValues.length) {
      container.innerHTML = `<p class="hint-text">No data yet.</p>`;
      return;
    }

    const maxPoints = options.maxPoints || 20;
    const step = Math.max(1, Math.ceil(safeLabels.length / maxPoints));
    const sampledLabels = [];
    const sampledValues = [];
    for (let index = 0; index < safeLabels.length; index += step) {
      sampledLabels.push(safeLabels[index]);
      sampledValues.push(Number(safeValues[index] || 0));
    }
    if (sampledLabels[sampledLabels.length - 1] !== safeLabels[safeLabels.length - 1]) {
      sampledLabels.push(safeLabels[safeLabels.length - 1]);
      sampledValues.push(Number(safeValues[safeValues.length - 1] || 0));
    }

    const maxValue = Math.max(1, ...sampledValues);
    container.innerHTML = sampledLabels
      .map((label, idx) => {
        const value = Math.max(0, Number(sampledValues[idx] || 0));
        const height = value <= 0 ? 4 : Math.max(8, Math.round((value / maxValue) * 118));
        return `
          <div class="bar-stack">
            <span class="bar-value">${htmlEscape(value)}</span>
            <span class="bar${options.secondary ? " secondary" : ""}" style="height:${height}px"></span>
            <span class="bar-label">${htmlEscape(label)}</span>
          </div>
        `;
      })
      .join("");
  }

  function sectionElement(sectionName) {
    return document.getElementById(`section-${sectionName}`);
  }

  function setActiveSection(sectionName) {
    state.activeSection = sectionName;
    for (const link of elements.navLinks) {
      link.classList.toggle("active", link.dataset.section === sectionName);
    }
    for (const name of Object.keys(SECTION_TITLES)) {
      const panel = sectionElement(name);
      if (panel) {
        panel.classList.toggle("active", name === sectionName);
      }
    }
    if (elements.pageHeading) {
      elements.pageHeading.textContent = SECTION_TITLES[sectionName] || "Admin";
    }
  }

  function closeSidebarOnMobile() {
    if (window.innerWidth <= 900) {
      document.body.classList.remove("sidebar-open");
    }
  }

  function handleAuthError(error) {
    if (error && Number(error.status) === 401) {
      showLogin("Session expired or token invalid. Please login again.");
      showToast("Unauthorized admin token.", "error");
      return true;
    }
    return false;
  }

  async function loadOverview(force = false) {
    if (!force && state.loaded.overview) {
      return;
    }
    try {
      const data = await fetchJson("/api/admin/overview", {
        params: { days: state.globalDays },
      });
      const summary = data.summary || {};
      elements.summaryTotalUsers.textContent = formatNumber(summary.total_users);
      elements.summaryActiveToday.textContent = formatNumber(summary.active_users_today);
      elements.summaryTotalMessages.textContent = formatNumber(summary.total_messages);
      elements.summaryTotalImages.textContent = formatNumber(summary.total_images);
      elements.summaryTotalAudio.textContent = formatNumber(summary.total_audio);

      const trends = data.trends || {};
      renderBarChart(elements.overviewMessagesChart, trends.labels || [], trends.messages || []);
      renderBarChart(elements.overviewActiveChart, trends.labels || [], trends.active_users || [], { secondary: true });

      const rows = Array.isArray(data.recent_activity) ? data.recent_activity : [];
      if (!rows.length) {
        renderEmptyTableBody(elements.overviewRecentBody, "No recent activity yet.", 5);
      } else {
        elements.overviewRecentBody.innerHTML = rows
          .map((item) => {
            const statusClass = item.success ? "success" : "fail";
            return `
              <tr>
                <td>${htmlEscape(formatDateTime(item.created_at))}</td>
                <td>${htmlEscape(userLabel(item))}</td>
                <td>${htmlEscape(item.message_type || "-")}</td>
                <td><span class="status-pill ${statusClass}">${item.success ? "success" : "failed"}</span></td>
                <td>${htmlEscape(item.preview || "-")}</td>
              </tr>
            `;
          })
          .join("");
      }
      state.loaded.overview = true;
    } catch (error) {
      if (handleAuthError(error)) {
        return;
      }
      renderEmptyTableBody(elements.overviewRecentBody, "Failed to load overview data.", 5);
      showToast(error.message || "Failed to load overview.", "error");
    }
  }

  async function loadMessages(force = false) {
    if (!force && state.loaded.messages) {
      return;
    }
    const page = state.pages.messages;
    try {
      const payload = await fetchJson("/api/admin/messages", {
        params: {
          limit: state.pageSize,
          offset: page.offset,
          search: elements.messagesSearch.value.trim(),
          message_type: elements.messagesType.value,
          scope: elements.messagesScope.value,
        },
      });
      const rows = Array.isArray(payload.items) ? payload.items : [];
      page.total = Number(payload.total || 0);
      page.hasMore = Boolean(payload.has_more);
      if (!rows.length) {
        renderEmptyTableBody(elements.messagesBody, "No messages found for the current filters.", 6);
      } else {
        elements.messagesBody.innerHTML = rows
          .map((item) => {
            const statusClass = item.success ? "success" : "fail";
            return `
              <tr>
                <td>${htmlEscape(formatDateTime(item.created_at))}</td>
                <td>${htmlEscape(userLabel(item))}</td>
                <td>${htmlEscape(item.message_type || "-")}</td>
                <td><span class="scope-pill">${htmlEscape(item.scope || "private")}</span></td>
                <td><span class="status-pill ${statusClass}">${item.success ? "success" : "failed"}</span></td>
                <td>${htmlEscape(item.user_message || item.bot_reply || "-")}</td>
              </tr>
            `;
          })
          .join("");
      }
      const pageNumber = Math.floor(page.offset / state.pageSize) + 1;
      const totalPages = Math.max(1, Math.ceil(page.total / state.pageSize));
      elements.messagesPageInfo.textContent = `Page ${pageNumber} / ${totalPages} (${formatNumber(page.total)} rows)`;
      elements.messagesPrev.disabled = page.offset <= 0;
      elements.messagesNext.disabled = !page.hasMore;
      state.loaded.messages = true;
    } catch (error) {
      if (handleAuthError(error)) {
        return;
      }
      renderEmptyTableBody(elements.messagesBody, "Failed to load messages.", 6);
      showToast(error.message || "Failed to load messages.", "error");
    }
  }

  async function loadUsers(force = false) {
    if (!force && state.loaded.users) {
      return;
    }
    const page = state.pages.users;
    try {
      const payload = await fetchJson("/api/admin/users", {
        params: {
          limit: state.pageSize,
          offset: page.offset,
          search: elements.usersSearch.value.trim(),
          active_days: Number(elements.usersActiveWindow.value || 7),
        },
      });
      const rows = Array.isArray(payload.items) ? payload.items : [];
      page.total = Number(payload.total || 0);
      page.hasMore = Boolean(payload.has_more);

      if (!rows.length) {
        renderEmptyTableBody(elements.usersBody, "No users found for the current filters.", 7);
      } else {
        elements.usersBody.innerHTML = rows
          .map((item) => {
            const activeClass = item.is_active ? "active" : "inactive";
            return `
              <tr>
                <td>${htmlEscape(userLabel(item))}</td>
                <td><span class="scope-pill">${htmlEscape(item.scope || "private")}</span></td>
                <td>${htmlEscape(formatDateTime(item.first_seen_at))}</td>
                <td>${htmlEscape(formatDateTime(item.last_seen_at))}</td>
                <td>${htmlEscape(formatNumber(item.total_messages))}</td>
                <td>${htmlEscape(formatNumber(item.total_images))}</td>
                <td><span class="status-pill ${activeClass}">${item.is_active ? "active" : "inactive"}</span></td>
              </tr>
            `;
          })
          .join("");
      }
      const pageNumber = Math.floor(page.offset / state.pageSize) + 1;
      const totalPages = Math.max(1, Math.ceil(page.total / state.pageSize));
      elements.usersPageInfo.textContent = `Page ${pageNumber} / ${totalPages} (${formatNumber(page.total)} rows)`;
      elements.usersPrev.disabled = page.offset <= 0;
      elements.usersNext.disabled = !page.hasMore;
      state.loaded.users = true;
    } catch (error) {
      if (handleAuthError(error)) {
        return;
      }
      renderEmptyTableBody(elements.usersBody, "Failed to load users.", 7);
      showToast(error.message || "Failed to load users.", "error");
    }
  }

  async function loadMedia(force = false) {
    if (!force && state.loaded.media) {
      return;
    }
    const page = state.pages.media;
    try {
      const payload = await fetchJson("/api/admin/media", {
        params: {
          limit: state.pageSize,
          offset: page.offset,
          search: elements.mediaSearch.value.trim(),
        },
      });
      const summary = payload.summary || {};
      elements.mediaTotalImages.textContent = formatNumber(summary.total_images);
      elements.mediaSuccessfulImages.textContent = formatNumber(summary.successful_images);
      elements.mediaLast7Days.textContent = formatNumber(summary.images_last_7_days);

      const rows = Array.isArray(payload.items) ? payload.items : [];
      page.total = Number(payload.total || 0);
      page.hasMore = Boolean(payload.has_more);
      if (!rows.length) {
        renderEmptyTableBody(elements.mediaBody, "No image history found for the current filters.", 5);
      } else {
        elements.mediaBody.innerHTML = rows
          .map((item) => {
            const statusClass = item.success ? "success" : "fail";
            return `
              <tr>
                <td>${htmlEscape(formatDateTime(item.created_at))}</td>
                <td>${htmlEscape(userLabel(item))}</td>
                <td><span class="status-pill ${statusClass}">${item.success ? "success" : "failed"}</span></td>
                <td>${htmlEscape(item.prompt || item.result_note || "-")}</td>
                <td>${htmlEscape(item.model_used || "-")}</td>
              </tr>
            `;
          })
          .join("");
      }
      const pageNumber = Math.floor(page.offset / state.pageSize) + 1;
      const totalPages = Math.max(1, Math.ceil(page.total / state.pageSize));
      elements.mediaPageInfo.textContent = `Page ${pageNumber} / ${totalPages} (${formatNumber(page.total)} rows)`;
      elements.mediaPrev.disabled = page.offset <= 0;
      elements.mediaNext.disabled = !page.hasMore;
      state.loaded.media = true;
    } catch (error) {
      if (handleAuthError(error)) {
        return;
      }
      renderEmptyTableBody(elements.mediaBody, "Failed to load media history.", 5);
      showToast(error.message || "Failed to load media history.", "error");
    }
  }

  async function loadAnalytics(force = false) {
    if (!force && state.loaded.analytics) {
      return;
    }
    try {
      const payload = await fetchJson("/api/admin/analytics", {
        params: {
          days: Number(elements.analyticsDays.value || 30),
          top_limit: 12,
        },
      });
      const trends = payload.trends || {};
      renderBarChart(elements.analyticsMessagesChart, trends.labels || [], trends.messages || []);
      renderBarChart(elements.analyticsUsersChart, trends.labels || [], trends.active_users || [], { secondary: true });
      renderBarChart(elements.analyticsImagesChart, trends.labels || [], trends.images || []);

      const topUsers = Array.isArray(payload.top_users) ? payload.top_users : [];
      if (!topUsers.length) {
        renderEmptyTableBody(elements.analyticsTopUsersBody, "No analytics data yet.", 4);
      } else {
        elements.analyticsTopUsersBody.innerHTML = topUsers
          .map(
            (item) => `
              <tr>
                <td>${htmlEscape(userLabel(item))}</td>
                <td>${htmlEscape(formatNumber(item.events))}</td>
                <td>${htmlEscape(formatNumber(item.total_messages))}</td>
                <td>${htmlEscape(formatNumber(item.total_images))}</td>
              </tr>
            `
          )
          .join("");
      }

      const breakdown = payload.message_type_breakdown || {};
      const typeItems = Object.entries(breakdown);
      elements.analyticsTypeBreakdown.innerHTML = typeItems.length
        ? typeItems
            .map(([type, count]) => `<li><strong>${htmlEscape(type)}</strong>: ${htmlEscape(formatNumber(count))}</li>`)
            .join("")
        : "<li>No message breakdown data.</li>";

      const models = Array.isArray(payload.top_models) ? payload.top_models : [];
      elements.analyticsTopModels.innerHTML = models.length
        ? models
            .map(
              (item) =>
                `<li><strong>${htmlEscape(item.model || "unknown")}</strong>: ${htmlEscape(formatNumber(item.count || 0))}</li>`
            )
            .join("")
        : "<li>No model data yet.</li>";

      state.loaded.analytics = true;
    } catch (error) {
      if (handleAuthError(error)) {
        return;
      }
      renderEmptyTableBody(elements.analyticsTopUsersBody, "Failed to load analytics.", 4);
      showToast(error.message || "Failed to load analytics.", "error");
    }
  }

  async function loadSection(sectionName, force = false) {
    if (sectionName === "overview") {
      await loadOverview(force);
      return;
    }
    if (sectionName === "messages") {
      await loadMessages(force);
      return;
    }
    if (sectionName === "users") {
      await loadUsers(force);
      return;
    }
    if (sectionName === "media") {
      await loadMedia(force);
      return;
    }
    if (sectionName === "analytics") {
      await loadAnalytics(force);
      return;
    }
  }

  async function loadStatus() {
    try {
      const payload = await fetchJson("/api/admin/status", { auth: false });
      const pieces = [
        `Token configured: ${payload.token_configured ? "yes" : "no"}`,
        `Data service: ${payload.service_enabled ? "enabled" : "disabled"}`,
      ];
      if (!payload.service_enabled && payload.service_reason) {
        pieces.push(`Reason: ${payload.service_reason}`);
      }
      if (elements.settingsStatus) {
        elements.settingsStatus.textContent = pieces.join(" | ");
      }
      state.statusLoaded = true;
    } catch (error) {
      if (elements.settingsStatus) {
        elements.settingsStatus.textContent = "Failed to load admin status.";
      }
    }
  }

  async function verifyToken(tokenValue) {
    await fetchJson("/api/admin/auth", { tokenOverride: tokenValue });
  }

  async function login(tokenValue) {
    const nextToken = String(tokenValue || "").trim();
    if (!nextToken) {
      showLogin("Admin token is required.");
      return;
    }
    try {
      await verifyToken(nextToken);
      state.token = nextToken;
      sessionStorage.setItem("jo_admin_token", nextToken);
      if (elements.settingsTokenInput) {
        elements.settingsTokenInput.value = nextToken;
      }
      hideLogin();
      await Promise.all([loadOverview(true), loadMessages(true), loadUsers(true), loadMedia(true), loadAnalytics(true)]);
      showToast("Admin session authorized.", "success");
    } catch (error) {
      showLogin(error.message || "Unauthorized admin token.");
      showToast(error.message || "Failed to authorize token.", "error");
    }
  }

  function logout() {
    state.token = "";
    sessionStorage.removeItem("jo_admin_token");
    state.loaded = {
      overview: false,
      messages: false,
      users: false,
      media: false,
      analytics: false,
    };
    showLogin("Logged out.");
  }

  function bindEvents() {
    for (const link of elements.navLinks) {
      link.addEventListener("click", async () => {
        const sectionName = link.dataset.section || "overview";
        setActiveSection(sectionName);
        closeSidebarOnMobile();
        await loadSection(sectionName, false);
      });
    }

    if (elements.menuToggle) {
      elements.menuToggle.addEventListener("click", () => {
        document.body.classList.toggle("sidebar-open");
      });
    }

    if (elements.globalDays) {
      elements.globalDays.addEventListener("change", async () => {
        state.globalDays = Number(elements.globalDays.value || 14);
        state.loaded.overview = false;
        await loadOverview(true);
      });
    }

    if (elements.refreshBtn) {
      elements.refreshBtn.addEventListener("click", async () => {
        await loadSection(state.activeSection, true);
      });
    }

    if (elements.logoutBtn) {
      elements.logoutBtn.addEventListener("click", logout);
    }
    if (elements.settingsLogout) {
      elements.settingsLogout.addEventListener("click", logout);
    }

    if (elements.loginForm) {
      elements.loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        await login(elements.loginToken.value);
      });
    }

    if (elements.messagesApply) {
      elements.messagesApply.addEventListener("click", async () => {
        state.pages.messages.offset = 0;
        state.loaded.messages = false;
        await loadMessages(true);
      });
    }
    if (elements.messagesPrev) {
      elements.messagesPrev.addEventListener("click", async () => {
        state.pages.messages.offset = Math.max(0, state.pages.messages.offset - state.pageSize);
        state.loaded.messages = false;
        await loadMessages(true);
      });
    }
    if (elements.messagesNext) {
      elements.messagesNext.addEventListener("click", async () => {
        if (!state.pages.messages.hasMore) {
          return;
        }
        state.pages.messages.offset += state.pageSize;
        state.loaded.messages = false;
        await loadMessages(true);
      });
    }

    if (elements.usersApply) {
      elements.usersApply.addEventListener("click", async () => {
        state.pages.users.offset = 0;
        state.loaded.users = false;
        await loadUsers(true);
      });
    }
    if (elements.usersPrev) {
      elements.usersPrev.addEventListener("click", async () => {
        state.pages.users.offset = Math.max(0, state.pages.users.offset - state.pageSize);
        state.loaded.users = false;
        await loadUsers(true);
      });
    }
    if (elements.usersNext) {
      elements.usersNext.addEventListener("click", async () => {
        if (!state.pages.users.hasMore) {
          return;
        }
        state.pages.users.offset += state.pageSize;
        state.loaded.users = false;
        await loadUsers(true);
      });
    }

    if (elements.mediaApply) {
      elements.mediaApply.addEventListener("click", async () => {
        state.pages.media.offset = 0;
        state.loaded.media = false;
        await loadMedia(true);
      });
    }
    if (elements.mediaPrev) {
      elements.mediaPrev.addEventListener("click", async () => {
        state.pages.media.offset = Math.max(0, state.pages.media.offset - state.pageSize);
        state.loaded.media = false;
        await loadMedia(true);
      });
    }
    if (elements.mediaNext) {
      elements.mediaNext.addEventListener("click", async () => {
        if (!state.pages.media.hasMore) {
          return;
        }
        state.pages.media.offset += state.pageSize;
        state.loaded.media = false;
        await loadMedia(true);
      });
    }

    if (elements.analyticsApply) {
      elements.analyticsApply.addEventListener("click", async () => {
        state.loaded.analytics = false;
        await loadAnalytics(true);
      });
    }

    if (elements.settingsTokenSave) {
      elements.settingsTokenSave.addEventListener("click", () => {
        const tokenValue = String(elements.settingsTokenInput.value || "").trim();
        if (!tokenValue) {
          showToast("Token value is empty.", "error");
          return;
        }
        state.token = tokenValue;
        sessionStorage.setItem("jo_admin_token", tokenValue);
        showToast("Token saved for this session.", "success");
      });
    }

    if (elements.settingsTokenTest) {
      elements.settingsTokenTest.addEventListener("click", async () => {
        const tokenValue = String(elements.settingsTokenInput.value || state.token || "").trim();
        if (!tokenValue) {
          showToast("Token value is empty.", "error");
          return;
        }
        try {
          await verifyToken(tokenValue);
          state.token = tokenValue;
          sessionStorage.setItem("jo_admin_token", tokenValue);
          hideLogin();
          showToast("Token validated.", "success");
        } catch (error) {
          showToast(error.message || "Token check failed.", "error");
        }
      });
    }
  }

  async function init() {
    setActiveSection("overview");
    bindEvents();
    await loadStatus();

    if (state.token) {
      if (elements.loginToken) {
        elements.loginToken.value = state.token;
      }
      if (elements.settingsTokenInput) {
        elements.settingsTokenInput.value = state.token;
      }
      await login(state.token);
      return;
    }
    showLogin();
  }

  window.addEventListener("DOMContentLoaded", init);
})();
