// Saved heats list.
import { h, fmtScore, UNIT_LABEL, toast, confirmDialog } from "./dom.js";
import { api } from "./api.js";

// Sign-in form shown in place of any locked tab.
export function renderLocked(host, { title, adminEnabled, onSignedIn }) {
  const pw = h("input", { type: "password", id: "admin-pw", autocomplete: "current-password", required: true });
  const msg = h("div", { class: "status-line", role: "alert" });
  const form = h("form", { class: "signin", onsubmit: async (e) => {
    e.preventDefault();
    msg.textContent = "Signing in…"; msg.classList.remove("error");
    try { await api.login(pw.value); onSignedIn(); }
    catch (err) { msg.textContent = err.message; msg.classList.add("error"); pw.select(); }
  } },
    h("h1", {}, title),
    adminEnabled
      ? [h("p", {}, "Results are only visible to SkyGames admins. The Analyzer is open to everyone."),
         h("div", { class: "field" }, h("label", { for: "admin-pw" }, "Admin password"), pw),
         h("button", { class: "btn primary", type: "submit" }, "Sign in"), msg]
      : h("p", {}, "Admin sign-in isn't set up on this server yet. Set SKYGAMES_ADMIN_PASSWORD to enable it."));
  host.replaceChildren(h("div", { class: "heats-wrap" }, form));
  if (adminEnabled) pw.focus();
}

export async function renderHeats({ onOpen }) {
  const host = document.getElementById("view-heats");
  host.replaceChildren(h("div", { class: "heats-wrap" }, h("h1", {}, "Saved heats"), h("p", { class: "muted" }, "Loading…")));
  let heats = [];
  try { heats = (await api.listHeats()).heats; }
  catch (e) { host.replaceChildren(h("div", { class: "heats-wrap" }, h("div", { class: "banner error" }, e.message))); return; }

  const wrap = h("div", { class: "heats-wrap" }, h("h1", {}, "Saved heats"));
  if (!heats.length) {
    wrap.append(h("p", {}, "No heats yet. Score one in the Analyzer and it is saved here automatically."));
    host.replaceChildren(wrap); return;
  }
  const rows = heats.map((ht) => {
    const sm = ht.summary || {};
    const when = new Date(ht.updated_at).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
    return h("tr", {},
      h("td", { class: "name" }, ht.name, ht.created_by === "public" ? h("span", { class: "tag" }, "Public upload") : null),
      h("td", {}, sm.task_label || ht.task),
      h("td", {}, sm.flyers ?? "–"),
      h("td", {}, sm.winner ? `${sm.winner} · ${fmtScore(sm.winning_score, sm.unit)} ${UNIT_LABEL[sm.unit] || ""}` : "–"),
      h("td", {}, when),
      h("td", { class: "actions" },
        h("button", { class: "btn small", onclick: () => onOpen(ht.id) }, "Open"), " ",
        h("button", { class: "btn small danger", onclick: async () => {
          if (!(await confirmDialog(`Delete ${ht.name}?`, "This removes the heat, its scores and its uploaded files. It can't be undone."))) return;
          try { await api.deleteHeat(ht.id); toast(`Deleted ${ht.name}`); renderHeats({ onOpen }); }
          catch (e) { toast(e.message); }
        } }, "Delete")));
  });
  wrap.append(h("table", { class: "heats-table" },
    h("thead", {}, h("tr", {}, ["Heat", "Discipline", "Flyers", "Winner", "Last scored", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows)));
  host.replaceChildren(wrap);
}
