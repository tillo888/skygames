// All server calls live here. In the static preview (window.SKYGAMES_DEMO)
// the same functions answer from embedded data instead.

const DEMO = () => window.SKYGAMES_DEMO;

async function json(res) {
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) throw new Error(body?.error || `Request failed (${res.status})`);
  return body;
}

function demoOnly() {
  return Promise.reject(new Error("This preview can't re-score. Run the SkyGames server to change rules or upload files."));
}

export const api = {
  me: () => DEMO() ? Promise.resolve({ admin: true, admin_enabled: true }) : fetch("api/me").then(json),
  login: (password) => fetch("api/login", { method: "POST", headers: { "Content-Type": "application/json" },
                                            body: JSON.stringify({ password }) }).then(json),
  logout: () => fetch("api/logout", { method: "POST" }).then(json),
  meta: () => DEMO() ? Promise.resolve(DEMO().meta) : fetch("api/meta").then(json),
  listHeats: () => DEMO() ? Promise.resolve({ heats: DEMO().heats }) : fetch("api/heats").then(json),
  getHeat: (id) => DEMO() ? Promise.resolve(DEMO().payload) : fetch(`api/heats/${id}`).then(json),
  createHeat: ({ name, task, ruleValues, files }) => {
    if (DEMO()) return demoOnly();
    const fd = new FormData();
    fd.append("name", name);
    fd.append("task", task);
    fd.append("rule_values", JSON.stringify(ruleValues));
    for (const f of files) { fd.append("files", f.file, f.file.name); fd.append("flyers", f.flyer); }
    return fetch("api/heats", { method: "POST", body: fd }).then(json);
  },
  rescore: (id, body) => DEMO() ? demoOnly()
    : fetch(`api/heats/${id}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" },
                                         body: JSON.stringify(body) }).then(json),
  deleteHeat: (id) => DEMO() ? demoOnly() : fetch(`api/heats/${id}`, { method: "DELETE" }).then(json),
  downloadUrl: (id, kind) => DEMO() ? null : `api/heats/${id}/download/${kind}`,
};
