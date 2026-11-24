// One shared state object + change notification. Modules read `state`,
// call `update()` to change it, and re-render in their subscribe callback.

export const state = {
  meta: null,            // /api/meta: tasks + rule form definition
  heatId: null,          // saved heat being shown (null = new, unsaved)
  name: "",
  task: "distance",
  files: [],             // new heat: [{file, flyer}] ; saved heat: [{file_id, flyer, file_name, color, ok}]
  ruleValues: {},        // {"window.top_ft": 11000, ...}
  payload: null,         // last results from the server
  scoredSignature: null, // what the payload was computed with (to show "rules changed")
  selected: null,        // flyer name highlighted across map/charts/table
  busy: false,
  view: "analyzer",
};

const subs = new Set();
export function subscribe(fn) { subs.add(fn); return () => subs.delete(fn); }
export function update(patch) {
  Object.assign(state, patch);
  for (const fn of subs) fn(state, patch);
}

export function defaults() {
  return Object.fromEntries((state.meta?.params || []).map((p) => [p.path, p.default]));
}

export function signature() {
  const names = state.files.map((f) => f.flyer).join("|");
  return JSON.stringify([state.name, state.task, state.ruleValues, names]);
}

export function isStale() {
  return !!state.payload && state.heatId && signature() !== state.scoredSignature;
}
