// Sidebar: heat name, discipline, flyer files.
import { h, fmtBytes } from "./dom.js";
import { state, update } from "./state.js";

const SHORT = { distance: "Distance", speed_course: "Speed course", max_horizontal_speed: "Max speed" };

export function initSetup() {
  const name = document.getElementById("heat-name");
  name.addEventListener("input", () => update({ name: name.value }));

  const input = document.getElementById("file-input");
  const zone = document.getElementById("dropzone");
  input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("drag"); addFiles(e.dataTransfer.files); });
}

function addFiles(list) {
  const incoming = [...list].filter((f) => /\.csv$/i.test(f.name));
  if (!incoming.length) return;
  // Adding files to a saved heat starts a new heat with those files plus nothing else.
  const base = state.heatId ? [] : state.files;
  const known = new Set(base.map((f) => f.file?.name + f.file?.size));
  const add = incoming.filter((f) => !known.has(f.name + f.size))
    .map((file) => ({ file, flyer: file.name.replace(/\.csv$/i, "") }));
  update({ files: [...base, ...add], heatId: state.heatId ? null : state.heatId,
           payload: state.heatId ? null : state.payload });
}

export function renderSetup() {
  const name = document.getElementById("heat-name");
  if (document.activeElement !== name) name.value = state.name;

  const picker = document.getElementById("task-picker");
  picker.replaceChildren(...(state.meta?.tasks || []).map((t) =>
    h("button", { type: "button", "aria-pressed": String(state.task === t.key), title: t.label,
                  onclick: () => update({ task: t.key }) }, SHORT[t.key] || t.label)));

  document.getElementById("files-count").textContent = state.files.length ? `${state.files.length} file${state.files.length > 1 ? "s" : ""}` : "";
  const ul = document.getElementById("file-list");
  const focused = document.activeElement?.dataset?.idx;
  ul.replaceChildren(...state.files.map((f, i) => {
    const saved = !f.file;
    const color = saved ? f.color : null;
    const inp = h("input", { type: "text", value: f.flyer, "aria-label": `Flyer name for ${saved ? f.file_name : f.file.name}`, "data-idx": i,
      oninput: (e) => { const files = state.files.slice(); files[i] = { ...files[i], flyer: e.target.value }; update({ files, _typing: true }); } });
    const meta = saved
      ? h("div", { class: "meta" + (f.ok === false ? " bad" : "") }, f.ok === false ? `${f.file_name} · not scored` : f.file_name)
      : h("div", { class: "meta" }, `${f.file.name} · ${fmtBytes(f.file.size)}`);
    return h("li", { class: "file-row" },
      h("span", { class: "dot", style: color ? { background: color } : null }),
      inp,
      saved ? h("span") : h("button", { class: "icon-btn", type: "button", title: "Remove", "aria-label": `Remove ${f.file.name}`,
        onclick: () => update({ files: state.files.filter((_, j) => j !== i) }) }, "×"),
      meta);
  }));
  if (focused !== undefined) ul.querySelector(`[data-idx="${focused}"]`)?.focus();
}
