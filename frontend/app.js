(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { mode: "demo", role: "donor", identity: "demo-canteen", token: "", toastTimer: null };
  const identities = {
    donor: [
      ["demo-canteen", "Demo College Canteen"],
      ["demo-events", "Demo Event Organizer"],
    ],
    recipient: [
      ["org-harvest", "Demo Harvest Community Kitchen"],
      ["org-neighborhood", "Demo Neighborhood Pantry"],
      ["org-community", "Demo Community Outreach"],
      ["org-review", "Demo Organization Awaiting Review"],
    ],
    admin: [["demo-admin", "Demo Administrator"]],
  };
  const labels = {
    AVAILABLE: "Available",
    REQUESTED: "Requested",
    ACCEPTED: "Accepted",
    READY_FOR_PICKUP: "Ready for pickup",
    COMPLETED: "Completed",
    CANCELLED: "Cancelled",
    WITHDRAWN: "Withdrawn",
    EXPIRED: "Expired",
    ELIGIBLE: "Safety information complete",
    PENDING_REVIEW: "Pending safety review",
    FLAGGED: "Flagged for review",
  };

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.mode === "demo") {
      headers["X-Demo-Role"] = state.role;
      headers["X-Demo-User"] = state.identity;
    } else if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }
    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch (_error) {
      throw new Error("FoodLoop could not reach the server. Check that the application is running.");
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = result.error || result.detail;
      throw new Error(typeof detail === "string" ? detail : "The request could not be completed.");
    }
    return result;
  }

  function showToast(message, isError = false) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.toggle("error", isError);
    toast.classList.add("visible");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 4200);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
  }

  function formatDate(value) {
    if (!value) return "Not available";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Not available" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }

  function number(value) {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value || 0);
  }

  function setRoleControls() {
    $("#role-select").value = state.role;
    const selector = $("#identity-select");
    selector.innerHTML = identities[state.role].map(([id, name]) => `<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`).join("");
    selector.value = state.identity;
    $("#demo-switcher").classList.toggle("hidden", state.mode !== "demo");
    $("#auth-panel").classList.toggle("hidden", state.mode === "demo");
    $("#auth-panel label").textContent = state.token ? `Signed in: ${state.role}` : "Signed out";
    $("#open-login").classList.toggle("hidden", Boolean(state.token));
    $("#sign-out").classList.toggle("hidden", !state.token);
  }

  function navigate(view) {
    const safeView = ["home", "donate", "find", "tracking", "impact", "admin"].includes(view) ? view : "home";
    $$(".view").forEach(section => section.classList.toggle("active", section.id === `view-${safeView}`));
    $$(".nav-link").forEach(link => link.classList.toggle("active", link.dataset.view === safeView));
    $("#main-nav").classList.remove("open");
    $("#menu-toggle").setAttribute("aria-expanded", "false");
    window.location.hash = safeView;
    if (safeView === "home") loadHome();
    if (safeView === "find") loadDonations();
    if (safeView === "tracking") loadClaims();
    if (safeView === "impact") loadImpact();
    if (safeView === "admin") loadAdmin();
  }

  function showLoading(target, text = "Loading…") {
    target.innerHTML = `<div class="loading-state">${escapeHtml(text)}</div>`;
  }

  function showError(target, error) {
    target.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
  }

  function statCard(value, label, caption = "") {
    return `<article class="stat-card"><div class="stat-value">${escapeHtml(value)}</div><div class="stat-label">${escapeHtml(label)}</div><div class="stat-caption">${escapeHtml(caption)}</div></article>`;
  }

  async function loadStatus() {
    try {
      const status = await api("/api/status");
      state.mode = status.mode;
      if (state.mode !== "demo") {
        state.token = sessionStorage.getItem("foodloop-access-token") || "";
        if (state.token) {
          try {
            const identity = await api("/api/auth/me");
            state.role = identity.role;
            state.identity = identity.identity;
          } catch (_error) {
            state.token = "";
            sessionStorage.removeItem("foodloop-access-token");
          }
        }
      }
      const banner = $("#mode-banner");
      banner.textContent = status.mode === "demo"
        ? `DEMO MODE · ${status.demo_notice} Role switching below is a demonstration convenience, not secure authentication.`
        : "SUPABASE MODE · Sign in with your organization account. Actions are authorized by the backend.";
      setRoleControls();
    } catch (error) {
      $("#mode-banner").textContent = error.message;
      $("#mode-banner").classList.add("error-state");
    }
  }

  async function loadHome() {
    const container = $("#home-stats");
    try {
      const data = await api("/api/impact");
      container.innerHTML = [
        statCard(data.completed_donations, "Completed donations", "Confirmed handovers"),
        statCard(number(data.portions_donated), "Portions donated", "Portion units only"),
        statCard(data.active_available_listings, "Available listings", "Currently listed"),
        statCard(`${number(data.estimated_food_waste_avoided_kg)} kg`, "Estimated food recovered", "Assumption-based estimate"),
      ].join("");
    } catch (error) {
      container.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
    }
  }

  function currentFilters() {
    const data = new FormData($("#filter-form"));
    const params = new URLSearchParams();
    for (const key of ["search", "category", "location", "minimum_quantity", "status"]) {
      const value = String(data.get(key) || "").trim();
      if (value) params.set(key, value);
    }
    const beforeDeadline = data.get("before_deadline");
    if (beforeDeadline) params.set("before_deadline", new Date(beforeDeadline).toISOString());
    return params.toString();
  }

  async function loadDonations() {
    const container = $("#donation-list");
    showLoading(container, "Loading available donations…");
    try {
      const query = currentFilters();
      const donations = await api(`/api/donations${query ? `?${query}` : ""}`);
      if (!donations.length) {
        container.innerHTML = '<div class="empty-state">No donations match these filters. Try another search or check back soon.</div>';
        return;
      }
      container.innerHTML = donations.map(donationCard).join("");
    } catch (error) {
      showError(container, error);
    }
  }

  function donationCard(item) {
    const safetyGood = item.safety_status === "ELIGIBLE";
    const statusTone = item.status === "AVAILABLE" ? "" : "neutral";
    const warnings = (item.safety_warnings || []).map(escapeHtml).join(" ");
    const canClaim = state.role === "recipient" && item.status === "AVAILABLE" && safetyGood;
    const allergenText = item.allergen_info_known
      ? (item.allergens?.length ? `Known allergens: ${item.allergens.map(escapeHtml).join(", ")}` : "No allergens listed; confirm details with donor")
      : "Allergen information unknown";
    const quantity = `<label class="small">Request quantity<input class="quantity-input" data-quantity="${escapeHtml(item.id)}" type="number" min="0.01" max="${escapeHtml(item.quantity)}" step="0.01" value="${escapeHtml(item.quantity)}" aria-label="Requested quantity for ${escapeHtml(item.title)}"></label>`;
    return `<article class="donation-card">
      <div class="card-head"><div><div class="card-category">${escapeHtml(item.category)}</div><h3>${escapeHtml(item.title)}</h3></div><span class="badge ${statusTone}">${escapeHtml(labels[item.status] || item.status)}</span></div>
      <p class="card-description">${escapeHtml(item.description || "No additional description provided.")}</p>
      <div class="card-facts">
        <div><div class="fact-label">Available quantity</div><div class="fact-value">${escapeHtml(number(item.quantity))} ${escapeHtml(item.unit)}</div></div>
        <div><div class="fact-label">Location</div><div class="fact-value">${escapeHtml(item.location)}</div></div>
        <div><div class="fact-label">Prepared</div><div class="fact-value">${escapeHtml(formatDate(item.prepared_at))}</div></div>
        <div><div class="fact-label">Pickup by</div><div class="fact-value">${escapeHtml(formatDate(item.pickup_deadline))}</div></div>
        <div><div class="fact-label">Donor</div><div class="fact-value">${escapeHtml(item.donor_name || "FoodLoop donor")}</div></div>
        <div><div class="fact-label">Food suitability</div><div class="fact-value">${item.donor_confirms_edible ? "Donor attested suitable" : "Not confirmed"}</div></div>
        <div><div class="fact-label">Safety review</div><div class="fact-value"><span class="badge ${safetyGood ? "" : "warn"}">${escapeHtml(labels[item.safety_status] || item.safety_status)}</span></div></div>
      </div>
      <div class="safety-note ${safetyGood ? "" : "warning"}">${escapeHtml(item.storage_conditions || "Storage information is missing.")} · ${allergenText}${warnings ? `. ${warnings}` : ""}</div>
      <div class="card-actions">${canClaim ? `${quantity}<button class="button" data-action="claim" data-id="${escapeHtml(item.id)}">Request pickup</button>` : ""}
      ${item.status === "AVAILABLE" && item.safety_status === "ELIGIBLE" ? `<button class="button button-quiet" data-action="matches" data-id="${escapeHtml(item.id)}">View ranked matches</button>` : ""}
      </div><div id="matches-${escapeHtml(item.id)}"></div>
    </article>`;
  }

  async function showMatches(donationId, button) {
    const target = $(`#matches-${CSS.escape(donationId)}`);
    button.disabled = true;
    try {
      const response = await api(`/api/donations/${encodeURIComponent(donationId)}/matches`);
      const eligible = response.matches.filter(match => match.eligible);
      if (!eligible.length) {
        target.innerHTML = '<div class="match-box">No organizations currently meet the safety, quantity and pickup requirements.</div>';
        return;
      }
      target.innerHTML = `<div class="match-box"><strong>Eligible recipient matches</strong><div>${eligible.map(match => `
        <div class="match-item"><span class="match-score">${escapeHtml(match.score)}/100</span> · ${escapeHtml(match.organization_name)}
        <div>${match.reasons.map(escapeHtml).join(" ")}</div></div>`).join("")}</div>
        <div class="form-hint">Weights: distance 35%, urgency 25%, quantity 25%, availability 15%. Missing coordinates use a neutral score and are not shown as a distance.</div></div>`;
    } catch (error) {
      target.innerHTML = `<div class="error-state">${escapeHtml(error.message)}</div>`;
    } finally {
      button.disabled = false;
    }
  }

  async function submitClaim(donationId, button) {
    const amount = Number($(`[data-quantity="${CSS.escape(donationId)}"]`).value);
    if (!(amount > 0)) {
      showToast("Enter a positive pickup quantity.", true);
      return;
    }
    if (!window.confirm(`Request ${number(amount)} portions from this donation?`)) return;
    button.disabled = true;
    try {
      await api(`/api/donations/${encodeURIComponent(donationId)}/claims`, {
        method: "POST",
        body: JSON.stringify({ recipient_id: state.identity, requested_quantity: amount }),
      });
      showToast("Pickup requested. The donor can now review and accept it.");
      await loadDonations();
    } catch (error) {
      showToast(error.message, true);
      button.disabled = false;
    }
  }

  function setDateDefaults() {
    const prepared = new Date(Date.now() - 60 * 60 * 1000);
    const deadline = new Date(Date.now() + 6 * 60 * 60 * 1000);
    const localValue = date => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    $("#donation-form [name=prepared_at]").value = localValue(prepared);
    $("#donation-form [name=pickup_deadline]").value = localValue(deadline);
  }

  async function createDonation(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const data = Object.fromEntries(values.entries());
    const asOptionalNumber = key => data[key] === "" || data[key] === undefined ? null : Number(data[key]);
    const known = form.elements.allergen_info_known.checked;
    const payload = {
      title: data.title.trim(),
      category: data.category,
      description: data.description.trim(),
      quantity: Number(data.quantity),
      unit: data.unit.trim(),
      prepared_at: new Date(data.prepared_at).toISOString(),
      pickup_deadline: new Date(data.pickup_deadline).toISOString(),
      donor_confirms_edible: form.elements.donor_confirms_edible.checked,
      location: data.location.trim(),
      storage_conditions: data.storage_conditions.trim(),
      allergen_info_known: known,
      allergens: known ? data.allergens.split(",").map(item => item.trim()).filter(Boolean) : [],
      minimum_quantity: asOptionalNumber("minimum_quantity"),
      maximum_quantity: asOptionalNumber("maximum_quantity"),
      latitude: asOptionalNumber("latitude"),
      longitude: asOptionalNumber("longitude"),
    };
    if (!window.confirm(`Publish "${payload.title}" with these donation details?`)) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const created = await api("/api/donations", { method: "POST", body: JSON.stringify(payload) });
      showToast(created.safety_status === "ELIGIBLE"
        ? "Donation published and eligible for matching."
        : "Donation published, but it needs a human safety review before it can be claimed.");
      form.reset();
      form.elements.allergen_info_known.checked = true;
      setDateDefaults();
      navigate("find");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  const workflow = ["REQUESTED", "ACCEPTED", "READY_FOR_PICKUP", "COMPLETED"];
  function claimActions(claim) {
    const buttons = [];
    if ((state.role === "donor" || state.role === "admin") && claim.status === "REQUESTED") {
      buttons.push(["ACCEPTED", "Accept request"]);
    }
    if ((state.role === "donor" || state.role === "admin") && claim.status === "ACCEPTED") {
      buttons.push(["READY_FOR_PICKUP", "Mark ready for pickup"]);
    }
    if ((state.role === "recipient" || state.role === "donor") && claim.status === "READY_FOR_PICKUP") {
      buttons.push(["COMPLETED", "Confirm handover"]);
    }
    if (["REQUESTED", "ACCEPTED", "READY_FOR_PICKUP"].includes(claim.status)) {
      buttons.push(["CANCELLED", "Cancel request"]);
    }
    return buttons.map(([status, text]) => `<button class="button ${status === "CANCELLED" ? "button-quiet" : ""}" data-action="claim-status" data-id="${escapeHtml(claim.id)}" data-status="${status}">${text}</button>`).join("");
  }

  function claimCard(claim) {
    const current = workflow.indexOf(claim.status);
    const timeline = workflow.map((status, index) => `<div class="timeline-step ${index <= current ? "done" : ""}">${escapeHtml(labels[status])}</div>`).join("");
    return `<article class="claim-card">
      <div class="claim-top"><div><h3>${escapeHtml(claim.donation_title)}</h3><div class="claim-meta">${escapeHtml(claim.organization_name)} · ${escapeHtml(number(claim.requested_quantity))} ${escapeHtml(claim.unit || "")}</div><div class="claim-meta">${escapeHtml(claim.location || "")} · pickup by ${escapeHtml(formatDate(claim.pickup_deadline))}</div></div><span class="badge ${claim.status === "COMPLETED" ? "" : "neutral"}">${escapeHtml(labels[claim.status] || claim.status)}</span></div>
      <div class="timeline" aria-label="Pickup workflow">${timeline}</div>
      <div class="claim-meta">Last update: ${escapeHtml(formatDate(claim.updated_at))}${claim.completed_at ? ` · Handover confirmed: ${escapeHtml(formatDate(claim.completed_at))}` : ""}</div>
      <div class="claim-actions">${claimActions(claim)}</div>
    </article>`;
  }

  async function loadClaims() {
    const target = $("#claims-list");
    showLoading(target, "Loading pickup activity…");
    try {
      const claims = await api("/api/claims");
      if (!claims.length) {
        target.innerHTML = '<div class="empty-state">No pickup requests to show for this role yet. Browse eligible donations to start one.</div>';
        return;
      }
      target.innerHTML = claims.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)).map(claimCard).join("");
    } catch (error) {
      showError(target, error);
    }
  }

  async function changeClaimStatus(claimId, status, button) {
    const consequence = status === "COMPLETED"
      ? "Confirm that the food has actually been handed over?"
      : status === "CANCELLED"
        ? "Cancel this pickup request?"
        : `${labels[status]}?`;
    if (!window.confirm(consequence)) return;
    button.disabled = true;
    try {
      await api(`/api/claims/${encodeURIComponent(claimId)}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      showToast(status === "COMPLETED" ? "Handover confirmed. Impact totals have been updated." : "Pickup status updated.");
      await loadClaims();
      await loadHome();
    } catch (error) {
      showToast(error.message, true);
      button.disabled = false;
    }
  }

  async function loadImpact() {
    const stats = $("#impact-stats");
    const recent = $("#recent-activity");
    showLoading(stats);
    try {
      const data = await api("/api/impact");
      stats.innerHTML = [
        statCard(data.completed_donations, "Completed donations", "Actual completed records"),
        statCard(number(data.portions_donated), "Portions donated", "Only portion units included"),
        statCard(data.active_available_listings, "Available listings", "Current available donations"),
        statCard(data.active_pickup_claims, "Active pickup claims", "Requested through ready"),
      ].join("");
      $("#impact-note").textContent = `${data.assumption} ${data.activity_notice}`;
      recent.innerHTML = data.recent_completed.length
        ? data.recent_completed.map(item => `<div class="activity-row"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(number(item.quantity))} ${escapeHtml(item.unit)} · ${escapeHtml(item.location)}</span><span>Completed ${escapeHtml(formatDate(item.updated_at))}</span></div>`).join("")
        : '<div class="empty-state">No completed pickups yet. A confirmed handover will appear here.</div>';
    } catch (error) {
      showError(stats, error);
      recent.innerHTML = "";
    }
  }

  function reviewItem(title, text, buttons) {
    return `<div class="review-row"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(text)}</p><div class="card-actions">${buttons}</div></div>`;
  }

  async function adminAction(path, action, note = "") {
    if (!window.confirm("Apply this administrative action?")) return;
    try {
      await api(path, { method: "PATCH", body: JSON.stringify({ action, note }) });
      showToast("Administrative review updated.");
      await loadAdmin();
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function loadAdmin() {
    const target = $("#admin-content");
    showLoading(target, "Loading review queues…");
    try {
      const data = await api("/api/admin/reviews");
      const organizations = data.organizations.map(org => reviewItem(
        org.name,
        `${org.verification_status} verification · ${org.location || "No location provided"}`,
        `<button class="button" data-action="verify-org" data-id="${escapeHtml(org.id)}">Verify organization</button>`,
      )).join("") || '<p class="muted small">No organizations waiting for review.</p>';
      const safety = data.safety_reviews.map(item => reviewItem(
        item.title,
        `${labels[item.safety_status] || item.safety_status} · ${item.safety_warnings?.join(" ") || "Deadline expired or requires review."}`,
        `${item.safety_status !== "EXPIRED" ? `<button class="button" data-action="review" data-id="${escapeHtml(item.id)}" data-review="resolve">Resolve review</button>` : ""}<button class="button button-quiet" data-action="review" data-id="${escapeHtml(item.id)}" data-review="flag">Flag</button><button class="button button-quiet" data-action="review" data-id="${escapeHtml(item.id)}" data-review="withdraw">Withdraw</button>`,
      )).join("") || '<p class="muted small">No listings waiting for a safety review.</p>';
      const active = data.active_claims.map(claim => reviewItem(
        `${claim.id} · ${labels[claim.status] || claim.status}`,
        `Donation ${claim.donation_id} · ${number(claim.requested_quantity)} requested`,
        "",
      )).join("") || '<p class="muted small">No active pickup claims.</p>';
      const completed = data.completed_donations.map(item => reviewItem(
        item.title,
        `${number(item.quantity)} ${item.unit} · completed ${formatDate(item.updated_at)}`,
        "",
      )).join("") || '<p class="muted small">No completed donation records.</p>';
      target.innerHTML = `
        <section class="admin-panel"><h2>Organization verification</h2>${organizations}</section>
        <section class="admin-panel"><h2>Safety review queue</h2>${safety}</section>
        <section class="admin-panel"><h2>Active pickup claims</h2>${active}</section>
        <section class="admin-panel"><h2>Completed donation history</h2>${completed}</section>`;
    } catch (error) {
      showError(target, error);
    }
  }

  async function login(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const submit = event.currentTarget.querySelector('button[type="submit"]');
    submit.disabled = true;
    $("#login-message").textContent = "";
    try {
      const response = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      state.token = response.access_token;
      state.role = response.role;
      state.identity = response.identity;
      sessionStorage.setItem("foodloop-access-token", response.access_token);
      setRoleControls();
      $("#login-dialog").close();
      showToast("Signed in. Your role comes from your FoodLoop profile.");
      navigate("home");
    } catch (error) {
      $("#login-message").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  }

  function wireEvents() {
    $$(".nav-link").forEach(link => link.addEventListener("click", event => {
      event.preventDefault();
      navigate(link.dataset.view);
    }));
    $$("[data-go]").forEach(button => button.addEventListener("click", () => navigate(button.dataset.go)));
    $("#menu-toggle").addEventListener("click", () => {
      const open = $("#main-nav").classList.toggle("open");
      $("#menu-toggle").setAttribute("aria-expanded", String(open));
    });
    $("#role-select").addEventListener("change", event => {
      state.role = event.target.value;
      state.identity = identities[state.role][0][0];
      setRoleControls();
      if ($("#view-find").classList.contains("active")) loadDonations();
      else if ($("#view-tracking").classList.contains("active")) loadClaims();
      else if ($("#view-admin").classList.contains("active")) loadAdmin();
    });
    $("#identity-select").addEventListener("change", event => {
      state.identity = event.target.value;
      if ($("#view-find").classList.contains("active")) loadDonations();
      else if ($("#view-tracking").classList.contains("active")) loadClaims();
    });
    $("#filter-form").addEventListener("submit", event => {
      event.preventDefault();
      loadDonations();
    });
    $("#refresh-donations").addEventListener("click", loadDonations);
    $("#donation-form").addEventListener("submit", createDonation);
    $("#donation-form [name=allergen_info_known]").addEventListener("change", event => {
      $("#donation-form [name=allergens]").disabled = !event.target.checked;
    });
    document.addEventListener("click", event => {
      const button = event.target.closest("[data-action]");
      if (!button) return;
      const { action, id, status } = button.dataset;
      if (action === "matches") showMatches(id, button);
      if (action === "claim") submitClaim(id, button);
      if (action === "claim-status") changeClaimStatus(id, status, button);
      if (action === "verify-org") adminAction(`/api/admin/organizations/${encodeURIComponent(id)}/verify`);
      if (action === "review") {
        const note = button.dataset.review === "resolve" ? "Reviewed through the FoodLoop demonstration admin dashboard." : "";
        adminAction(`/api/admin/donations/${encodeURIComponent(id)}/review`, button.dataset.review, note);
      }
    });
    $("#open-login").addEventListener("click", () => $("#login-dialog").showModal());
    $("#close-login").addEventListener("click", () => $("#login-dialog").close());
    $("#login-form").addEventListener("submit", login);
    $("#sign-out").addEventListener("click", () => {
      state.token = "";
      sessionStorage.removeItem("foodloop-access-token");
      setRoleControls();
      showToast("Signed out.");
    });
    window.addEventListener("hashchange", () => navigate(window.location.hash.slice(1)));
  }

  async function start() {
    wireEvents();
    setDateDefaults();
    await loadStatus();
    navigate(window.location.hash.slice(1) || "home");
  }

  start();
})();
