/* movie-ui page (movie-ui spec Section 12, docs/superpowers/specs/2026-10-19-movie-ui-design.md).
   Vanilla ES2017, no modules, no eval; every confirmation uses the in-page #confirm dialog;
   every text from the server is inserted with textContent. */
"use strict";

(function () {
  const TOKEN_KEY = "movie-ui-token";
  const STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo";
  const BATCH_POLL_MS = 2000;   // batch forks spec 1.1: the jobs poll interval
  const LEVEL_LABELS = {render: "Render", stills: "New stills", replan: "Re-plan"};
  const S = {
    token: null, host: null, ws: null, workspaces: [], options: null, catalog: {video: [], stills: []},
    characters: [], locations: [], location: null, locationPick: [], seedUpload: null, composeAction: "story", story: null, character: null, action: null, selectedJob: null, logOffset: 0,
    logBuffer: "", logLines: [], bannerKind: null, stopped: false, recentSeq: 0, trace: null, traceAgent: null, agents: [], recent: [], timers: {}
  };

  // --- helpers -------------------------------------------------------------------------

  function $(selector) { return document.querySelector(selector); }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") { node.textContent = attrs[key]; }
      else if (key === "cls") { node.className = attrs[key]; }
      else if (key === "data") { Object.keys(attrs.data).forEach(function (d) { node.dataset[d] = attrs.data[d]; }); }
      else { node.setAttribute(key, attrs[key]); }
    });
    (children || []).forEach(function (child) {
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } return node; }

  function show(node, visible) { node.hidden = !visible; }

  function enc(text) { return encodeURIComponent(text); }

  function sizeText(bytes) {
    if (bytes === null || bytes === undefined) { return "-"; }
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let value = bytes;
    let i = 0;
    while (value >= 1024 && i < units.length - 1) { value = value / 1024; i += 1; }
    return (i === 0 ? String(value) : value.toFixed(1)) + " " + units[i];
  }

  function localTime(epoch) {
    if (epoch === null || epoch === undefined) { return "-"; }
    return new Date(epoch * 1000).toLocaleString();
  }

  function utcSeconds(text) { return text ? Date.parse(text) / 1000 : null; }

  function fileUrl(path) {
    return "/files?ws=" + enc(S.ws) + "&path=" + enc(path) + "&t=" + enc(S.token);
  }

  function banner(text, kind) {
    const node = $("#banner");
    $("#banner-text").textContent = text;
    S.bannerKind = text ? (kind || "error") : null;
    show(node, Boolean(text));
  }

  function stopPolling() {
    S.stopped = true;
    ["jobs", "log", "host", "batch"].forEach(function (name) {
      if (S.timers[name]) { clearInterval(S.timers[name]); S.timers[name] = null; }
    });
    if (S.timers.traces) { clearTimeout(S.timers.traces); S.timers.traces = null; }
  }

  async function api(method, path, body, raw) {
    const headers = {"X-Movie-UI-Token": S.token || ""};
    const init = {method: method, headers: headers};
    if (raw) {
      headers["Content-Type"] = raw.type;
      init.body = raw.data;
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch (err) {
      banner("movie-ui is not reachable: " + err, "unreachable");
      return {status: 0, data: {error: String(err)}};
    }
    if (response.status === 401) {
      banner("The token was rejected. Open the URL that movie-ui printed in its terminal.", "auth");
      stopPolling();
    } else if (S.bannerKind === "auth" || S.bannerKind === "unreachable") {
      banner("");
    }
    let data = null;
    try { data = await response.json(); } catch (err) { data = null; }
    return {status: response.status, data: data};
  }

  let pendingConfirm = null;
  function askConfirm(text) {
    if (pendingConfirm) { pendingConfirm(false); }
    return new Promise(function (resolve) {
      const dialog = $("#confirm");
      function done(answer) {
        pendingConfirm = null;
        show(dialog, false);
        $("#confirm-yes").removeEventListener("click", yes);
        $("#confirm-no").removeEventListener("click", no);
        resolve(answer);
      }
      function yes() { done(true); }
      function no() { done(false); }
      pendingConfirm = done;
      $("#confirm-text").textContent = text;
      show(dialog, true);
      $("#confirm-yes").addEventListener("click", yes);
      $("#confirm-no").addEventListener("click", no);
      $("#confirm-no").focus();
    });
  }

  function debounce(fn, ms) {
    let timer = null;
    return function () {
      if (timer) { clearTimeout(timer); }
      timer = setTimeout(fn, ms);
    };
  }

  function wsQuery() { return "?ws=" + enc(S.ws); }

  function numberOrNull(selector) {
    const value = $(selector).value.trim();
    return value === "" ? null : Number(value);
  }

  function textOrNull(selector) {
    const value = $(selector).value.trim();
    return value === "" ? null : value;
  }

  // Resolution presets: the dropdown drives #c-width/#c-height. A concrete preset
  // (WxH) fills and locks the two number inputs; "custom" unlocks them for free entry.
  function applyResPreset() {
    const sel = $("#c-res-preset");
    if (!sel) { return; }
    const custom = sel.value === "custom";
    if (!custom) {
      const wh = sel.value.split("x");
      $("#c-width").value = wh[0];
      $("#c-height").value = wh[1];
    }
    $("#c-width").readOnly = !custom;
    $("#c-height").readOnly = !custom;
    $("#c-width").classList.toggle("preset-locked", !custom);
    $("#c-height").classList.toggle("preset-locked", !custom);
  }

  // Point the dropdown at whatever width/height currently hold (default 1024x576 when
  // empty), falling back to "custom" for any off-list pair, then lock accordingly.
  function syncResPreset() {
    const sel = $("#c-res-preset");
    if (!sel) { return; }
    if (!$("#c-width").value) { $("#c-width").value = 1024; }
    if (!$("#c-height").value) { $("#c-height").value = 576; }
    const key = $("#c-width").value + "x" + $("#c-height").value;
    const known = Array.prototype.some.call(sel.options, function (o) { return o.value === key; });
    sel.value = known ? key : "custom";
    applyResPreset();
  }

  // --- token, header, workspaces, capabilities (MU77, MU78) ---------------------------

  function readToken() {
    const params = new URLSearchParams(location.search);
    const t = params.get("t");
    if (t) {
      sessionStorage.setItem(TOKEN_KEY, t);
      history.replaceState(null, "", "/");
    }
    S.token = sessionStorage.getItem(TOKEN_KEY);
    if (!S.token) {
      banner("The token was rejected. Open the URL that movie-ui printed in its terminal.", "auth");
    }
  }

  function capability(name) {
    const caps = (S.host && S.host.capabilities) || {};
    return caps[name] || {ok: null, reason: "probing"};
  }

  function renderBadges() {
    const reasons = clear($("#badge-reasons"));
    [["render", "#badge-render", "render"], ["stills", "#badge-stills", "stills"],
     ["story_server", "#badge-story", "story server"]].forEach(function (item) {
      const cap = capability(item[0]);
      const node = $(item[1]);
      const word = cap.ok === true ? "ok" : (cap.ok === false ? "unavailable" : "probing");
      node.textContent = item[2] + ": " + word;
      node.className = "badge " + (cap.ok === true ? "ok" : (cap.ok === false ? "bad" : ""));
      if (cap.ok !== true && cap.reason) {
        reasons.appendChild(el("div", {text: item[2] + ": " + cap.reason}));
      }
    });
    const key = S.host && S.host.api_key_present;
    $("#badge-apikey").textContent = "ANTHROPIC_API_KEY: " + (key ? "set" : "not set");
    $("#c-judge").disabled = !key;
    if (!key) { $("#c-judge").checked = false; }
    updateComposeButtons();
    updateCharacterButtons();
    updateLocationButtons();
  }

  async function loadHost(refresh) {
    const res = await api("GET", "/api/host" + (refresh ? "?refresh=1" : ""));
    if (res.status === 200) {
      S.host = res.data;
      renderBadges();
    }
  }

  function workspaceLabel(entry) {
    let label = entry.label;
    if (entry.prune === "kept_for_data") { label += " - kept for data (" + sizeText(entry.data_bytes) + ")"; }
    if (entry.prune === "would_prune") { label += " - would be pruned"; }
    return label;
  }

  async function loadWorkspaces() {
    const res = await api("GET", "/api/workspaces");
    if (res.status !== 200) { return; }
    S.workspaces = res.data.workspaces;
    const select = clear($("#ws-select"));
    S.workspaces.forEach(function (entry) {
      select.appendChild(el("option", {value: entry.path, text: workspaceLabel(entry)}));
    });
    if (!S.workspaces.some(function (e) { return e.path === res.data["default"]; })) {
      select.appendChild(el("option", {value: res.data["default"], text: res.data["default"]}));
    }
    select.value = res.data["default"];
    await selectWorkspace(res.data["default"]);
  }

  async function useTypedPath() {
    const typed = $("#ws-typed").value.trim();
    const res = await api("GET", "/api/options?ws=" + enc(typed));
    if (res.status !== 200) {
      banner(res.data && res.data.error ? res.data.error : "cannot use that path");
      return;
    }
    const select = $("#ws-select");
    const known = Array.prototype.some.call(select.options, function (o) { return o.value === typed; });
    if (!known) { select.appendChild(el("option", {value: typed, text: "typed path"})); }
    select.value = typed;
    await selectWorkspace(typed);
  }

  async function selectWorkspace(path) {
    S.ws = path;
    await loadOptions();
    await Promise.all([loadCatalog(), loadCharacters(), loadLocations(), loadActions(), loadStories(), loadModels()]);
    preview();
  }

  async function loadOptions() {
    const res = await api("GET", "/api/options" + wsQuery());
    if (res.status !== 200) { return; }
    S.options = res.data;
    const supported = res.data.supported;
    document.querySelectorAll("[data-field]").forEach(function (node) {
      const ok = supported[node.dataset.field] !== false;
      if (node.tagName === "OPTION") { node.disabled = !ok; } else { show(node, ok); }
    });
    if (!res.data.help_ok) { banner(res.data.help_error); }
    const d = res.data.defaults;
    fillModelSelect();
    if (!$("#c-gemma").value) { $("#c-gemma").value = d.gemma; }
  }

  // --- tabs (MU79) ---------------------------------------------------------------------

  const TABS = ["compose", "stories", "batches", "characters", "locations", "actions", "loras", "jobs", "traces"];

  function showTab(name) {
    TABS.forEach(function (tab) {
      $("#tab-" + tab).classList.toggle("active", tab === name);
      show($("#panel-" + tab), tab === name);
    });
    if (name !== "batches") { stopBatchPoll(); }
    if (name === "stories") { loadStories(); }
    if (name === "batches") { loadBatches(); }
    if (name === "characters") { loadCharacters(); }
    if (name === "locations") { loadLocations(); }
    if (name === "actions") { loadActions(); }
    if (name === "traces") { loadTraceAgents(); loadRecent(); loadSaved(); }
    if (name === "loras") { loadCatalogTable(); loadModels(); }
  }

  // --- compose (MU80) ------------------------------------------------------------------

  function loraRow(target, item, container) {
    const entries = S.catalog[target];
    const select = el("select", {cls: "lora-pick"});
    entries.forEach(function (e) { select.appendChild(el("option", {value: e.id, text: e.id + " (" + e.kind + ")"})); });
    select.appendChild(el("option", {value: "", text: "path..."}));
    const path = el("input", {type: "text", size: "50", cls: "lora-path", placeholder: "/absolute/path.safetensors"});
    const range = el("input", {type: "range", step: "0.05", cls: "lora-strength"});
    const value = el("span", {cls: "lora-value"});
    const remove = el("button", {type: "button", text: "Remove"});
    const row = el("div", {cls: "lora-row"}, [select, path, range, value, remove]);
    function sync() {
      const entry = entries.find(function (e) { return e.id === select.value; });
      show(path, !entry);
      if (entry) {
        const lo = entry.strength_range ? entry.strength_range[0] : 0.05;
        const hi = entry.strength_range ? entry.strength_range[1] : 2;
        range.min = String(lo);
        range.max = String(hi);
        if (Number(range.value) < lo || Number(range.value) > hi) { range.value = String(entry.default_strength); }
      } else {
        range.min = "0.05";
        range.max = "2";
      }
      value.textContent = Number(range.value).toFixed(2);
      preview();
    }
    if (item) {
      select.value = item.id || "";
      path.value = item.id ? "" : item.path;
      range.min = "0.05";
      range.max = "2";
      range.value = String(item.strength);
    } else if (entries.length) {
      range.value = String(entries[0].default_strength);
    } else {
      range.value = "1";
    }
    select.addEventListener("change", sync);
    range.addEventListener("input", sync);
    path.addEventListener("input", preview);
    remove.addEventListener("click", function () { row.remove(); preview(); });
    (container || $(target === "video" ? "#c-video-loras" : "#c-stills-loras")).appendChild(row);
    sync();
  }

  function collectLoras(target, container) {
    const entries = S.catalog[target];
    const rows = container ? container.querySelectorAll(".lora-row")
      : document.querySelectorAll((target === "video" ? "#c-video-loras" : "#c-stills-loras") + " .lora-row");
    return Array.prototype.map.call(rows, function (row) {
      const id = row.querySelector(".lora-pick").value;
      const entry = entries.find(function (e) { return e.id === id; });
      const strength = Number(row.querySelector(".lora-strength").value);
      if (entry) { return {id: entry.id, path: entry.path, strength: strength, kind: entry.kind}; }
      return {id: null, path: row.querySelector(".lora-path").value.trim(), strength: strength, kind: null};
    });
  }

  function ordered(items) {
    const first = items.filter(function (i) { return i.kind === "motion" || i.kind === "physics"; });
    const rest = items.filter(function (i) { return !(i.kind === "motion" || i.kind === "physics"); });
    return first.concat(rest);
  }

  function composeFields(action) {
    const byLength = $("#c-size-length").checked;
    const bySeed = $("#c-res-seed").checked;
    const supported = (S.options && S.options.supported) || {};
    const goal = textOrNull("#c-goal");
    return {
      ws: S.ws, action: action || "story",
      story_id: $("#c-story-id").value.trim(), narrative: $("#c-narrative").value,
      goal: supported.goal === false ? null : goal,
      panels: byLength ? null : numberOrNull("#c-panels"),
      length: byLength ? numberOrNull("#c-length") : null,
      fps: numberOrNull("#c-fps"), frames: numberOrNull("#c-frames"),
      width: bySeed ? null : numberOrNull("#c-width"), height: bySeed ? null : numberOrNull("#c-height"),
      seed_upload: bySeed ? S.seedUpload : null,
      mode: $("#c-mode").value,
      model: $("#c-model").value === "__download__" ? null : textOrNull("#c-model"),
      gemma: supported.gemma === false ? null : textOrNull("#c-gemma"),
      story_model: textOrNull("#c-story-model"),
      auto_lora: $("#c-auto-lora").checked,
      narration: $("#c-narration").value,
      video_loras: collectLoras("video"), stills_loras: collectLoras("stills"),
      characters: Array.prototype.map.call($("#c-characters").selectedOptions, function (o) { return o.value; }),
      locations: Array.prototype.map.call($("#c-locations").selectedOptions, function (o) { return o.value; }),
      location_strength: numberOrNull("#c-location-strength"),
      action_loras: Array.prototype.map.call($("#c-actions").selectedOptions, function (o) {
        return {name: o.value, strength: numberOrNull("#c-action-strength")};
      }),
      story_legacy: $("#c-story-legacy").checked, judge: $("#c-judge").checked,
      no_low_ram: $("#c-no-low-ram").checked, panel_timeout: numberOrNull("#c-panel-timeout"),
      overwrite_movie: $("#c-overwrite").checked, redo: []
    };
  }

  function updateFrameHints() {
    const frames = Number($("#c-frames").value);
    const fps = Number($("#c-fps").value);
    const ok = Number.isInteger(frames) && (frames - 1) % 8 === 0 && frames >= 9;
    $("#c-frames-check").textContent = ok ? "frames ok" : "frames must satisfy (n-1)%8==0 and n>=9";
    $("#c-seconds-per-panel").textContent = fps > 0 ? (frames / fps).toFixed(2) + " s per panel" : "";
  }

  const preview = debounce(async function () {
    if (!S.ws) { return; }
    updateFrameHints();
    const fields = composeFields(S.composeAction);
    $("#c-command-for").textContent = "(" + S.composeAction + ")";
    const order = ordered(fields.video_loras).concat(ordered(fields.stills_loras));
    $("#c-lora-order").textContent = order.map(function (i) { return i.id || i.path; }).join(", ") || "none";
    S.previewSeq = (S.previewSeq || 0) + 1;
    const seq = S.previewSeq;
    const res = await api("POST", "/api/preview", fields);
    if (seq !== S.previewSeq) { return; }
    const errors = clear($("#c-errors"));
    if (res.status !== 200) {
      errors.appendChild(el("li", {text: (res.data && res.data.error) || ("http " + res.status)}));
      $("#c-command").textContent = "";
      return;
    }
    $("#c-command").textContent = res.data.command || "";
    res.data.errors.forEach(function (line) { errors.appendChild(el("li", {text: line})); });
  }, 300);

  function showChecks(checks) {
    const list = clear($("#c-checks"));
    (checks || []).forEach(function (c) {
      list.appendChild(el("li", {cls: "check-" + c.status, text: c.status + " " + c.id + " " + c.name + ": " + c.detail}));
    });
  }

  async function validate() {
    $("#c-checks").textContent = "validating...";
    const res = await api("POST", "/api/validate", composeFields(S.composeAction));
    if (res.status === 200) { showChecks(res.data.checks); }
    else { showChecks([{status: "fail", id: "", name: "request", detail: (res.data && res.data.error) || ""}]); }
  }

  async function submit(fields) {
    $("#c-checks").textContent = "checking and queueing...";
    const res = await api("POST", "/api/jobs", fields);
    if (res.status === 201) {
      showChecks(res.data.checks);
      selectJob(res.data.job.id);
      await pollJobs();
      if (!(res.data.checks || []).some(function (c) { return c.status === "warn"; })) { showTab("jobs"); }
    } else if (res.status === 409) {
      showChecks(res.data.checks);
    } else {
      showChecks([{status: "fail", id: "", name: "request", detail: (res.data && res.data.error) || ""}]);
    }
    return res;
  }

  function gate(button, reasonNode, needs) {
    const missing = needs.filter(function (name) { return capability(name).ok !== true; });
    button.disabled = missing.length > 0;
    reasonNode.textContent = missing.map(function (name) {
      return name.replace("_", " ") + " unavailable: " + (capability(name).reason || "probing");
    }).join("; ");
  }

  function updateComposeButtons() {
    const mode = $("#c-mode").value;
    gate($("#c-run-all"), $("#c-run-all-reason"), mode === "no_stills" ? ["render"] : ["render", "stills"]);
    gate($("#c-write-story"), $("#c-write-story-reason"), []);
    gate($("#c-smoke"), $("#c-smoke-reason"), ["render"]);
    show($("#c-check-seams-box"), mode === "chained");
  }

  async function uploadFile(file) {
    if (file.size > 20 * 1024 * 1024) { throw new Error("image is larger than 20 MiB"); }
    const res = await api("POST", "/api/uploads", undefined, {type: file.type, data: file});
    if (res.status !== 201) { throw new Error((res.data && res.data.error) || ("upload failed: http " + res.status)); }
    return res.data.upload_id;
  }

  async function onSeedFile() {
    const file = $("#c-seed-file").files[0];
    if (!file) { return; }
    $("#c-seed-status").textContent = "uploading...";
    try {
      S.seedUpload = await uploadFile(file);
      $("#c-seed-status").textContent = "uploaded " + S.seedUpload.slice(0, 12);
      $("#c-res-seed").checked = true;
    } catch (err) {
      $("#c-seed-status").textContent = String(err.message);
    }
    preview();
  }

  function fillCompose(fields) {
    const f = Object.assign({}, S.options ? S.options.defaults : {}, fields || {});
    S.composeAction = f.action || "story";
    $("#c-story-id").value = f.story_id || "";
    $("#c-narrative").value = f.narrative || "";
    $("#c-goal").value = f.goal || "";
    $("#c-size-length").checked = f.panels === null && f.length !== null && f.length !== undefined;
    $("#c-size-panels").checked = !$("#c-size-length").checked;
    if (f.panels !== null && f.panels !== undefined) { $("#c-panels").value = f.panels; }
    if (f.length !== null && f.length !== undefined) { $("#c-length").value = f.length; }
    $("#c-fps").value = f.fps || 24;
    $("#c-frames").value = f.frames || 145;
    $("#c-width").value = f.width || 1024;
    $("#c-height").value = f.height || 576;
    syncResPreset();
    S.seedUpload = f.seed_upload || null;
    $("#c-res-seed").checked = Boolean(S.seedUpload);
    $("#c-res-size").checked = !S.seedUpload;
    $("#c-mode").value = f.mode || "chained";
    fillModelSelect(f.model || "");
    $("#c-gemma").value = f.gemma || "";
    $("#c-story-model").value = f.story_model || "";
    $("#c-auto-lora").checked = f.auto_lora !== false;
    $("#c-narration").value = f.narration === false ? "none"
      : (f.narration === "speech" || f.narration === "none") ? f.narration : "full";
    clear($("#c-video-loras"));
    clear($("#c-stills-loras"));
    (f.video_loras || []).forEach(function (item) { loraRow("video", item); });
    (f.stills_loras || []).forEach(function (item) { loraRow("stills", item); });
    Array.prototype.forEach.call($("#c-characters").options, function (o) {
      o.selected = (f.characters || []).indexOf(o.value) >= 0;
    });
    Array.prototype.forEach.call($("#c-locations").options, function (o) {
      o.selected = (f.locations || []).indexOf(o.value) >= 0;
    });
    S.locationPick = (f.locations || []).slice();
    $("#c-location-strength").value = f.location_strength === null || f.location_strength === undefined
      ? "" : f.location_strength;
    const actionNames = (f.action_loras || []).map(function (a) { return a.name; });
    Array.prototype.forEach.call($("#c-actions").options, function (o) {
      o.selected = actionNames.indexOf(o.value) >= 0;
    });
    const actionStrength = (f.action_loras || []).length ? f.action_loras[0].strength : null;
    $("#c-action-strength").value = actionStrength === null || actionStrength === undefined ? "" : actionStrength;
    $("#c-story-legacy").checked = Boolean(f.story_legacy);
    $("#c-judge").checked = Boolean(f.judge);
    $("#c-no-low-ram").checked = Boolean(f.no_low_ram);
    $("#c-panel-timeout").value = fields && fields.panel_timeout ? fields.panel_timeout : "";
    $("#c-overwrite").checked = Boolean(f.overwrite_movie);
    updateComposeButtons();
    preview();
  }

  function setupCompose() {
    const panel = $("#panel-compose");
    panel.addEventListener("input", function (event) {
      if (!event.target.classList.contains("lora-strength")) { preview(); }
    });
    panel.addEventListener("change", function () { updateComposeButtons(); preview(); });
    $("#c-add-video-lora").addEventListener("click", function () { loraRow("video"); });
    $("#c-add-stills-lora").addEventListener("click", function () { loraRow("stills"); });
    $("#c-seed-file").addEventListener("change", onSeedFile);
    $("#c-res-preset").addEventListener("change", applyResPreset);
    syncResPreset();
    $("#c-model").addEventListener("change", function () {
      const sel = $("#c-model");
      if (sel.value === "__download__") {
        show($("#c-model-dl"), true);
        sel.value = sel.dataset.selected || "";
        $("#c-model-dl-repo").focus();
      } else {
        sel.dataset.selected = sel.value;
        show($("#c-model-dl"), false);
      }
    });
    $("#c-model-dl-go").addEventListener("click", function () {
      downloadModel($("#c-model-dl-repo").value, $("#c-model-dl-hub").value, $("#c-model-dl-status"));
    });
    $("#c-copy").addEventListener("click", function () {
      navigator.clipboard.writeText($("#c-command").textContent);
    });
    $("#c-validate").addEventListener("click", validate);
    $("#c-write-story").addEventListener("click", function () { S.composeAction = "story"; submit(composeFields("story")); });
    $("#c-run-all").addEventListener("click", function () {
      S.composeAction = "movie";
      submit(Object.assign(composeFields("movie"),
                           {check_seams: $("#c-mode").value === "chained" && $("#c-check-seams").checked}));
    });
    $("#c-model").addEventListener("change", loadCatalog);
  }

  async function loadCatalog() {
    if (!S.ws) { return; }
    const model = $("#c-model").value.trim() || (S.options ? S.options.defaults.model : "");
    const video = await api("GET", "/api/loras" + wsQuery() + "&model=" + enc(model));
    const stills = await api("GET", "/api/loras" + wsQuery() + "&model=" + enc(STILLS_MODEL));
    S.catalog.video = video.status === 200 ? video.data.entries.filter(function (e) { return e.target === "video"; }) : [];
    S.catalog.stills = stills.status === 200 ? stills.data.entries.filter(function (e) { return e.target === "stills"; }) : [];
  }

  async function loadModels() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/models" + wsQuery());
    if (res.status !== 200) { return; }
    S.models = res.data.models || [];
    S.loraBases = res.data.lora_bases || null;
    const list = clear($("#c-model-list"));
    const body = clear($("#m-table tbody"));
    S.models.forEach(function (m) {
      if (m.hub === "ltx") { list.appendChild(el("option", {value: m.repo})); }
      body.appendChild(el("tr", {}, [el("td", {text: m.hub}), el("td", {text: m.repo}),
        el("td", {text: m.intact ? "yes" : "no", cls: m.intact ? "ok" : "bad"}),
        el("td", {text: m.problems.join("; ")}), el("td", {text: sizeText(m.bytes)})]));
    });
    fillModelSelect();
    fillLoraBaseModels();
  }

  // Video model is a dropdown of locally-available ltx-hub models. A value not present
  // locally (a draft's model) is still listed, flagged; "__download__" is the escape to
  // the inline fetch control.
  function fillModelSelect(preferred) {
    const sel = $("#c-model");
    if (!sel || sel.tagName !== "SELECT") { return; }
    const local = (S.models || []).filter(function (m) { return m.hub === "ltx"; })
      .map(function (m) { return m.repo; });
    const defaultModel = (S.options && S.options.defaults && S.options.defaults.model) || "";
    const want = preferred || sel.dataset.selected || defaultModel || "";
    const options = local.slice();
    if (want && options.indexOf(want) < 0) { options.push(want); }
    options.sort();
    clear(sel);
    options.forEach(function (repo) {
      const missing = local.indexOf(repo) < 0;
      sel.appendChild(el("option", {value: repo, text: repo + (missing ? " — not downloaded" : "")}));
    });
    sel.appendChild(el("option", {value: "__download__", text: "＋ Download a model…"}));
    sel.value = (want && options.indexOf(want) >= 0) ? want : (options[0] || "__download__");
    sel.dataset.selected = sel.value;
  }

  async function downloadModel(repo, hub, statusEl) {
    repo = (repo || "").trim();
    if (!repo) { if (statusEl) { statusEl.textContent = "enter an org/repo id"; } return; }
    if (statusEl) { statusEl.textContent = "queuing…"; }
    const res = await api("POST", "/api/models/download", {ws: S.ws, repo: repo, hub: hub || "ltx"});
    if (res.status !== 201) {
      if (statusEl) { statusEl.textContent = "error: " + ((res.data && res.data.error) || res.status); }
      return;
    }
    const jobId = res.data.job.id;
    if (statusEl) { statusEl.textContent = "downloading… job " + jobId + " (watch in Jobs)"; }
    const timer = setInterval(async function () {
      const jr = await api("GET", "/api/jobs/" + jobId);
      if (jr.status !== 200) { return; }
      const st = jr.data.status ? jr.data.status.state : jr.data.state;
      if (["done", "failed", "cancelled", "lost"].indexOf(st) < 0) { return; }
      clearInterval(timer);
      if (statusEl) { statusEl.textContent = "job " + jobId + " " + st; }
      if (st === "done") { await loadModels(); fillModelSelect(repo); show($("#c-model-dl"), false); }
    }, 2000);
  }

  // --- V7 smoke render (MU52, Q4) ------------------------------------------------------

  async function pollSmoke() {
    if (!S.smokeJob) { return; }
    const res = await api("GET", "/api/jobs/" + S.smokeJob);
    if (res.status !== 200) { return; }
    const state = res.data.status.state;
    const smoke = res.data.progress && res.data.progress.smoke;
    let status = "running";
    if (state === "done" && smoke && smoke.clip_ok) { status = "pass"; }
    else if (["done", "failed", "cancelled", "lost"].indexOf(state) >= 0) { status = "fail"; }
    const node = $("#c-smoke-check");
    node.className = "check-" + status;
    node.textContent = status + " V7 smoke render: job " + S.smokeJob + " " + state + (smoke ? " - " + smoke.clip : "");
    show(node, true);
  }

  function setupSmoke() {
    $("#c-smoke").addEventListener("click", async function () {
      const res = await submit(composeFields("smoke"));
      if (res.status === 201) { S.smokeJob = res.data.job.id; pollSmoke(); }
    });
    setInterval(pollSmoke, 2000);
  }

  // --- stories (MU81) ------------------------------------------------------------------

  async function loadStories() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/stories" + wsQuery());
    const picks = await api("GET", "/api/batches/stories" + wsQuery());
    const keep = pickedStories();
    const body = clear($("#s-list tbody"));
    if (res.status !== 200) { updateNewBatch(); return; }
    const eligibility = {};
    if (picks.status === 200) { picks.data.stories.forEach(function (p) { eligibility[p.id] = p; }); }
    res.data.stories.forEach(function (st) {
      const checks = st.checks ? st.checks.hard + " hard, " + st.checks.advisory + " advisory" +
        (st.checks.verdict ? " (" + st.checks.verdict + ")" : "") : "-";
      const row = el("tr", {data: {storyId: st.id}, cls: "clickable"}, [pickCell(st.id, eligibility[st.id], keep.indexOf(st.id) >= 0),
        el("td", {text: st.id}), el("td", {text: st.story_md ? "yes" : "no"}), el("td", {text: checks}),
        el("td", {text: String(st.stills)}), el("td", {text: String(st.clips)}),
        el("td", {text: st.movie ? "yes" : "no"}), el("td", {text: new Date(st.mtime).toLocaleString()})]);
      row.addEventListener("click", function () { openStory(st.id); });
      body.appendChild(row);
    });
    updateNewBatch();
  }

  function showSeams(data) {
    const chained = data.plan_mode === "chained";
    show($("#s-seams"), Boolean(data.end_frames));
    show($("#s-seams-box"), chained);
    const body = clear($("#s-seams-table tbody"));
    const report = data.end_frames ? data.seams : null;
    show($("#s-seams-table"), Boolean(report));
    if (!chained) { return; }
    if (!data.end_frames) { $("#s-seams-summary").textContent = "This plan has no end frames; no seam report."; return; }
    if (!report) { $("#s-seams-summary").textContent = "No seam report yet: press Check seams."; return; }
    const s = report.summary || {};
    $("#s-seams-summary").textContent = "Mean score " + (s.mean_score === null || s.mean_score === undefined ? "n/a" : s.mean_score)
      + " over " + s.scored + " scored panel(s); " + s.missed + " missed (a score below " + report.threshold + ").";
    (report.panels || []).forEach(function (p) {
      body.appendChild(el("tr", {cls: p.verdict === "missed" ? "seam-missed" : ""}, [
        el("td", {text: String(p.panel)}), el("td", {text: p.score === null ? "-" : String(p.score)}),
        el("td", {text: p.verdict}), el("td", {text: p.reason})]));
    });
  }

  async function openStory(storyId) {
    showTab("stories");
    const res = await api("GET", "/api/stories/" + enc(storyId) + wsQuery());
    if (res.status !== 200) { $("#s-action-status").textContent = (res.data && res.data.error) || "not found"; return; }
    S.story = res.data;
    show($("#s-detail"), true);
    $("#s-title").textContent = storyId;
    $("#s-editor").value = res.data.story_md ? res.data.story_md.text : "";
    $("#s-save-status").textContent = res.data.story_md ? "" : "no story.md yet";
    show($("#s-reload"), false);
    const checks = clear($("#s-checks"));
    if (res.data.checks) {
      ["hard", "advisory"].forEach(function (kind) {
        const list = el("ul", {cls: kind});
        (res.data.checks[kind] || []).forEach(function (v) { list.appendChild(el("li", {text: v.message || JSON.stringify(v)})); });
        checks.appendChild(el("h4", {text: kind + " (" + (res.data.checks[kind] || []).length + ")"}));
        checks.appendChild(list);
      });
    } else {
      checks.textContent = "no story_checks.json";
    }
    $("#s-picks").textContent = res.data.plan_loras ? JSON.stringify(res.data.plan_loras, null, 2) : "none";
    const gallery = clear($("#s-gallery"));
    res.data.stills.forEach(function (p) { gallery.appendChild(el("img", {src: fileUrl(p), alt: p, title: p})); });
    res.data.clips.forEach(function (p) { gallery.appendChild(el("video", {src: fileUrl(p), controls: "", preload: "metadata"})); });
    if (res.data.movie) {
      gallery.appendChild(el("div", {cls: "movie"}, [el("h4", {text: "movie.mp4"}),
        el("video", {src: fileUrl(res.data.movie), controls: "", preload: "metadata"})]));
    }
    const shots = res.data.plan_mode === "shots" || (res.data.last_fields && res.data.last_fields.mode === "shots");
    show($("#s-redo-box"), Boolean(shots));
    const regen = $("#s-regen-panels");
    const lastPanels = res.data.last_fields ? res.data.last_fields.panels : null;
    regen.value = lastPanels !== null && lastPanels !== undefined ? String(lastPanels) : "";
    regen.placeholder = res.data.checks && res.data.checks.panels ? String(res.data.checks.panels) : "";
    $("#s-action-status").textContent = res.data.last_fields ? "" : "no earlier job for this story: Render opens Compose with only its ID";
    showSeams(res.data);
  }

  async function saveStory() {
    const st = S.story;
    const res = await api("PUT", "/api/stories/" + enc(st.id) + "/story.md",
                          {ws: S.ws, text: $("#s-editor").value, base_sha256: st.story_md ? st.story_md.sha256 : null});
    if (res.status === 200) {
      st.story_md = {text: $("#s-editor").value, sha256: res.data.sha256};
      $("#s-save-status").textContent = "saved" + (res.data.backup ? "; backup " + res.data.backup : "");
      show($("#s-reload"), false);
    } else {
      $("#s-save-status").textContent = (res.data && res.data.error) || ("http " + res.status);
      show($("#s-reload"), res.status === 409);
    }
  }

  function storyFields(action) {
    const st = S.story;
    if (st.last_fields) { return Object.assign({}, st.last_fields, {ws: S.ws, action: action}); }
    const saved = st.checks ? (st.checks.panels_target || st.checks.panels) : null;
    const panels = saved ? saved : (S.options ? S.options.defaults.panels : 15);
    return {story_id: st.id, panels: panels, action: action};
  }

  function setupStories() {
    $("#s-save").addEventListener("click", saveStory);
    $("#s-new-batch").addEventListener("click", function () { openBatchEditor(pickedStories()); });
    $("#s-reload").addEventListener("click", function () { openStory(S.story.id); });
    $("#s-render").addEventListener("click", function () {
      fillCompose(storyFields("movie"));
      showTab("compose");
    });
    $("#s-regenerate").addEventListener("click", async function () {
      if (!S.story.last_fields) { $("#s-action-status").textContent = "compose this story once before regenerating it"; return; }
      if ($("#s-regen-panels").validity.badInput) { $("#s-action-status").textContent = "panels must be a whole number"; return; }
      const target = numberOrNull("#s-regen-panels");
      const question = target === null
        ? "Regenerate story.md of " + S.story.id + "? The current one is replaced."
        : "Regenerate story.md of " + S.story.id + " with a target of " + target + " panels? The current one is replaced.";
      if (!(await askConfirm(question))) { return; }
      const fields = storyFields("regenerate");
      const res = await submit(target === null ? fields : Object.assign(fields, {panels: target, length: null}));
      $("#s-action-status").textContent = res.status === 201 ? "queued" : "refused; see Compose checks";
    });
    $("#s-redo").addEventListener("click", async function () {
      if (!S.story.last_fields) { $("#s-action-status").textContent = "compose this story once before a redo"; return; }
      const panels = $("#s-redo-panels").value.split(",").map(function (v) { return Number(v.trim()); })
        .filter(function (n) { return Number.isInteger(n) && n > 0; });
      const res = await submit(Object.assign(storyFields("redo"), {redo: panels, mode: "shots"}));
      $("#s-action-status").textContent = res.status === 201 ? "queued" : "refused; see Compose checks";
    });
    $("#s-seams").addEventListener("click", async function () {
      const res = await api("POST", "/api/stories/" + enc(S.story.id) + "/seams", {ws: S.ws});
      $("#s-action-status").textContent = res.status === 201 ? "seams check queued as job " + res.data.job.id
        : ((res.data && res.data.error) || ("http " + res.status));
      if (res.status === 201) { pollJobs(); }
    });
  }

  // --- batches (batch forks spec Section 5, BF36-BF39) ---------------------------------

  // The editor's "Add setting…" menu, grouped by what a change costs (BF38): [key, label].
  const BATCH_SETTINGS = [
    ["Render", [["model", "Video model"], ["gemma", "Gemma"], ["video_loras", "Video LoRAs"],
                ["action_loras", "Actions"], ["frames", "Frames per panel"], ["fps", "FPS"],
                ["no_low_ram", "No low-RAM mode"], ["panel_timeout", "Panel timeout (s)"]]],
    ["New stills", [["resolution", "Resolution"], ["stills_loras", "Stills LoRAs"],
                    ["location_strength", "Location strength"]]],
    ["Re-plan", [["size", "Size"], ["goal", "Goal"], ["seed_upload", "Seed image"], ["mode", "Mode"],
                 ["story_model", "Story model"], ["auto_lora", "Auto-pick catalog LoRAs"], ["narration", "Narration"],
                 ["characters", "Cast"], ["locations", "Locations"], ["story_legacy", "Legacy story engine"],
                 ["judge", "Judge with Claude"]]]
  ];
  // The Compose control each single-control setting copies (BF38).
  const BATCH_CONTROLS = {
    gemma: "#c-gemma", goal: "#c-goal", story_model: "#c-story-model", frames: "#c-frames", fps: "#c-fps",
    panel_timeout: "#c-panel-timeout", location_strength: "#c-location-strength", no_low_ram: "#c-no-low-ram",
    auto_lora: "#c-auto-lora", story_legacy: "#c-story-legacy", judge: "#c-judge", mode: "#c-mode",
    narration: "#c-narration", characters: "#c-characters", locations: "#c-locations"
  };

  function cloneControl(selector) {
    const node = $(selector).cloneNode(true);
    node.removeAttribute("id");
    node.querySelectorAll("[id]").forEach(function (n) { n.removeAttribute("id"); });
    return node;
  }

  function nodeNumber(node) {
    const value = node.value.trim();
    return value === "" ? null : Number(value);
  }

  function nodeText(node) {
    const value = node.value.trim();
    return value === "" ? null : value;
  }

  function selectedValues(node) {
    return Array.prototype.map.call(node.selectedOptions, function (o) { return o.value; });
  }

  function selectValues(node, values) {
    Array.prototype.forEach.call(node.options, function (o) { o.selected = (values || []).indexOf(o.value) >= 0; });
  }

  function hasOption(node, value) {
    return Array.prototype.some.call(node.options, function (o) { return o.value === value; });
  }

  function batchFileUrl(ws, path) {
    return "/files?ws=" + enc(ws) + "&path=" + enc(path) + "&t=" + enc(S.token);
  }

  function levelBadge(level) { return el("span", {cls: "badge level-" + level, text: LEVEL_LABELS[level]}); }

  function batchNote(source) {
    return el("span", {cls: "s-pick-note muted", text: "settings from batch b" + source.number,
                       title: "This fork's job was deleted; its settings come from batch " + source.id});
  }

  function diffValue(key, value) {
    if (value === null || value === undefined) { return "default"; }
    if (key === "video_loras" || key === "stills_loras") {
      return value.map(function (i) { return (i.id || String(i.path).split("/").pop()) + " @ " + i.strength; }).join(", ") || "none";
    }
    if (key === "action_loras") {
      return value.map(function (a) { return a.name + (a.strength === null ? "" : " @ " + a.strength); }).join(", ") || "none";
    }
    if (Array.isArray(value)) { return value.join(", ") || "none"; }
    return String(value);
  }

  function diffLine(d) {
    if (d.key === "narrative") { return "narrative: prompt edited"; }
    return d.key + ": " + diffValue(d.key, d.from) + " → " + diffValue(d.key, d.to) + (d.note ? " (" + d.note + ")" : "");
  }

  // --- the Stories tab's checkboxes (BF36)

  function pickedStories() {
    return Array.prototype.filter.call(document.querySelectorAll("#s-list .s-pick"), function (b) { return b.checked; })
      .map(function (b) { return b.dataset.storyId; });
  }

  function updateNewBatch() {
    const n = pickedStories().length;
    $("#s-new-batch").textContent = "New batch (" + n + ")";
    show($("#s-new-batch"), n >= 1);
  }

  function pickCell(storyId, info, checked) {
    const box = el("input", {type: "checkbox", cls: "s-pick", data: {storyId: storyId}});
    const cell = el("td", {}, [box]);
    if (!info || !info.eligible) {
      box.disabled = true;
      box.title = info ? info.reason : "batch eligibility is not known";
    } else if (checked) {
      box.checked = true;
    }
    if (info && info.fields_source === "batch") {
      cell.appendChild(document.createTextNode(" "));
      cell.appendChild(batchNote(info.fields_batch));
    }
    box.addEventListener("click", function (event) { event.stopPropagation(); updateNewBatch(); });
    return cell;
  }

  // --- the Batches tab: one box at a time (BF37)

  function stopBatchPoll() {
    if (S.timers.batch) { clearInterval(S.timers.batch); S.timers.batch = null; }
  }

  function showBatchBox(name) {
    show($("#b-list-box"), name === "list");
    show($("#b-editor"), name === "editor");
    show($("#b-page"), name === "page");
    if (name !== "page") { stopBatchPoll(); }
  }

  async function loadBatches() {
    showBatchBox("list");
    if (!S.ws) { return; }
    const res = await api("GET", "/api/batches" + wsQuery());
    const body = clear($("#b-list tbody"));
    if (res.status !== 200) { return; }
    res.data.batches.forEach(function (b) {
      const row = el("tr", {data: {batchId: b.id}, cls: "clickable"}, [el("td", {text: b.id}),
        el("td", {text: new Date(b.created).toLocaleString()}), el("td", {text: b.done + "/" + b.cells}),
        el("td", {text: b.status})]);
      row.addEventListener("click", function () { openBatch(b.id); });
      body.appendChild(row);
    });
  }

  // --- the editor (BF38)

  function batchCards() { return Array.prototype.slice.call(document.querySelectorAll("#b-variants .b-variant")); }

  function batchStart() {
    const ed = S.bEditor;
    const row = ed && ed.rows.length ? ed.rows[0] : null;
    return Object.assign({}, S.options ? S.options.defaults : {}, row && row.fields ? row.fields : {});
  }

  function settingLabel(key) {
    let label = key;
    BATCH_SETTINGS.forEach(function (group) {
      group[1].forEach(function (item) { if (item[0] === key) { label = item[1]; } });
    });
    return label;
  }

  function settingsMenu() {
    const menu = el("select", {cls: "b-add-setting"}, [el("option", {value: "", text: "Add setting…"})]);
    BATCH_SETTINGS.forEach(function (group) {
      menu.appendChild(el("optgroup", {label: group[0]}, group[1].map(function (item) {
        return el("option", {value: item[0], text: item[1]});
      })));
    });
    return menu;
  }

  // One setting's control, started at the original's value f[key]; read() gives its settings.
  function settingControl(key, f) {
    let node;
    let read;
    if (key === "model") {
      node = cloneControl("#c-model");
      Array.prototype.slice.call(node.options).forEach(function (o) { if (o.value === "__download__") { o.remove(); } });
      if (f.model && !hasOption(node, f.model)) { node.appendChild(el("option", {value: f.model, text: f.model})); }
      node.value = f.model || "";
      read = function () { return {model: node.value || null}; };
    } else if (["gemma", "goal", "story_model"].indexOf(key) >= 0) {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.value = f[key] === null || f[key] === undefined ? "" : String(f[key]);
      read = function () { const out = {}; out[key] = nodeText(node); return out; };
    } else if (["frames", "fps", "panel_timeout", "location_strength"].indexOf(key) >= 0) {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.value = f[key] === null || f[key] === undefined ? "" : String(f[key]);
      read = function () { const out = {}; out[key] = nodeNumber(node); return out; };
    } else if (["no_low_ram", "auto_lora", "story_legacy", "judge"].indexOf(key) >= 0) {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.checked = key === "auto_lora" ? f.auto_lora !== false : Boolean(f[key]);
      read = function () { const out = {}; out[key] = node.checked; return out; };
    } else if (key === "mode" || key === "narration") {
      node = cloneControl(BATCH_CONTROLS[key]);
      node.value = f[key] || (key === "mode" ? "chained" : "full");
      read = function () { const out = {}; out[key] = node.value; return out; };
    } else if (key === "characters" || key === "locations") {
      node = cloneControl(BATCH_CONTROLS[key]);
      selectValues(node, f[key]);
      read = function () { const out = {}; out[key] = selectedValues(node); return out; };
    } else if (key === "action_loras") {
      const pick = cloneControl("#c-actions");
      const strength = cloneControl("#c-action-strength");
      const items = f.action_loras || [];
      selectValues(pick, items.map(function (a) { return a.name; }));
      strength.value = items.length && items[0].strength !== null && items[0].strength !== undefined ? String(items[0].strength) : "";
      node = el("span", {}, [pick, " Strength ", strength]);
      read = function () {
        return {action_loras: selectedValues(pick).map(function (name) { return {name: name, strength: nodeNumber(strength)}; })};
      };
    } else if (key === "resolution") {
      const preset = cloneControl("#c-res-preset");
      const width = cloneControl("#c-width");
      const height = cloneControl("#c-height");
      const lock = function () {
        const custom = preset.value === "custom";
        width.readOnly = !custom;
        height.readOnly = !custom;
      };
      width.value = String(f.width || 1024);
      height.value = String(f.height || 576);
      preset.value = hasOption(preset, width.value + "x" + height.value) ? width.value + "x" + height.value : "custom";
      lock();
      preset.addEventListener("change", function () {
        if (preset.value !== "custom") {
          const wh = preset.value.split("x");
          width.value = wh[0];
          height.value = wh[1];
        }
        lock();
      });
      node = el("span", {}, [preset, width, " x ", height]);
      read = function () { return {width: nodeNumber(width), height: nodeNumber(height)}; };
    } else if (key === "size") {
      const kind = el("select", {cls: "b-size-kind"}, [el("option", {value: "panels", text: "Panels"}),
                                                        el("option", {value: "length", text: "Seconds"})]);
      const count = cloneControl("#c-panels");
      const bounds = function () {
        count.max = kind.value === "length" ? "3600" : "200";
        count.step = kind.value === "length" ? "0.5" : "1";
      };
      const byLength = (f.panels === null || f.panels === undefined) && f.length !== null && f.length !== undefined;
      kind.value = byLength ? "length" : "panels";
      count.value = String(byLength ? f.length : (f.panels === null || f.panels === undefined ? 15 : f.panels));
      bounds();
      kind.addEventListener("change", bounds);
      node = el("span", {}, [kind, count]);
      read = function () { const out = {}; out[kind.value] = nodeNumber(count); return out; };
    } else if (key === "seed_upload") {
      const file = cloneControl("#c-seed-file");
      let upload = f.seed_upload || null;
      const status = el("span", {cls: "muted", text: upload ? "upload " + upload.slice(0, 12) : "no seed image"});
      file.addEventListener("change", async function () {
        const chosen = file.files[0];
        if (!chosen) { return; }
        status.textContent = "uploading...";
        try {
          upload = await uploadFile(chosen);
          status.textContent = "uploaded " + upload.slice(0, 12);
        } catch (err) {
          status.textContent = String(err.message);
        }
        batchPreview();
      });
      node = el("span", {}, [file, status]);
      read = function () { return {seed_upload: upload}; };
    } else {
      const target = key === "video_loras" ? "video" : "stills";
      const box = el("div", {cls: "b-loras"});
      const add = el("button", {type: "button", text: "Add"});
      add.addEventListener("click", function () { loraRow(target, null, box); });
      (f[key] || []).forEach(function (item) { loraRow(target, item, box); });
      node = el("span", {}, [add, box]);
      read = function () { const out = {}; out[key] = collectLoras(target, box); return out; };
    }
    return {node: node, read: read};
  }

  function syncMenu(card) {
    const used = Array.prototype.map.call(card.querySelectorAll(".b-setting"), function (r) { return r.dataset.key; });
    Array.prototype.forEach.call(card.querySelector(".b-add-setting").options, function (o) {
      o.disabled = o.value !== "" && used.indexOf(o.value) >= 0;
    });
  }

  function addSettingRow(card, key) {
    const control = settingControl(key, batchStart());
    const remove = el("button", {type: "button", text: "Remove"});
    const row = el("div", {cls: "b-setting", data: {key: key}}, [el("span", {text: settingLabel(key)}), control.node, remove]);
    row.readSetting = control.read;
    remove.addEventListener("click", function () { row.remove(); syncMenu(card); });
    card.querySelector(".b-settings").appendChild(row);
    syncMenu(card);
  }

  function syncReplaces(card) {
    card.querySelector(".b-add-replace").disabled = card.querySelectorAll(".b-replace").length >= 10;
  }

  function addReplaceRow(card) {
    const box = card.querySelector(".b-replaces");
    if (box.querySelectorAll(".b-replace").length >= 10) { return; }
    const remove = el("button", {type: "button", text: "Remove"});
    const row = el("div", {cls: "b-replace"}, [el("input", {type: "text", cls: "b-find", size: "30", placeholder: "Find"}),
      el("input", {type: "text", cls: "b-with", size: "30", placeholder: "Replace with"}), remove]);
    remove.addEventListener("click", function () { row.remove(); syncReplaces(card); });
    box.appendChild(row);
    syncReplaces(card);
  }

  function syncCards() {
    const cards = batchCards();
    cards.forEach(function (card) { show(card.querySelector(".b-remove-variant"), cards.length > 1); });
    $("#b-add-variant").disabled = cards.length >= 6;
    $("#b-variant-note").textContent = cards.length >= 6 ? "at most 6 variants" : "";
  }

  function addVariantCard() {
    const used = batchCards().map(function (c) { return c.querySelector(".b-label").value; });
    if (used.length >= 6) { return; }
    let k = 1;
    while (used.indexOf("v" + k) >= 0) { k += 1; }
    const menu = settingsMenu();
    const addReplace = el("button", {type: "button", cls: "b-add-replace", text: "Add find → replace"});
    const remove = el("button", {type: "button", cls: "b-remove-variant", text: "Remove variant"});
    const label = el("input", {type: "text", cls: "b-label", maxlength: "24", size: "12", value: "v" + k});
    const card = el("div", {cls: "b-variant"}, [
      el("div", {cls: "row"}, [el("label", {}, ["Label ", label]), menu, remove]),
      el("div", {cls: "b-settings"}),
      el("textarea", {cls: "b-append", rows: "2", placeholder: "Append to every prompt"}),
      el("div", {cls: "b-replaces"}, [addReplace])]);
    card.perStory = {};
    menu.addEventListener("change", function () {
      if (menu.value) { addSettingRow(card, menu.value); }
      menu.value = "";
    });
    addReplace.addEventListener("click", function () { addReplaceRow(card); });
    remove.addEventListener("click", function () { card.remove(); syncCards(); });
    $("#b-variants").appendChild(card);
    syncCards();
  }

  // The request body of the preview and the submit (spec 3.2); a find/replace row with an empty Find is not sent.
  function batchBody() {
    const variants = batchCards().map(function (card) {
      const settings = {};
      card.querySelectorAll(".b-setting").forEach(function (row) { Object.assign(settings, row.readSetting()); });
      const replace = Array.prototype.filter.call(card.querySelectorAll(".b-replace"), function (row) {
        return row.querySelector(".b-find").value !== "";
      }).map(function (row) {
        return {"find": row.querySelector(".b-find").value, "with": row.querySelector(".b-with").value};
      });
      return {label: card.querySelector(".b-label").value, settings: settings,
              prompt: {append: card.querySelector(".b-append").value, replace: replace, per_story: Object.assign({}, card.perStory)}};
    });
    return {ws: S.ws, stories: S.bEditor.stories, variants: variants};
  }

  function previewCell(c) {
    const td = el("td", {}, [el("div", {text: c.fork_id})]);
    if (c.level) { td.appendChild(levelBadge(c.level)); }
    c.diff.forEach(function (d) { td.appendChild(el("div", {cls: "muted", text: diffLine(d)})); });
    const warnings = el("ul", {cls: "warnings"});
    c.warnings.forEach(function (w) { warnings.appendChild(el("li", {text: w})); });
    td.appendChild(warnings);
    if (c.status !== "ok") { td.appendChild(el("div", {cls: "bad", text: c.status + ": " + c.reason})); }
    const edit = button("Edit prompt", function () { openPromptDialog(c.story_id, c.variant - 1); });
    edit.className = "b-edit-prompt";
    td.appendChild(edit);
    return td;
  }

  function renderBatchPreview(data) {
    const labels = batchCards().map(function (c) { return c.querySelector(".b-label").value; });
    clear($("#b-preview thead")).appendChild(el("tr", {}, [el("th", {text: "Story"})].concat(
      labels.map(function (label) { return el("th", {text: label}); }))));
    const body = clear($("#b-preview tbody"));
    data.rows.forEach(function (row) {
      const first = el("td", {text: row.story_id});
      if (row.fields_source === "batch") {
        first.appendChild(document.createTextNode(" "));
        first.appendChild(batchNote(row.fields_batch));
      }
      body.appendChild(el("tr", {}, [first].concat(data.cells.filter(function (c) { return c.story_id === row.story_id; })
        .map(previewCell))));
    });
    $("#b-totals").textContent = data.totals.text;
    $("#b-submit").disabled = data.totals.jobs === 0;
  }

  const batchPreview = debounce(async function () {
    const ed = S.bEditor;
    if (!ed) { return; }
    S.batchSeq = (S.batchSeq || 0) + 1;
    const seq = S.batchSeq;
    const res = await api("POST", "/api/batches/preview", batchBody());
    if (seq !== S.batchSeq || ed !== S.bEditor) { return; }
    if (res.status !== 200) {
      $("#b-editor-status").textContent = errorText(res);
      $("#b-totals").textContent = "";
      $("#b-submit").disabled = true;
      return;
    }
    ed.rows = res.data.rows;
    $("#b-editor-status").textContent = "";
    renderBatchPreview(res.data);
  }, 300);

  function openBatchEditor(stories) {
    S.bEditor = {stories: stories.slice(), rows: []};
    showTab("batches");
    showBatchBox("editor");
    $("#b-editor-stories").textContent = "Stories: " + stories.join(", ");
    clear($("#b-variants"));
    clear($("#b-preview thead"));
    clear($("#b-preview tbody"));
    $("#b-totals").textContent = "";
    $("#b-editor-status").textContent = "";
    $("#b-submit").disabled = true;
    addVariantCard();
    batchPreview();
  }

  async function submitBatch() {
    if (!S.bEditor) { return; }
    $("#b-submit").disabled = true;
    $("#b-editor-status").textContent = "submitting...";
    const res = await api("POST", "/api/batches", batchBody());
    if (res.status === 201) {
      S.bEditor = null;
      openBatch(res.data.batch.id);
      return;
    }
    $("#b-editor-status").textContent = errorText(res);
    $("#b-submit").disabled = false;
  }

  function promptCount() { $("#b-prompt-count").textContent = $("#b-prompt-text").value.length + " / 20000 characters"; }

  function closePromptDialog() {
    S.batchPrompt = null;
    show($("#b-prompt-dialog"), false);
  }

  function openPromptDialog(storyId, index) {
    const card = batchCards()[index];
    if (!card || !S.bEditor) { return; }
    const row = S.bEditor.rows.find(function (r) { return r.story_id === storyId; });
    const original = row && row.fields ? row.fields.narrative : "";
    S.batchPrompt = {card: card, storyId: storyId};
    $("#b-prompt-title").textContent = "Prompt for " + storyId + " in " + card.querySelector(".b-label").value;
    $("#b-prompt-text").value = card.perStory[storyId] !== undefined ? card.perStory[storyId] : original;
    promptCount();
    show($("#b-prompt-dialog"), true);
    $("#b-prompt-text").focus();
  }

  // --- the batch page (BF39)

  async function useBatchWorkspace(ws) {
    if (S.ws === ws) { return; }
    const select = $("#ws-select");
    if (!hasOption(select, ws)) { select.appendChild(el("option", {value: ws, text: ws})); }
    select.value = ws;
    await selectWorkspace(ws);
  }

  function setVideo(td, ws, path, original) {
    const box = td.querySelector(".b-video");
    if (!path) {
      if (original && !box.firstChild) { box.appendChild(el("span", {cls: "muted", text: "no movie.mp4 yet"})); }
      return;
    }
    if (box.querySelector("video")) { return; }
    clear(box).appendChild(el("video", {src: batchFileUrl(ws, path), controls: "", preload: "metadata",
                                        cls: original ? "b-original-video" : "b-fork-video"}));
  }

  function playRow(tr) {
    const videos = Array.prototype.slice.call(tr.querySelectorAll("video"));
    videos.forEach(function (v) {
      v.pause();
      v.currentTime = 0;
      v.muted = !v.classList.contains("b-original-video");
    });
    videos.forEach(function (v) {
      const playing = v.play();
      if (playing && playing.catch) { playing.catch(function () {}); }
    });
  }

  function chipText(cell, view) {
    const p = view.job && view.job.progress;
    if ((view.state === "starting" || view.state === "running") && p && p.phase) {
      return "Phase " + p.phase + ": " + (p.phase_title || "") +
        (p.panels_total ? ", panels " + p.panels_done + "/" + p.panels_total : "");
    }
    if (view.state === "queued" && view.job) { return "queued (#" + view.job.queue_position + ")"; }
    if (cell.reason && ["refused", "cancelled", "interrupted"].indexOf(view.state) >= 0) { return view.state + ": " + cell.reason; }
    return view.state;
  }

  function buildBatchGrid(rec) {
    clear($("#b-grid thead")).appendChild(el("tr", {}, [el("th", {text: "Story"}), el("th", {text: "Original"})].concat(
      rec.variants.map(function (v) { return el("th", {text: v.label}); }))));
    const body = clear($("#b-grid tbody"));
    S.batchGrid = {id: rec.id, originals: {}, cells: []};
    rec.stories.forEach(function (storyId, s) {
      const original = el("td", {}, [el("div", {cls: "b-video"})]);
      const play = button("Play row", function () { playRow(tr); });
      play.className = "b-play-row";
      const tr = el("tr", {}, [el("td", {}, [el("div", {text: storyId}), play]), original]);
      S.batchGrid.originals[storyId] = original;
      rec.variants.forEach(function (_v, m) {
        const td = el("td", {}, [el("div", {cls: "b-video"}), el("div", {cls: "b-info"})]);
        S.batchGrid.cells[s * rec.variants.length + m] = td;
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
  }

  function fillBatchCell(td, rec, cell, view) {
    setVideo(td, rec.workspace, view.movie, false);
    const info = clear(td.querySelector(".b-info"));
    info.appendChild(el("span", {cls: "chip", text: chipText(cell, view)}));
    if (cell.level) {
      info.appendChild(document.createTextNode(" "));
      info.appendChild(levelBadge(cell.level));
    }
    cell.diff.forEach(function (d) { info.appendChild(el("div", {cls: "muted", text: diffLine(d)})); });
    const actions = el("div", {cls: "row"});
    if (view.dir) {
      const open = button("Open story", async function () {
        await useBatchWorkspace(rec.workspace);
        openStory(cell.fork_id);
      });
      open.className = "b-open";
      actions.appendChild(open);
    }
    if (view.job) {
      const log = button("Log", function () { selectJob(cell.job_id); showTab("jobs"); });
      log.className = "b-log";
      actions.appendChild(log);
    }
    if (view.job && ["queued", "starting", "running"].indexOf(view.state) >= 0) {
      const cancel = button("Cancel", async function () {
        if (await askConfirm("Cancel the job of fork " + cell.fork_id + "?")) {
          await api("POST", "/api/jobs/" + cell.job_id + "/cancel", {});
          pollBatch();
        }
      });
      cancel.className = "b-cancel-cell";
      actions.appendChild(cancel);
    }
    info.appendChild(actions);
  }

  function renderBatchPage(data) {
    const rec = data.batch;
    $("#b-page-title").textContent = "Batch " + rec.id + " (" + rec.status + ")";
    show($("#b-resume"), rec.status === "interrupted");
    if (!S.batchGrid || S.batchGrid.id !== rec.id) { buildBatchGrid(rec); }
    rec.stories.forEach(function (storyId) {
      setVideo(S.batchGrid.originals[storyId], rec.workspace, data.view.originals[storyId], true);
    });
    rec.cells.forEach(function (cell, i) { fillBatchCell(S.batchGrid.cells[i], rec, cell, data.view.cells[i]); });
  }

  async function pollBatch() {
    if (S.stopped || !S.batchId) { return; }
    const id = S.batchId;
    const res = await api("GET", "/api/batches/" + id);
    if (id !== S.batchId || $("#b-page").hidden) { return; }
    if (res.status !== 200) {
      $("#b-page-status").textContent = errorText(res);
      return;
    }
    renderBatchPage(res.data);
  }

  async function openBatch(batchId) {
    S.batchId = batchId;
    S.batchGrid = null;
    showTab("batches");
    showBatchBox("page");
    clear($("#b-grid thead"));
    clear($("#b-grid tbody"));
    $("#b-page-title").textContent = "Batch " + batchId;
    $("#b-page-status").textContent = "";
    S.timers.batch = setInterval(pollBatch, BATCH_POLL_MS);
    await pollBatch();
  }

  function setupBatches() {
    const editor = $("#b-editor");
    editor.addEventListener("input", function () { batchPreview(); });
    editor.addEventListener("change", function () { batchPreview(); });
    editor.addEventListener("click", function (event) {
      if (event.target.tagName === "BUTTON" && event.target.id !== "b-submit" && event.target.id !== "b-discard") { batchPreview(); }
    });
    $("#b-add-variant").addEventListener("click", addVariantCard);
    $("#b-submit").addEventListener("click", submitBatch);
    $("#b-discard").addEventListener("click", function () { S.bEditor = null; loadBatches(); });
    $("#b-back").addEventListener("click", function () { S.batchId = null; loadBatches(); });
    $("#b-cancel").addEventListener("click", async function () {
      const id = S.batchId;
      if (!id || !(await askConfirm("Cancel batch " + id + "? Queued forks are removed; running jobs stop and keep their partial output."))) { return; }
      const res = await api("POST", "/api/batches/" + id + "/cancel", {});
      $("#b-page-status").textContent = res.status === 200 ? "cancelled" : errorText(res);
      pollBatch();
    });
    $("#b-resume").addEventListener("click", async function () {
      const res = await api("POST", "/api/batches/" + S.batchId + "/resume", {});
      $("#b-page-status").textContent = res.status === 200 ? res.data.pending + " fork(s) to submit again" : errorText(res);
      pollBatch();
    });
    $("#b-delete").addEventListener("click", async function () {
      const id = S.batchId;
      if (!id || !(await askConfirm("Delete the record of batch " + id + "? The forks stay as ordinary stories."))) { return; }
      const res = await api("DELETE", "/api/batches/" + id);
      if (res.status === 200) {
        S.batchId = null;
        loadBatches();
      } else {
        $("#b-page-status").textContent = errorText(res);
      }
    });
    $("#b-prompt-text").addEventListener("input", promptCount);
    $("#b-prompt-save").addEventListener("click", function () {
      if (S.batchPrompt) { S.batchPrompt.card.perStory[S.batchPrompt.storyId] = $("#b-prompt-text").value; }
      closePromptDialog();
      batchPreview();
    });
    $("#b-prompt-original").addEventListener("click", function () {
      if (S.batchPrompt) { delete S.batchPrompt.card.perStory[S.batchPrompt.storyId]; }
      closePromptDialog();
      batchPreview();
    });
    $("#b-prompt-close").addEventListener("click", closePromptDialog);
  }

  // --- characters (MU82) ---------------------------------------------------------------

  async function loadCharacters() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/characters" + wsQuery());
    S.characters = res.status === 200 ? res.data.characters : [];
    const body = clear($("#ch-list tbody"));
    const cast = $("#c-characters");
    const chosen = Array.prototype.map.call(cast.selectedOptions, function (o) { return o.value; });
    clear(cast);
    S.characters.forEach(function (c) {
      const row = el("tr", {data: {character: c.name}, cls: "clickable"}, c.invalid ?
        [el("td", {text: c.name}), el("td", {text: "invalid: " + c.invalid}), el("td"), el("td"), el("td")] :
        [el("td", {text: c.name}), el("td", {text: c.status}), el("td", {text: c.video ? "yes" : "no"}),
         el("td", {text: c.stills ? "yes" : "no"}), el("td", {text: c.phrase})]);
      row.addEventListener("click", function () { openCharacter(c.name); });
      body.appendChild(row);
      if (c.status === "trained") {
        const option = el("option", {value: c.name, text: c.name + " (" + c.phrase + ")"});
        option.selected = chosen.indexOf(c.name) >= 0;
        cast.appendChild(option);
      }
    });
  }

  async function openCharacter(name) {
    const res = await api("GET", "/api/characters/" + enc(name) + wsQuery());
    if (res.status !== 200) { $("#ch-status").textContent = (res.data && res.data.error) || "error"; return; }
    S.character = res.data;
    show($("#ch-detail"), true);
    $("#ch-regen-seed").value = String((res.data.character.seed + 1) % 2147483648);
    $("#ch-title").textContent = name + " (" + res.data.character.status + ")";
    const gallery = clear($("#ch-gallery"));
    if (res.data.dataset) {
      gallery.appendChild(el("img", {src: fileUrl(res.data.dataset.contact_sheet), alt: "contact sheet", cls: "sheet"}));
      res.data.dataset.stills.forEach(function (p) { gallery.appendChild(el("img", {src: fileUrl(p), alt: p})); });
    }
    show($("#ch-force"), res.data.face_problem === true && Boolean(res.data.last_create_fields));
    show($("#ch-train-form"), false);
    $("#ch-status").textContent = res.data.face_problem ? "the last create refused the seed face" : "";
    updateCharacterButtons();
  }

  function updateCharacterButtons() {
    gate($("#ch-create"), $("#ch-create-status"), ["stills"]);
    const status = S.character ? S.character.character.status : null;
    gate($("#ch-train"), $("#ch-train-reason"), ["render"]);
    if (status === "dataset") {
      $("#ch-train").disabled = true;
      $("#ch-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
  }

  async function createCharacter(force) {
    let body;
    if (force) {
      body = Object.assign({}, S.character.last_create_fields, {force: true});
    } else {
      let seed = null;
      const file = $("#ch-seed-file").files[0];
      try {
        if (file) { seed = await uploadFile(file); }
      } catch (err) {
        $("#ch-create-status").textContent = String(err.message);
        return;
      }
      body = {ws: S.ws, name: $("#ch-name").value.trim(), phrase: $("#ch-phrase").value.trim(),
              class_noun: textOrNull("#ch-class"), descriptor: file ? null : textOrNull("#ch-descriptor"),
              trigger: textOrNull("#ch-trigger"), seed: numberOrNull("#ch-seed"), seed_upload: seed, force: false};
    }
    body.ws = S.ws;
    const res = await api("POST", "/api/characters", body);
    const status = force ? $("#ch-status") : $("#ch-create-status");
    if (res.status === 201) {
      status.textContent = "queued job " + res.data.job.id;
      pollJobs();
    } else {
      status.textContent = (res.data && (res.data.errors || [res.data.error]).join("; ")) || ("http " + res.status);
    }
  }

  function setupCharacters() {
    $("#ch-create").addEventListener("click", function () { createCharacter(false); });
    $("#ch-force").addEventListener("click", function () { createCharacter(true); });
    $("#ch-accept").addEventListener("click", function () { show($("#ch-train-form"), true); });
    $("#ch-regenerate").addEventListener("click", async function () {
      const name = S.character.character.name;
      const seedText = $("#ch-regen-seed").value.trim();
      const seedValue = Number(seedText);
      const withSeed = seedText !== "";
      const confirmText = withSeed ? "Regenerate the dataset of " + name + " with seed " + seedText + "?"
                                  : "Regenerate the dataset of " + name + "?";
      if (!(await askConfirm(confirmText))) { return; }
      const res = await api("POST", "/api/characters/" + enc(name) + "/regenerate",
                            withSeed ? {ws: S.ws, seed: seedValue} : {ws: S.ws});
      $("#ch-status").textContent = res.status === 201 ? "queued job " + res.data.job.id : (res.data && res.data.error);
    });
    $("#ch-train").addEventListener("click", async function () {
      const name = S.character.character.name;
      const res = await api("POST", "/api/characters/" + enc(name) + "/train",
                            {ws: S.ws, video: $("#ch-train-video").checked, stills: $("#ch-train-stills").checked,
                             force: $("#ch-train-force").checked});
      $("#ch-train-reason").textContent = res.status === 201 ? "queued job " + res.data.job.id :
        ((res.data && (res.data.errors || [res.data.error]).join("; ")) || "");
    });
  }

  // --- locations (location library spec L4.4) ------------------------------------------

  function wordCount(text) { return String(text || "").split(/\s+/).filter(Boolean).length; }

  function firstWords(text, n) {
    const words = String(text || "").split(/\s+/).filter(Boolean);
    return words.slice(0, n).join(" ") + (words.length > n ? "..." : "");
  }

  function oneLine(selector) { return $(selector).value.replace(/\s+/g, " ").trim(); }

  function errorText(res) {
    return (res.data && (res.data.errors || [res.data.error]).join("; ")) || ("http " + res.status);
  }

  async function loadLocations() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/locations" + wsQuery());
    S.locations = res.status === 200 ? res.data.locations : [];
    const body = clear($("#lo-list tbody"));
    const pick = $("#c-locations");
    const chosen = Array.prototype.map.call(pick.selectedOptions, function (o) { return o.value; });
    clear(pick);
    S.locations.forEach(function (l) {
      const row = el("tr", {data: {location: l.name}, cls: "clickable"}, l.invalid ?
        [el("td", {text: l.name}), el("td", {text: "invalid: " + l.invalid}), el("td"), el("td"), el("td"), el("td")] :
        [el("td", {text: l.name}), el("td", {text: l.status}), el("td", {text: l.source}),
         el("td", {text: l.video ? "yes" : "no"}), el("td", {text: l.stills ? "yes" : "no"}),
         el("td", {text: l.description})]);
      row.addEventListener("click", function () { openLocation(l.name); });
      body.appendChild(row);
      if (l.status === "trained") {
        const option = el("option", {value: l.name, text: l.name + " (" + firstWords(l.description, 6) + ")"});
        option.selected = chosen.indexOf(l.name) >= 0;
        pick.appendChild(option);
      }
    });
    S.locationPick = Array.prototype.map.call(pick.selectedOptions, function (o) { return o.value; });
  }

  function onLocationPick() {
    const pick = $("#c-locations");
    if (pick.selectedOptions.length > 3) {
      Array.prototype.forEach.call(pick.options, function (o) {
        if (o.selected && S.locationPick.indexOf(o.value) < 0) { o.selected = false; }
      });
      $("#c-locations-note").textContent = "at most 3 locations";
    } else {
      $("#c-locations-note").textContent = "";
    }
    S.locationPick = Array.prototype.map.call(pick.selectedOptions, function (o) { return o.value; });
    preview();
  }

  function loraLossNote(loc) {
    return loc.status === "trained" && $("#lo-force").checked ? " Its LoRAs are deleted." : "";
  }

  async function openLocation(name) {
    const res = await api("GET", "/api/locations/" + enc(name) + wsQuery());
    if (res.status !== 200) { $("#lo-status").textContent = errorText(res); return; }
    S.location = res.data;
    const loc = res.data.location;
    $("#lo-force").checked = false;
    $("#lo-train-force").checked = false;
    show($("#lo-detail"), true);
    $("#lo-title").textContent = name + " (" + loc.status + ", " + loc.source + ")";
    const sheet = $("#lo-sheet");
    if (res.data.contact_sheet) { sheet.src = fileUrl(res.data.contact_sheet); }
    show(sheet, Boolean(res.data.contact_sheet));
    const byN = {};
    res.data.stills.forEach(function (p) {
      const m = /loc_(\d+)\.png$/.exec(p);
      if (m) { byN[Number(m[1])] = p; }
    });
    const stills = clear($("#lo-stills"));
    (res.data.manifest || []).forEach(function (item) {
      const parts = [];
      if (byN[item.n]) { parts.push(el("img", {src: fileUrl(byN[item.n]), alt: "still " + item.n})); }
      const people = item.people_visible === null ? "people -" : (item.people_visible ? "people" : "no people");
      parts.push(el("figcaption", {text: [item.source, item.match_score === null ? "score -" : "score " + item.match_score,
        people, item.caption || "", item.kept ? "kept" : "dropped: " + (item.reason || "")].join("; ")}));
      stills.appendChild(el("figure", {}, parts));
    });
    $("#lo-desc-edit").value = loc.description || "";
    $("#lo-desc-save").textContent = loc.source === "photos" ? "Save description" : "Regenerate with this description";
    show($("#lo-train-form"), false);
    const tests = clear($("#lo-tests"));
    if (res.data.tests.video_lora && res.data.tests.video_control) {
      [["video_lora", "with the LoRA"], ["video_control", "without (control)"]].forEach(function (t) {
        tests.appendChild(el("figure", {}, [el("video", {src: fileUrl(res.data.tests[t[0]]), controls: ""}),
          el("figcaption", {text: t[1]})]));
      });
    }
    $("#lo-status").textContent = "";
    updateLocationButtons();
  }

  function updateLocationButtons() {
    const words = wordCount($("#lo-description").value);
    const photos = $("#lo-photos").files.length;
    const okWords = words >= 15 && words <= 40;
    $("#lo-words").textContent = words + " words (15-40)";
    $("#lo-create").disabled = !/^[a-z][a-z0-9-]{1,23}$/.test($("#lo-name").value.trim()) || photos > 24
      || (words > 0 && !okWords) || (photos === 0 && !okWords);
    gate($("#lo-train"), $("#lo-train-reason"), ["render"]);
    if (S.location && S.location.location.status === "dataset") {
      $("#lo-train").disabled = true;
      $("#lo-train-reason").textContent = "fewer than 12 stills kept; regenerate the dataset";
    }
  }

  async function createLocation() {
    const status = $("#lo-create-status");
    const files = Array.prototype.slice.call($("#lo-photos").files);
    const uploads = [];
    try {
      for (let i = 0; i < files.length; i += 1) {
        status.textContent = "uploading photo " + (i + 1) + " of " + files.length + "...";
        uploads.push(await uploadFile(files[i]));
      }
    } catch (err) {
      status.textContent = String(err.message);
      return;
    }
    const res = await api("POST", "/api/locations", {ws: S.ws, name: $("#lo-name").value.trim(),
      description: oneLine("#lo-description") || null, photo_uploads: uploads, trigger: textOrNull("#lo-trigger"),
      seed: numberOrNull("#lo-seed"), force: false});
    status.textContent = res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
    if (res.status === 201) { pollJobs(); }
  }

  function setupLocations() {
    $("#lo-name").addEventListener("input", updateLocationButtons);
    $("#lo-description").addEventListener("input", updateLocationButtons);
    $("#lo-photos").addEventListener("change", updateLocationButtons);
    $("#lo-create").addEventListener("click", createLocation);
    $("#c-locations").addEventListener("change", onLocationPick);
    $("#lo-accept").addEventListener("click", function () { show($("#lo-train-form"), true); });
    $("#lo-desc-save").addEventListener("click", async function () {
      const loc = S.location.location;
      if (loc.source !== "photos" &&
          !(await askConfirm("Regenerate the dataset of " + loc.name + " with this description?" + loraLossNote(loc)))) { return; }
      const res = loc.source === "photos"
        ? await api("PATCH", "/api/locations/" + enc(loc.name), {ws: S.ws, description: oneLine("#lo-desc-edit")})
        : await api("POST", "/api/locations/" + enc(loc.name) + "/regenerate",
                    {ws: S.ws, description: oneLine("#lo-desc-edit"), force: $("#lo-force").checked});
      $("#lo-status").textContent = res.status === 200 ? "description saved"
        : res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
      if (res.status === 200) { await openLocation(loc.name); $("#lo-status").textContent = "description saved"; loadLocations(); }
      if (res.status === 201) { pollJobs(); }
    });
    $("#lo-regen").addEventListener("click", async function () {
      const name = S.location.location.name;
      if (!(await askConfirm("Regenerate the dataset of " + name + " with a new seed?" + loraLossNote(S.location.location)))) { return; }
      const res = await api("POST", "/api/locations/" + enc(name) + "/regenerate",
                            {ws: S.ws, new_seed: true, force: $("#lo-force").checked});
      $("#lo-status").textContent = res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
      if (res.status === 201) { pollJobs(); }
    });
    $("#lo-train").addEventListener("click", async function () {
      const name = S.location.location.name;
      const res = await api("POST", "/api/locations/" + enc(name) + "/train",
                            {ws: S.ws, video: $("#lo-train-video").checked, stills: $("#lo-train-stills").checked,
                             force: $("#lo-train-force").checked});
      $("#lo-train-reason").textContent = res.status === 201 ? "queued job " + res.data.job.id : errorText(res);
      if (res.status === 201) { pollJobs(); }
    });
    updateLocationButtons();
  }

  // --- actions (motion LoRAs, bin/action) ----------------------------------------------

  async function loadActions() {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/actions" + wsQuery());
    const actions = res.status === 200 ? res.data.actions : [];
    const body = clear($("#a-list tbody"));
    const pick = $("#c-actions");
    const chosen = Array.prototype.map.call(pick.selectedOptions, function (o) { return o.value; });
    clear(pick);
    actions.forEach(function (a) {
      const row = el("tr", {data: {action: a.name}, cls: "clickable"}, a.invalid ?
        [el("td", {text: a.name}), el("td", {text: "invalid: " + a.invalid}), el("td"), el("td")] :
        [el("td", {text: a.name}), el("td", {text: a.status}),
         el("td", {text: a.clips === null ? "-" : String(a.clips)}), el("td", {text: a.trigger})]);
      row.addEventListener("click", function () { openAction(a.name); });
      body.appendChild(row);
      if (a.status === "trained") {
        const option = el("option", {value: a.name, text: a.name + " (" + a.trigger + ")"});
        option.selected = chosen.indexOf(a.name) >= 0;
        pick.appendChild(option);
      }
    });
  }

  async function openAction(name) {
    const res = await api("GET", "/api/actions/" + enc(name) + wsQuery());
    if (res.status !== 200) { $("#a-status").textContent = (res.data && res.data.error) || "error"; return; }
    S.action = res.data;
    const a = res.data.action;
    show($("#a-detail"), true);
    $("#a-title").textContent = name + " (" + a.status + ")";
    $("#a-summary").textContent = "trigger: " + a.trigger + "\ndescriptor: " + a.descriptor
      + "\nidentity agnostic: " + a.identity_agnostic + "\ndefault strength: " + a.default_strength
      + (a.lora ? "\nLoRA: " + a.lora.path : "");
    const gallery = clear($("#a-gallery"));
    if (res.data.contact_sheet) {
      gallery.appendChild(el("img", {src: fileUrl(res.data.contact_sheet), alt: "contact sheet", cls: "sheet"}));
    }
    res.data.clips.forEach(function (p) { gallery.appendChild(el("video", {src: fileUrl(p), controls: "", preload: "metadata"})); });
    $("#a-status").textContent = "";
    show($("#a-regenerate"), Boolean(res.data.last_create_fields) && a.status !== "trained");
    gate($("#a-train"), $("#a-train-reason"), ["render"]);
    if (a.status === "trained") {
      $("#a-train").disabled = true;
      $("#a-train-reason").textContent = "already trained";
    } else if ((a.dataset || {}).clips < 8) {
      $("#a-train").disabled = true;
      $("#a-train-reason").textContent = "fewer than 8 clips; add clips and rebuild the dataset";
    }
  }

  async function submitAction(body, status) {
    body.ws = S.ws;
    const res = await api("POST", "/api/actions", body);
    if (res.status === 201) {
      status.textContent = "queued job " + res.data.job.id;
      pollJobs();
    } else {
      status.textContent = (res.data && (res.data.errors || [res.data.error]).join("; ")) || ("http " + res.status);
    }
  }

  function setupActions() {
    $("#a-create").addEventListener("click", function () {
      const clips = $("#a-clips").value.split("\n").map(function (l) { return l.trim(); })
        .filter(function (l) { return l; });
      submitAction({name: $("#a-name").value.trim(), trigger: $("#a-trigger").value.trim(),
                    descriptor: $("#a-descriptor").value.trim(), clips: clips,
                    performers: numberOrNull("#a-performers") || 0, force: $("#a-force").checked,
                    regenerate: false}, $("#a-create-status"));
    });
    $("#a-regenerate").addEventListener("click", async function () {
      const name = S.action.action.name;
      if (!(await askConfirm("Rebuild the dataset of " + name + " from its last clips?"))) { return; }
      submitAction(Object.assign({}, S.action.last_create_fields, {regenerate: true}), $("#a-status"));
    });
    $("#a-train").addEventListener("click", async function () {
      const name = S.action.action.name;
      if (!(await askConfirm("Train " + name + "? The story server is stopped for training and restarted after."))) { return; }
      const res = await api("POST", "/api/actions/" + enc(name) + "/train", {ws: S.ws});
      $("#a-train-reason").textContent = res.status === 201 ? "queued job " + res.data.job.id :
        ((res.data && (res.data.errors || [res.data.error]).join("; ")) || "");
      if (res.status === 201) { pollJobs(); }
    });
  }

  // --- LoRAs & Models (MU83) -----------------------------------------------------------

  // Shell-quote an argv element so a displayed command is copy-pasteable (multi-word
  // --use-when / --avoid-when / --description stay a single quoted argument).
  function shQuote(s) {
    s = String(s);
    return /^[A-Za-z0-9_@%+=:,./-]+$/.test(s) ? s : "'" + s.replace(/'/g, "'\\''") + "'";
  }

  function runText(run) {
    return "$ " + run.argv.map(shQuote).join(" ") + "\nexit " + run.exit_code + "\n" + run.stdout + run.stderr;
  }

  // The LoRA base-model dropdown lists only hosted models, filtered by target:
  // stills LoRAs attach to the Z-Image (zimage-hub) base, video LoRAs to the ltx-hub base.
  function fillLoraBaseModels() {
    const sel = $("#l-base-models");
    if (!sel) { return; }
    const target = $("#l-target").value;
    // Prefer the backend's curated LoRA-base list (excludes text encoders); fall back
    // to a hub filter if an older server didn't send it.
    let repos = S.loraBases && S.loraBases[target];
    if (!repos) {
      const hub = target === "stills" ? "zimage" : "ltx";
      repos = (S.models || []).filter(function (m) { return m.hub === hub; })
        .map(function (m) { return m.repo; }).sort();
    }
    const prev = Array.prototype.filter.call(sel.options, function (o) { return o.selected; })
      .map(function (o) { return o.value; });
    clear(sel);
    repos.forEach(function (repo) {
      const opt = el("option", {value: repo, text: repo});
      if (prev.indexOf(repo) >= 0) { opt.selected = true; }
      sel.appendChild(opt);
    });
    // default to selecting the first hosted base when nothing carried over
    if (sel.selectedOptions.length === 0 && sel.options.length) { sel.options[0].selected = true; }
  }

  async function loadCatalogTable(results) {
    if (!S.ws) { return; }
    const res = await api("GET", "/api/loras" + wsQuery());
    const body = clear($("#l-table tbody"));
    if (res.status !== 200) {
      $("#l-output").textContent = (res.data && res.data.error) || ("http " + res.status);
      return;
    }
    const verdicts = {};
    (results || []).forEach(function (r) {
      verdicts[r.id] = (r.ok ? "ok" : r.problems.join("; ")) + (r.warnings && r.warnings.length ? " | warning: " + r.warnings.join("; ") : "");
    });
    res.data.entries.forEach(function (e) {
      const remove = el("button", {type: "button", text: "Remove"});
      remove.addEventListener("click", async function () {
        if (!(await askConfirm("Remove " + e.id + " from the catalog? The file is not touched."))) { return; }
        const out = await api("POST", "/api/loras/remove", {ws: S.ws, id: e.id});
        $("#l-output").textContent = out.data && out.data.run ? runText(out.data.run) : (out.data && out.data.error);
        loadCatalogTable();
        loadCatalog();
      });
      const strength = e.default_strength + (e.strength_range ? " (" + e.strength_range.join("-") + ")" : "");
      body.appendChild(el("tr", {}, [el("td", {text: e.id}), el("td", {text: e.kind}), el("td", {text: e.target}),
        el("td", {text: strength}), el("td", {text: (e.triggers || []).join(", ")}),
        el("td", {text: (e.base_models || []).join(", ")}), el("td", {text: verdicts[e.id] || ""}),
        el("td", {}, [remove])]));
    });
  }

  function splitList(selector) {
    return $(selector).value.split(",").map(function (v) { return v.trim(); }).filter(Boolean);
  }

  function setupLoras() {
    $("#m-dl-go").addEventListener("click", function () {
      downloadModel($("#m-dl-repo").value, $("#m-dl-hub").value, $("#m-dl-status"));
    });
    $("#l-target").addEventListener("change", fillLoraBaseModels);
    $("#l-verify-all").addEventListener("click", async function () {
      const res = await api("POST", "/api/loras/verify", {ws: S.ws, ids: []});
      if (res.data && res.data.run) {
        $("#l-output").textContent = runText(res.data.run);
        loadCatalogTable(res.data.results);
      } else {
        $("#l-output").textContent = (res.data && res.data.error) || ("http " + res.status);
      }
    });
    $("#l-add").addEventListener("click", async function () {
      const body = {ws: S.ws, path: $("#l-path").value.trim(), id: $("#l-id").value.trim(),
        kind: $("#l-kind").value, target: $("#l-target").value,
        base_models: Array.prototype.map.call($("#l-base-models").selectedOptions, function (o) { return o.value; }),
        triggers: splitList("#l-triggers"), description: $("#l-description").value.trim(),
        use_when: $("#l-use-when").value.trim(), avoid_when: $("#l-avoid-when").value.trim(),
        default_strength: Number($("#l-default-strength").value),
        strength_range: [Number($("#l-range-lo").value), Number($("#l-range-hi").value)],
        rank: numberOrNull("#l-rank"), alpha: numberOrNull("#l-alpha"),
        no_arch_check: $("#l-no-arch-check").checked};
      const res = await api("POST", "/api/loras", body);
      $("#l-output").textContent = res.data && res.data.run ? runText(res.data.run) : (res.data && res.data.error);
      loadCatalogTable();
      loadCatalog();
    });
  }

  // --- jobs (MU84) ---------------------------------------------------------------------

  function jobLabel(job) {
    return job.story_id || job.character || (job.kind === "smoke" ? "smoke render" : "-");
  }

  function duration(job) {
    const a = utcSeconds(job.started);
    const b = utcSeconds(job.ended);
    if (a === null || b === null) { return "-"; }
    const s = Math.round(b - a);
    return s >= 60 ? Math.floor(s / 60) + "m " + (s % 60) + "s" : s + "s";
  }

  function renderProgress(job) {
    const box = clear($("#j-progress"));
    const p = job.progress;
    if (!p) { return; }
    if (p.phases) {
      const phases = el("div", {cls: "phases"});
      p.phases.forEach(function (ph) { phases.appendChild(el("span", {cls: ph === p.phase ? "phase current" : "phase", text: ph})); });
      box.appendChild(phases);
      const parts = [];
      if (p.phase_title) { parts.push("phase " + p.phase + ": " + p.phase_title); }
      if (p.rewrite) { parts.push("rewrite " + p.rewrite[0] + " of " + p.rewrite[1]); }
      if (p.redo) { parts.push("redo panels " + p.redo); }
      if (p.panels_total) { parts.push("panels " + p.panels_done + "/" + p.panels_total); }
      if (p.stills) { parts.push("stills " + p.stills.count + "/" + p.stills.expected); }
      if (p.wrap_up) { parts.push("wrapping up"); }
      box.appendChild(el("div", {text: parts.join(" - ")}));
      const panels = el("div", {cls: "panels"});
      Object.keys(p.panels).forEach(function (k) {
        const v = p.panels[k];
        panels.appendChild(el("span", {cls: "panel-state " + v.state,
          text: k + ": " + v.state + (v.reused ? " (reused)" : "") + (v.reason ? " (" + v.reason + ")" : ""),
          title: v.detail || ""}));
      });
      box.appendChild(panels);
    } else {
      box.appendChild(el("div", {text: job.kind + (p.elapsed_s !== null ? " - " + p.elapsed_s + " s" : "") +
        (p.face_problem ? " - the seed face was refused" : "")}));
    }
    box.appendChild(el("div", {cls: "muted", text: p.last_line || ""}));
  }

  function headerJob(running) {
    if (!running) { $("#header-job").textContent = "no job running"; return; }
    const p = running.progress || {};
    let text = "running " + running.id + " (" + jobLabel(running) + ")";
    if (p.phase) { text += " phase " + p.phase; }
    if (p.panels_total) { text += " " + p.panels_done + "/" + p.panels_total; }
    $("#header-job").textContent = text;
  }

  async function jobAction(path, method, body) {
    const res = await api(method || "POST", path, body === undefined ? {} : body);
    if (res.status >= 400) { banner((res.data && res.data.error) || ("http " + res.status)); }
    await pollJobs();
    return res;
  }

  function button(text, handler) {
    const b = el("button", {type: "button", text: text});
    b.addEventListener("click", handler);
    return b;
  }

  async function deleteJob(job) {
    if (!(await askConfirm("Delete job " + job.id + " and its log? Story outputs are kept."))) { return; }
    let res = await api("DELETE", "/api/jobs/" + job.id);
    const live = function (r) { return r.status === 409 && r.data && /still has a live process group/.test(r.data.error || ""); };
    if (live(res)) {
      if (await askConfirm("Its processes are still running and may hold GPU memory. Delete the record anyway and unblock the queue?")) {
        res = await api("DELETE", "/api/jobs/" + job.id, {confirm: true});
      }
    }
    if (res.status >= 400) {
      if (!live(res)) { banner((res.data && res.data.error) || ("http " + res.status)); }
    } else if (S.selectedJob === job.id) {
      selectJob(null);
    }
    await pollJobs();
  }

  function selectJob(id) {
    if (S.selectedJob !== id) {
      S.selectedJob = id;
      S.logOffset = 0;
      S.logBuffer = "";
      S.logLines = [];
      $("#j-log").textContent = "";
    }
    $("#j-log-title").textContent = id || "";
    loadJobTraces(id);
  }

  async function pollJobs() {
    if (S.stopped) { return; }
    if (S.timers.jobsBusy) { S.timers.jobsDirty = true; return; }
    S.timers.jobsBusy = true;
    try {
      do {
        S.timers.jobsDirty = false;
        await pollJobsOnce();
      } while (S.timers.jobsDirty && !S.stopped);
    } finally {
      S.timers.jobsBusy = false;
    }
  }

  async function pollJobsOnce() {
    const res = await api("GET", "/api/jobs");
    if (res.status !== 200) { return; }
    const jobs = res.data;
    headerJob(jobs.running);
    $("#header-queue").textContent = "queue: " + jobs.queued.length;
    const blocked = $("#j-blocked");
    if (jobs.blocked_by) {
      blocked.textContent = "Queue waiting: lost job " + jobs.blocked_by.job + " still has a live process group " +
        jobs.blocked_by.pgid + ". Kill orphan or Delete that job to unblock the queue.";
      blocked.hidden = false;
    } else {
      blocked.textContent = "";
      blocked.hidden = true;
    }
    const running = $("#j-running");
    if (jobs.running) {
      running.textContent = jobs.running.id + " " + jobs.running.kind + " " + jobLabel(jobs.running) + " - " +
        jobs.running.state + " - " + jobs.running.command;
      renderProgress(jobs.running);
      show($("#j-cancel"), true);
      $("#j-cancel").dataset.jobId = jobs.running.id;
      if (!S.selectedJob) { selectJob(jobs.running.id); }
    } else {
      running.textContent = "no job running";
      clear($("#j-progress"));
      show($("#j-cancel"), false);
    }
    const queue = clear($("#j-queue tbody"));
    jobs.queued.forEach(function (job) {
      queue.appendChild(el("tr", {data: {jobId: job.id}}, [el("td", {text: String(job.queue_position)}),
        el("td", {text: job.id}), el("td", {text: job.kind}), el("td", {text: jobLabel(job)}),
        el("td", {}, [button("Up", function () { jobAction("/api/queue/move", "POST", {id: job.id, direction: "up"}); }),
                      button("Down", function () { jobAction("/api/queue/move", "POST", {id: job.id, direction: "down"}); }),
                      button("Cancel", async function () {
                        if (await askConfirm("Cancel queued job " + job.id + "?")) { jobAction("/api/jobs/" + job.id + "/cancel"); }
                      })])]));
    });
    const past = clear($("#j-history tbody"));
    jobs.history.forEach(function (job) {
      const actions = el("td");
      actions.appendChild(button("Log", function () { selectJob(job.id); }));
      if (job.story_id) { actions.appendChild(button("Story", function () { openStory(job.story_id); })); }
      actions.appendChild(button("Delete", function () { deleteJob(job); }));
      const row = el("tr", {data: {jobId: job.id}}, [el("td", {text: job.id}), el("td", {text: job.kind}),
        el("td", {text: job.state + (job.error ? " (" + job.error + ")" : ""), cls: "state-" + job.state}),
        el("td", {text: duration(job)}), el("td", {text: job.exit_code === null ? "-" : String(job.exit_code)}),
        el("td", {text: jobLabel(job)}), actions]);
      past.appendChild(row);
      if (job.state === "lost") { addOrphanButton(job.id, actions); }
    });
    await pollLog();
  }

  async function addOrphanButton(id, cell) {
    const res = await api("GET", "/api/jobs/" + id);
    if (res.status !== 200 || !res.data.orphan || !res.data.orphan.alive) { return; }
    cell.appendChild(button("Kill orphan", async function () {
      if (await askConfirm("Send SIGKILL to process group " + res.data.orphan.pgid + " left by job " + id + "?")) {
        jobAction("/api/jobs/" + id + "/kill-orphan", "POST", {confirm: true});
      }
    }));
  }

  function appendLog(text) {
    const data = S.logBuffer + text;
    const parts = data.split("\n");
    S.logBuffer = parts.pop();
    parts.forEach(function (line) {
      const cut = line.replace(/\r+$/, "");
      S.logLines.push(cut.slice(cut.lastIndexOf("\r") + 1));
    });
    if (S.logLines.length > 5000) { S.logLines = S.logLines.slice(-5000); }
    const tail = S.logBuffer.slice(S.logBuffer.lastIndexOf("\r") + 1);
    $("#j-log").textContent = S.logLines.join("\n") + (tail ? "\n" + tail : "");
  }

  async function pollLog() {
    if (S.stopped || !S.selectedJob || S.timers.logBusy) { return; }
    S.timers.logBusy = true;
    try {
      const id = S.selectedJob;
      const res = await api("GET", "/api/jobs/" + id + "/log?offset=" + S.logOffset);
      if (res.status === 200 && id === S.selectedJob) {
        S.logOffset = res.data.next_offset;
        if (res.data.text) {
          const node = $("#j-log");
          const atEnd = node.scrollTop + node.clientHeight >= node.scrollHeight - 4;
          appendLog(res.data.text);
          if (atEnd) { node.scrollTop = node.scrollHeight; }
        }
      }
    } finally {
      S.timers.logBusy = false;
    }
  }

  async function loadJobTraces(id) {
    const list = clear($("#j-traces"));
    if (!id) { return; }
    const job = await api("GET", "/api/jobs/" + id);
    if (job.status !== 200 || !job.data.window.start) { list.appendChild(el("li", {text: "the job has not started"})); return; }
    const start = utcSeconds(job.data.window.start);
    const end = job.data.window.end ? utcSeconds(job.data.window.end) : Date.now() / 1000;
    const res = await api("GET", "/api/traces/recent?agent=all&n=100");
    if (res.status !== 200) { return; }
    res.data.traces.filter(function (t) { return t.start >= start && t.start <= end; }).forEach(function (t) {
      const item = el("li", {cls: "clickable", text: localTime(t.start) + " " + t.kind + " " + t.name + " " + t.status});
      item.addEventListener("click", function () { showTab("traces"); openTrace(t.trace_id, t.seen_on[0]); });
      list.appendChild(item);
    });
    if (!list.firstChild) { list.appendChild(el("li", {text: "no trace started during this job"})); }
  }

  function setupJobs() {
    $("#j-cancel").addEventListener("click", async function () {
      const id = $("#j-cancel").dataset.jobId;
      if (await askConfirm("Cancel running job " + id + "? Its process tree is stopped.")) { jobAction("/api/jobs/" + id + "/cancel"); }
    });
  }

  // --- traces (MU85) -------------------------------------------------------------------

  async function loadTraceAgents() {
    const res = await api("GET", "/api/traces/agents");
    if (res.status !== 200) { return; }
    S.agents = res.data.agents;
    const select = $("#t-agent");
    const current = select.value;
    clear(select).appendChild(el("option", {value: "all", text: "all"}));
    S.agents.forEach(function (a) { select.appendChild(el("option", {value: a.id, text: a.id + (a.url ? "" : " (" + a.error + ")")})); });
    select.value = current || "all";
  }

  function traceFilters(t) {
    const agent = $("#t-agent").value;
    const status = $("#t-filter-status").value.trim();
    const kind = $("#t-filter-kind").value;
    const name = $("#t-filter-name").value.trim();
    return (agent === "all" || t.agents.indexOf(agent) >= 0) && (!status || t.status === status) &&
      (!kind || t.kind === kind) && (!name || t.name.indexOf(name) >= 0);
  }

  function renderRecent() {
    const body = clear($("#t-recent tbody"));
    S.recent.filter(traceFilters).forEach(function (t) {
      const row = el("tr", {data: {traceId: t.trace_id}, cls: "clickable"}, [el("td", {text: localTime(t.start)}),
        el("td", {text: t.kind + " " + t.name}), el("td", {text: t.agents.join(", ")}),
        el("td", {text: (t.dur_ms / 1000).toFixed(1) + " s"}), el("td", {text: t.status}), el("td", {text: String(t.spans)})]);
      row.addEventListener("click", function () { openTrace(t.trace_id, t.seen_on[0]); });
      body.appendChild(row);
    });
  }

  async function loadRecent() {
    S.recentSeq += 1;
    const seq = S.recentSeq;
    const res = await api("GET", "/api/traces/recent?agent=all&n=100");
    if (seq !== S.recentSeq) { return; }
    const errors = clear($("#t-errors"));
    if (res.status !== 200) { errors.appendChild(el("li", {text: (res.data && res.data.error) || "error"})); return; }
    S.recent = res.data.traces;
    res.data.errors.forEach(function (e) { errors.appendChild(el("li", {text: e.agent + ": " + e.error})); });
    const kinds = $("#t-filter-kind");
    if (kinds.options.length === 1) {
      ["turn", "model", "tool", "delegate", "run", "agent"].forEach(function (k) { kinds.appendChild(el("option", {value: k, text: k})); });
    }
    renderRecent();
  }

  function traceOrder(records) {
    const byId = {};
    records.forEach(function (r) { byId[r.span_id] = r; });
    const children = {};
    const roots = [];
    const orphans = [];
    records.forEach(function (r) {
      if (r.parent_span_id === null) { roots.push(r); }
      else if (byId[r.parent_span_id]) { (children[r.parent_span_id] = children[r.parent_span_id] || []).push(r); }
      else { orphans.push(r); }
    });
    function key(a, b) { return a.start - b.start || (a.span_id < b.span_id ? -1 : (a.span_id > b.span_id ? 1 : 0)); }
    roots.sort(key);
    orphans.sort(key);
    Object.keys(children).forEach(function (k) { children[k].sort(key); });
    const out = [];
    const seen = {};
    function walk(r, depth) {
      if (seen[r.span_id]) { return; }
      seen[r.span_id] = true;
      out.push({record: r, depth: depth});
      (children[r.span_id] || []).forEach(function (c) { walk(c, depth + 1); });
    }
    roots.forEach(function (r) { walk(r, 0); });
    orphans.forEach(function (r) { walk(r, 1); });
    records.slice().sort(key).forEach(function (r) { walk(r, 0); });
    return out;
  }

  function renderTrace(view) {
    S.trace = view;
    show($("#t-view"), true);
    const result = view.result;
    const records = result.records;
    const agents = Array.from(new Set(records.map(function (r) { return r.agent; }))).sort();
    const t0 = records.length ? Math.min.apply(null, records.map(function (r) { return r.start; })) : 0;
    const tEnd = records.length ? Math.max.apply(null, records.map(function (r) { return r.start + r.dur_ms / 1000; })) : 0;
    const total = Math.max(tEnd - t0, 0.001);
    const root = records.find(function (r) { return r.parent_span_id === null; });
    $("#t-header").textContent = "trace " + result.trace_id;
    const meta = ["start " + localTime(records.length ? t0 : null),
                  "duration " + (root ? (root.dur_ms / 1000).toFixed(1) + " s" : "-"),
                  "agents " + (agents.join(", ") || "none")];
    result.missing.forEach(function (m) { meta.push("missing " + m.agent + ": " + m.reason); });
    result.truncated.forEach(function (t) { meta.push("truncated " + t.agent + " (" + t.count + ")"); });
    if (view.skew.length) { meta.push("clock skew: " + view.skew.length + " span(s) start before their parent"); }
    $("#t-meta").textContent = meta.join(" | ");
    const fall = clear($("#t-waterfall"));
    traceOrder(records).forEach(function (item) {
      const r = item.record;
      const bar = el("div", {cls: "bar agent-" + (agents.indexOf(r.agent) % 8)});
      bar.style.marginLeft = ((r.start - t0) / total * 100).toFixed(3) + "%";
      bar.style.width = (Math.max(r.dur_ms / 1000 / total, 0.002) * 100).toFixed(3) + "%";
      const label = el("div", {cls: "label", text: r.kind + " " + r.name + " @" + r.agent + " " + (r.dur_ms / 1000).toFixed(2) + " s"});
      label.style.paddingLeft = (item.depth * 1.2) + "em";
      const row = el("div", {cls: "span-row" + (view.skew.indexOf(r.span_id) >= 0 ? " skewed" : ""), data: {spanId: r.span_id}},
                     [label, el("div", {cls: "track"}, [bar]), el("span", {cls: "badge status-" + r.status, text: r.status})]);
      row.addEventListener("click", function () {
        const lines = Object.keys(r).filter(function (k) { return k !== "attrs"; }).map(function (k) { return k + ": " + JSON.stringify(r[k]); });
        Object.keys(r.attrs).forEach(function (k) { lines.push("attrs." + k + ": " + JSON.stringify(r.attrs[k])); });
        $("#t-attrs").textContent = lines.join("\n");
      });
      fall.appendChild(row);
    });
    $("#t-attrs").textContent = "";
    $("#t-text").textContent = view.text || "";
    $("#t-status").textContent = "";
  }

  async function openTrace(traceId, agent) {
    S.traceAgent = agent;
    const res = await api("GET", "/api/traces/" + traceId + "?agent=" + enc(agent) + "&format=text");
    if (res.status === 200) { renderTrace(res.data); }
    else { $("#t-errors").appendChild(el("li", {text: (res.data && res.data.error) || ("http " + res.status)})); }
  }

  async function loadSaved() {
    const res = await api("GET", "/api/traces/saved");
    const list = clear($("#t-saved"));
    if (res.status !== 200) { return; }
    res.data.saved.forEach(function (s) {
      const item = el("li", {text: s.trace_id + " " + (s.invalid ? "(invalid)" : (s.agent + " " + s.saved_at + " " + s.spans + " spans")) + " "});
      if (!s.invalid) {
        item.appendChild(button("View", async function () {
          const view = await api("GET", "/api/traces/saved/" + s.trace_id);
          if (view.status === 200) { S.traceAgent = view.data.agent; renderTrace(view.data); }
        }));
      }
      item.appendChild(button("Delete", async function () {
        if (await askConfirm("Delete saved trace " + s.trace_id + "?")) {
          await api("DELETE", "/api/traces/saved/" + s.trace_id);
          loadSaved();
        }
      }));
      list.appendChild(item);
    });
  }

  function scheduleTraces() {
    if (S.stopped || !$("#t-auto").checked) { return; }
    S.timers.traces = setTimeout(async function () {
      S.timers.traces = null;
      await loadRecent();
      scheduleTraces();
    }, 5000);
  }

  function setupTraces() {
    $("#t-refresh").addEventListener("click", function () { loadTraceAgents(); loadRecent(); loadSaved(); });
    ["#t-agent", "#t-filter-status", "#t-filter-kind", "#t-filter-name"].forEach(function (sel) {
      $(sel).addEventListener("input", renderRecent);
      $(sel).addEventListener("change", renderRecent);
    });
    $("#t-auto").addEventListener("change", function () {
      if (S.timers.traces) { clearTimeout(S.timers.traces); S.timers.traces = null; }
      scheduleTraces();
    });
    $("#t-save").addEventListener("click", async function () {
      const res = await api("POST", "/api/traces/" + S.trace.result.trace_id + "/save", {agent: S.traceAgent});
      $("#t-status").textContent = res.status === 200 ? "saved to " + res.data.path : ((res.data && res.data.error) || "");
      loadSaved();
    });
    $("#t-download").addEventListener("click", function () {
      const blob = new Blob([JSON.stringify(S.trace.result, null, 2)], {type: "application/json"});
      const url = URL.createObjectURL(blob);
      const link = el("a", {href: url, download: "trace-" + S.trace.result.trace_id + ".json"});
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
  }

  // --- start ---------------------------------------------------------------------------

  async function start() {
    readToken();
    TABS.forEach(function (tab) { $("#tab-" + tab).addEventListener("click", function () { showTab(tab); }); });
    $("#ws-select").addEventListener("change", function () { selectWorkspace($("#ws-select").value); });
    $("#ws-typed-use").addEventListener("click", useTypedPath);
    $("#badge-refresh").addEventListener("click", function () { loadHost(true); });
    $("#banner-dismiss").addEventListener("click", function () { banner(""); });
    setupCompose();
    setupSmoke();
    setupStories();
    setupBatches();
    setupCharacters();
    setupLocations();
    setupActions();
    setupLoras();
    setupJobs();
    setupTraces();
    await loadHost(false);
    await loadWorkspaces();
    updateComposeButtons();
    await pollJobs();
    if (S.stopped) { return; }
    S.timers.jobs = setInterval(pollJobs, 2000);
    S.timers.log = setInterval(pollLog, 1000);
    S.timers.host = setInterval(function () {
      if (!S.stopped && capability("render").ok === null) { loadHost(false); }
    }, 3000);
  }

  document.addEventListener("DOMContentLoaded", start);
})();
