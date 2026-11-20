/* Behind the Code - progress tracking and small helpers.
   Progress lives only in this browser (localStorage). The page works without it. */
(function () {
  var KEY = "behind-the-code:v1";

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; }
  }
  function save(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* storage unavailable */ }
  }

  var state = load();
  state.checks = state.checks || {};
  state.notes = state.notes || {};
  state.totals = state.totals || {};

  var chapter = document.body.getAttribute("data-chapter");
  var boxes = Array.prototype.slice.call(document.querySelectorAll("input[type=checkbox][data-id]"));
  var notes = Array.prototype.slice.call(document.querySelectorAll("textarea[data-id]"));

  function refresh() {
    var done = boxes.filter(function (b) { return b.checked; }).length;
    var bar = document.querySelector(".progress-bar > span");
    var text = document.querySelector(".progress-text");
    if (bar) bar.style.width = (boxes.length ? Math.round((done / boxes.length) * 100) : 0) + "%";
    if (text) text.textContent = done + " / " + boxes.length;
    boxes.forEach(function (b) {
      var ex = b.closest(".exercise");
      if (ex && b.closest(".ex-done")) ex.classList.toggle("done", b.checked);
    });
    if (chapter) {
      state.totals[chapter] = { done: done, total: boxes.length };
      save(state);
    }
  }

  boxes.forEach(function (b) {
    b.checked = !!state.checks[b.getAttribute("data-id")];
    b.addEventListener("change", function () {
      state.checks[b.getAttribute("data-id")] = b.checked;
      save(state);
      refresh();
    });
  });

  notes.forEach(function (t) {
    t.value = state.notes[t.getAttribute("data-id")] || "";
    t.addEventListener("input", function () {
      state.notes[t.getAttribute("data-id")] = t.value;
      save(state);
    });
  });

  if (boxes.length) refresh();

  /* Index page: show saved progress per chapter. */
  Array.prototype.slice.call(document.querySelectorAll("[data-progress-for]")).forEach(function (el) {
    var t = state.totals[el.getAttribute("data-progress-for")];
    if (!t || !t.total) { el.textContent = "טרם התחלתם"; return; }
    el.textContent = t.done === t.total ? "הושלם ✓" : t.done + " / " + t.total;
  });

  /* Copy buttons on code blocks. */
  Array.prototype.slice.call(document.querySelectorAll(".codebox:not(.output)")).forEach(function (box) {
    var label = box.querySelector(".label");
    var pre = box.querySelector("pre");
    if (!label || !pre || !navigator.clipboard) return;
    var btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.type = "button";
    btn.textContent = "copy";
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(pre.innerText).then(function () {
        btn.textContent = "copied";
        setTimeout(function () { btn.textContent = "copy"; }, 1200);
      }, function () {});
    });
    label.appendChild(btn);
  });

  var printBtn = document.querySelector("[data-print]");
  if (printBtn) printBtn.addEventListener("click", function () { window.print(); });

  var resetBtn = document.querySelector("[data-reset]");
  if (resetBtn) resetBtn.addEventListener("click", function () {
    if (!window.confirm("למחוק את כל הסימונים וההערות של הפרק הזה?")) return;
    boxes.forEach(function (b) { b.checked = false; delete state.checks[b.getAttribute("data-id")]; });
    notes.forEach(function (t) { t.value = ""; delete state.notes[t.getAttribute("data-id")]; });
    save(state);
    refresh();
  });
})();
