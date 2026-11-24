// Competitions tab: public event list + registration; admin editing and registrations.
import { h, toast, confirmDialog } from "./dom.js";
import { api } from "./api.js";
import { state } from "./state.js";

const SHORT = { distance: "Distance", speed_course: "Speed course", max_horizontal_speed: "Max speed" };
const ALL = Object.keys(SHORT);
let ctx = { admin: false, open: null, mode: null }; // open = competition id; mode = "register" | "edit" | "regs" | "done"

const d = (iso) => new Date(iso + "T00:00:00Z");
const fmt = (iso, o) => d(iso).toLocaleDateString("en-GB", { timeZone: "UTC", ...o });

function dateParts(c) {
  const sameMonth = c.start_date.slice(0, 7) === c.end_date.slice(0, 7);
  const days = c.start_date === c.end_date ? fmt(c.start_date, { day: "numeric" })
    : sameMonth ? `${fmt(c.start_date, { day: "numeric" })}–${fmt(c.end_date, { day: "numeric" })}`
    : `${fmt(c.start_date, { day: "numeric", month: "short" })} – ${fmt(c.end_date, { day: "numeric", month: "short" })}`;
  const month = sameMonth ? fmt(c.start_date, { month: "short", year: "numeric" }) : fmt(c.end_date, { year: "numeric" });
  return { days, month };
}

function statusText(c) {
  if (c.status === "past") return "Finished";
  if (c.status === "closed") return "Registration closed";
  if (c.status === "full") return "Full";
  return c.spots_left != null ? `Registration open · ${c.spots_left} spot${c.spots_left === 1 ? "" : "s"} left` : "Registration open";
}

export async function renderCompetitions({ admin }) {
  ctx.admin = admin;
  const host = document.getElementById("view-competitions");
  let comps;
  try { comps = (await api.listCompetitions()).competitions; }
  catch (e) { host.replaceChildren(h("div", { class: "comp-wrap" }, h("div", { class: "banner error" }, e.message))); return; }
  const upcoming = comps.filter((c) => c.status !== "past");
  const past = comps.filter((c) => c.status === "past").reverse();
  const rerender = () => renderCompetitions({ admin });

  host.replaceChildren(h("div", { class: "comp-wrap" },
    h("div", { class: "comp-head" },
      h("h1", {}, "Competitions"),
      admin ? h("button", { class: "btn small", type: "button", onclick: () => { ctx.open = "new"; ctx.mode = "edit"; rerender(); } }, "New competition") : null),
    ctx.open === "new" ? h("div", { class: "comp-row open" }, editForm(null, rerender)) : null,
    upcoming.length ? h("ol", { class: "comp-list" }, upcoming.map((c) => row(c, rerender)))
      : h("p", { class: "muted" }, "No upcoming competitions yet."),
    past.length ? [h("h2", { class: "comp-sub" }, "Past"), h("ol", { class: "comp-list past" }, past.map((c) => row(c, rerender)))] : null));
}

function row(c, rerender) {
  const { days, month } = dateParts(c);
  const isOpen = ctx.open === c.id;
  const toggle = (mode) => { ctx = { ...ctx, open: isOpen && ctx.mode === mode ? null : c.id, mode }; rerender(); };
  const actions = [];
  if (c.status === "open") actions.push(h("button", { class: isOpen && ctx.mode === "register" ? "btn small" : "btn primary-sm", type: "button", "aria-expanded": String(isOpen && ctx.mode === "register"), onclick: () => toggle("register") }, isOpen && ctx.mode === "register" ? "Cancel" : "Register"));
  if (ctx.admin) {
    actions.push(h("button", { class: "btn small", type: "button", onclick: () => toggle("regs") }, `Registrations (${c.registered ?? 0})`));
    actions.push(h("button", { class: "btn small", type: "button", onclick: () => toggle("edit") }, "Edit"));
  }
  let panel = null;
  if (isOpen) panel = ctx.mode === "register" ? registerForm(c, rerender) : ctx.mode === "done" ? ctx.doneView
    : ctx.mode === "edit" ? editForm(c, rerender) : ctx.mode === "regs" ? regsPanel(c, rerender) : null;
  return h("li", { class: "comp-row" + (isOpen ? " open" : "") },
    h("div", { class: "comp-main" },
      h("div", { class: "comp-date" }, h("span", { class: "days num" }, days), h("span", { class: "month" }, month)),
      h("div", { class: "comp-info" },
        h("h2", {}, c.name),
        h("div", { class: "where" }, c.location),
        h("div", { class: "disc" }, c.disciplines.map((k) => SHORT[k] || k).join(", ")),
        h("div", { class: "status status-" + c.status }, statusText(c)),
        c.notes ? h("p", { class: "notes-text" }, c.notes) : null),
      h("div", { class: "comp-actions" }, actions)),
    panel);
}

function field(label, input, hint) {
  return h("div", { class: "field" }, h("label", { for: input.id }, label), input, hint ? h("span", { class: "help" }, hint) : null);
}

function registerForm(c, rerender) {
  const id = (n) => `reg-${c.id}-${n}`;
  const name = h("input", { type: "text", id: id("name"), autocomplete: "name", required: true, maxlength: 80 });
  const total = h("input", { type: "number", id: id("total"), min: 0, step: 1, inputmode: "numeric", required: true });
  const track = h("input", { type: "number", id: id("track"), min: 0, step: 1, inputmode: "numeric", required: true });
  const lic = h("input", { type: "text", id: id("lic"), required: true, maxlength: 80, placeholder: "e.g. USPA, RFAE Spain, CBPq Brazil" });
  const trap = h("input", { type: "text", name: "website", tabindex: "-1", autocomplete: "off", class: "trap", "aria-hidden": "true" });
  const boxes = c.disciplines.map((k) => h("label", { class: "check" }, h("input", { type: "checkbox", value: k, checked: c.disciplines.length === 1 }), SHORT[k] || k));
  const msg = h("div", { class: "status-line", role: "alert" });
  const submit = h("button", { class: "btn primary", type: "submit" }, "Register");
  const form = h("form", { class: "comp-form", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    const disciplines = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    submit.disabled = true; msg.textContent = "Sending…"; msg.classList.remove("error");
    try {
      const r = await api.register(c.id, { name: name.value, total_jumps: total.value, tracking_jumps: track.value,
        license: lic.value, disciplines, website: trap.value });
      ctx.mode = "done";
      ctx.doneView = h("div", { class: "comp-form done" },
        h("h3", {}, `You're registered for ${c.name}.`),
        r.payment_url
          ? [h("p", {}, "Next, pay the entry fee. The payment page opens in a new tab."),
             h("a", { class: "btn primary", href: r.payment_url, target: "_blank", rel: "noopener noreferrer" }, "Pay entry fee")]
          : h("p", {}, "The payment link isn't published yet. Check back on this page before the event."));
      rerender();
    } catch (err) {
      msg.textContent = err.message; msg.classList.add("error"); submit.disabled = false;
    }
  } },
    h("div", { class: "form-grid" },
      field("Full name", name),
      field("Total jumps", total),
      field("Tracking jumps", track),
      field("License country or federation", lic)),
    h("fieldset", { class: "field" }, h("legend", {}, "Disciplines"), h("div", { class: "checks" }, boxes)),
    trap, h("div", { class: "form-foot" }, submit, msg));
  queueMicrotask(() => name.focus());
  return form;
}

function editForm(c, rerender) {
  const v = c || { name: "", location: "", start_date: "", end_date: "", disciplines: ALL, payment_url: "", spots: null, registration_open: true, notes: "" };
  const pre = c ? `edit-${c.id}` : "edit-new";
  const inp = (n, attrs) => h("input", { id: `${pre}-${n}`, ...attrs });
  const name = inp("name", { type: "text", value: v.name, required: true });
  const loc = inp("loc", { type: "text", value: v.location, placeholder: "City, Country" });
  const start = inp("start", { type: "date", value: v.start_date, required: true });
  const end = inp("end", { type: "date", value: v.end_date, required: true });
  const pay = inp("pay", { type: "url", value: v.payment_url || "", placeholder: "https://…" });
  const spots = inp("spots", { type: "number", min: 1, step: 1, value: v.spots ?? "", placeholder: "No limit" });
  const notes = h("textarea", { id: `${pre}-notes`, rows: 2 }, v.notes || "");
  const open = h("input", { type: "checkbox", checked: v.registration_open });
  const boxes = ALL.map((k) => h("label", { class: "check" }, h("input", { type: "checkbox", value: k, checked: v.disciplines.includes(k) }), SHORT[k]));
  const msg = h("div", { class: "status-line", role: "alert" });
  return h("form", { class: "comp-form", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    const body = { name: name.value, location: loc.value, start_date: start.value, end_date: end.value || start.value,
      payment_url: pay.value, spots: spots.value, notes: notes.value, registration_open: open.checked,
      disciplines: boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value) };
    try {
      await (c ? api.updateCompetition(c.id, body) : api.createCompetition(body));
      toast(c ? "Saved" : "Competition created");
      ctx.open = null; rerender();
    } catch (err) { msg.textContent = err.message; msg.classList.add("error"); }
  } },
    h("h3", {}, c ? `Edit ${c.name}` : "New competition"),
    h("div", { class: "form-grid" },
      field("Name", name), field("Location", loc), field("First day", start), field("Last day", end),
      field("Payment link", pay, "Shown to people right after they register."), field("Spots", spots, "Leave empty for no limit.")),
    h("fieldset", { class: "field" }, h("legend", {}, "Disciplines"), h("div", { class: "checks" }, boxes)),
    field("Notes shown on the event", notes),
    h("label", { class: "toggle" }, open, h("span", {}, "Registration open")),
    h("div", { class: "form-foot" },
      h("button", { class: "btn primary", type: "submit" }, c ? "Save changes" : "Create competition"),
      h("button", { class: "btn small", type: "button", onclick: () => { ctx.open = null; rerender(); } }, "Cancel"),
      c ? h("button", { class: "btn small danger", type: "button", onclick: async () => {
        if (!(await confirmDialog(`Delete ${c.name}?`, `This also deletes its ${c.registered ?? 0} registration(s). It can't be undone.`))) return;
        try { await api.deleteCompetition(c.id); toast(`Deleted ${c.name}`); ctx.open = null; rerender(); } catch (err) { toast(err.message); }
      } }, "Delete competition") : null,
      msg));
}

function regsPanel(c, rerender) {
  const box = h("div", { class: "comp-form" }, h("p", { class: "muted" }, "Loading…"));
  api.registrations(c.id).then(({ registrations: regs }) => {
    const csv = api.registrationsCsvUrl(c.id);
    box.replaceChildren(
      h("div", { class: "regs-head" }, h("h3", {}, `${regs.length} registration${regs.length === 1 ? "" : "s"}`),
        regs.length ? h("a", { class: "btn small", href: csv, download: "" }, "Download spreadsheet (CSV)") : null),
      regs.length ? h("div", { class: "table-scroll" }, h("table", { class: "regs" },
        h("thead", {}, h("tr", {}, ["Name", "Total jumps", "Tracking jumps", "License / federation", "Disciplines", "Registered", ""].map((t) => h("th", {}, t)))),
        h("tbody", {}, regs.map((r) => h("tr", {},
          h("td", {}, r.name), h("td", { class: "n" }, r.total_jumps.toLocaleString()), h("td", { class: "n" }, r.tracking_jumps.toLocaleString()),
          h("td", {}, r.license), h("td", {}, r.disciplines.map((k) => SHORT[k] || k).join(", ")),
          h("td", {}, new Date(r.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })),
          h("td", {}, h("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${r.name}`, title: "Remove", onclick: async () => {
            if (!(await confirmDialog(`Remove ${r.name}?`, "Their registration is deleted. It can't be undone.", "Remove"))) return;
            await api.deleteRegistration(r.id); toast(`Removed ${r.name}`); rerender();
          } }, "×"))))))) : h("p", { class: "muted" }, "Nobody has registered yet."));
  }).catch((e) => box.replaceChildren(h("div", { class: "banner error" }, e.message)));
  return box;
}

export function resetCompetitions() { ctx = { admin: false, open: null, mode: null }; }
