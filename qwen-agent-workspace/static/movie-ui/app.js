/* movie-ui page (movie-ui spec Section 12, docs/superpowers/specs/2026-10-19-movie-ui-design.md).
   Vanilla ES2017, no modules, no eval; every confirmation uses the in-page #confirm dialog;
   every text from the server is inserted with textContent. */
"use strict";

(function () {
  const TOKEN_KEY = "movie-ui-token";
  const STILLS_MODEL = "Tongyi-MAI/Z-Image-Turbo";
  const S = {
    token: null, host: null, ws: null, workspaces: [], options: null, catalog: {video: [], stills: []},
    characters: [], seedUpload: null, composeAction: "story", story: null, character: null, selectedJob: null, logOffset: 0,
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
    ["jobs", "log", "host"].forEach(function (name) {
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

  function askConfirm(text) {
    return new Promise(function (resolve) {
      const dialog = $("#confirm");
      $("#confirm-text").textContent = text;
      show(dialog, true);
      function done(answer) {
        show(dialog, false);
        $("#confirm-yes").removeEventListener("click", yes);
        $("#confirm-no").removeEventListener("click", no);
        resolve(answer);
      }
      function yes() { done(true); }
      function no() { done(false); }
      $("#confirm-yes").addEventListener("click", yes);
      $("#confirm-no").addEventListener("click", no);
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
    await Promise.all([loadCatalog(), loadCharacters(), loadStories(), loadModels()]);
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
    if (!$("#c-model").value) { $("#c-model").value = d.model; }
    if (!$("#c-gemma").value) { $("#c-gemma").value = d.gemma; }
  }

  // --- tabs (MU79) ---------------------------------------------------------------------

  const TABS = ["compose", "stories", "characters", "loras", "jobs", "traces"];

  function showTab(name) {
    TABS.forEach(function (tab) {
      $("#tab-" + tab).classList.toggle("active", tab === name);
      show($("#panel-" + tab), tab === name);
    });
    if (name === "stories") { loadStories(); }
    if (name === "characters") { loadCharacters(); }
    if (name === "traces") { loadTraceAgents(); loadRecent(); loadSaved(); }
    if (name === "loras") { loadCatalogTable(); loadModels(); }
  }

  // --- compose (MU80) ------------------------------------------------------------------

  function loraRow(target, item) {
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
    $(target === "video" ? "#c-video-loras" : "#c-stills-loras").appendChild(row);
    sync();
  }

  function collectLoras(target) {
    const entries = S.catalog[target];
    const rows = document.querySelectorAll((target === "video" ? "#c-video-loras" : "#c-stills-loras") + " .lora-row");
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
      model: textOrNull("#c-model"), gemma: supported.gemma === false ? null : textOrNull("#c-gemma"),
      story_model: textOrNull("#c-story-model"),
      auto_lora: $("#c-auto-lora").checked,
      video_loras: collectLoras("video"), stills_loras: collectLoras("stills"),
      characters: Array.prototype.map.call($("#c-characters").selectedOptions, function (o) { return o.value; }),
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
      showTab("jobs");
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
    gate($("#c-write-story"), $("#c-write-story-reason"), ["story_server"]);
    gate($("#c-smoke"), $("#c-smoke-reason"), ["render"]);
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
    $("#c-width").value = f.width || "";
    $("#c-height").value = f.height || "";
    S.seedUpload = f.seed_upload || null;
    $("#c-res-seed").checked = Boolean(S.seedUpload);
    $("#c-res-size").checked = !S.seedUpload;
    $("#c-mode").value = f.mode || "chained";
    $("#c-model").value = f.model || "";
    $("#c-gemma").value = f.gemma || "";
    $("#c-story-model").value = f.story_model || "";
    $("#c-auto-lora").checked = f.auto_lora !== false;
    clear($("#c-video-loras"));
    clear($("#c-stills-loras"));
    (f.video_loras || []).forEach(function (item) { loraRow("video", item); });
    (f.stills_loras || []).forEach(function (item) { loraRow("stills", item); });
    Array.prototype.forEach.call($("#c-characters").options, function (o) {
      o.selected = (f.characters || []).indexOf(o.value) >= 0;
    });
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
    $("#c-copy").addEventListener("click", function () {
      navigator.clipboard.writeText($("#c-command").textContent);
    });
    $("#c-validate").addEventListener("click", validate);
    $("#c-write-story").addEventListener("click", function () { S.composeAction = "story"; submit(composeFields("story")); });
    $("#c-run-all").addEventListener("click", function () { S.composeAction = "movie"; submit(composeFields("movie")); });
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
    const list = clear($("#c-model-list"));
    const body = clear($("#m-table tbody"));
    res.data.models.forEach(function (m) {
      if (m.hub === "ltx") { list.appendChild(el("option", {value: m.repo})); }
      body.appendChild(el("tr", {}, [el("td", {text: m.hub}), el("td", {text: m.repo}),
        el("td", {text: m.intact ? "yes" : "no", cls: m.intact ? "ok" : "bad"}),
        el("td", {text: m.problems.join("; ")}), el("td", {text: sizeText(m.bytes)})]));
    });
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
    const body = clear($("#s-list tbody"));
    if (res.status !== 200) { return; }
    res.data.stories.forEach(function (st) {
      const checks = st.checks ? st.checks.hard + " hard, " + st.checks.advisory + " advisory" +
        (st.checks.verdict ? " (" + st.checks.verdict + ")" : "") : "-";
      const row = el("tr", {data: {storyId: st.id}, cls: "clickable"}, [
        el("td", {text: st.id}), el("td", {text: st.story_md ? "yes" : "no"}), el("td", {text: checks}),
        el("td", {text: String(st.stills)}), el("td", {text: String(st.clips)}),
        el("td", {text: st.movie ? "yes" : "no"}), el("td", {text: new Date(st.mtime).toLocaleString()})]);
      row.addEventListener("click", function () { openStory(st.id); });
      body.appendChild(row);
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
    $("#s-action-status").textContent = res.data.last_fields ? "" : "no earlier job for this story: Render opens Compose with only its ID";
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
    const panels = st.checks && st.checks.panels ? st.checks.panels : (S.options ? S.options.defaults.panels : 15);
    return {story_id: st.id, panels: panels, action: action};
  }

  function setupStories() {
    $("#s-save").addEventListener("click", saveStory);
    $("#s-reload").addEventListener("click", function () { openStory(S.story.id); });
    $("#s-render").addEventListener("click", function () {
      fillCompose(storyFields("movie"));
      showTab("compose");
    });
    $("#s-regenerate").addEventListener("click", async function () {
      if (!S.story.last_fields) { $("#s-action-status").textContent = "compose this story once before regenerating it"; return; }
      if (!(await askConfirm("Regenerate story.md of " + S.story.id + "? The current one is replaced."))) { return; }
      const res = await submit(storyFields("regenerate"));
      $("#s-action-status").textContent = res.status === 201 ? "queued" : "refused; see Compose checks";
    });
    $("#s-redo").addEventListener("click", async function () {
      if (!S.story.last_fields) { $("#s-action-status").textContent = "compose this story once before a redo"; return; }
      const panels = $("#s-redo-panels").value.split(",").map(function (v) { return Number(v.trim()); })
        .filter(function (n) { return Number.isInteger(n) && n > 0; });
      const res = await submit(Object.assign(storyFields("redo"), {redo: panels, mode: "shots"}));
      $("#s-action-status").textContent = res.status === 201 ? "queued" : "refused; see Compose checks";
    });
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
      if (!(await askConfirm("Regenerate the dataset of " + name + "?"))) { return; }
      const res = await api("POST", "/api/characters/" + enc(name) + "/regenerate", {ws: S.ws});
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

  // --- LoRAs & Models (MU83) -----------------------------------------------------------

  function runText(run) {
    return "$ " + run.argv.join(" ") + "\nexit " + run.exit_code + "\n" + run.stdout + run.stderr;
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
    (results || []).forEach(function (r) { verdicts[r.id] = r.ok ? "ok" : r.problems.join("; "); });
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
        kind: $("#l-kind").value, target: $("#l-target").value, base_models: splitList("#l-base-models"),
        triggers: splitList("#l-triggers"), description: $("#l-description").value.trim(),
        use_when: $("#l-use-when").value.trim(), avoid_when: $("#l-avoid-when").value.trim(),
        default_strength: Number($("#l-default-strength").value),
        strength_range: [Number($("#l-range-lo").value), Number($("#l-range-hi").value)],
        rank: numberOrNull("#l-rank"), alpha: numberOrNull("#l-alpha")};
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
    setupCharacters();
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
