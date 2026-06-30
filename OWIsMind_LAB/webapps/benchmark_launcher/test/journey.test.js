const test = require("node:test");
const assert = require("node:assert");
const J = require("../journey.js");

test("runnableLabel armed when runnable > 0", () => {
  const r = J.runnableLabel({ runnable: 18, ledger: { tested: 0, pending: 18, redo: 0 } });
  assert.equal(r.enabled, true);
  assert.match(r.label, /18/);
});

test("runnableLabel disabled with reason when nothing runnable", () => {
  const r = J.runnableLabel({ runnable: 0, ledger: { tested: 18, pending: 0, redo: 0 } });
  assert.equal(r.enabled, false);
  assert.ok(r.hint.length > 0);
});

test("createGate locks when no tagged questions", () => {
  assert.deepEqual(J.createGate(0), { canCreate: false, primaryAction: "tag" });
  assert.equal(J.createGate(6).canCreate, true);
});

test("benchmarkListState", () => {
  assert.equal(J.benchmarkListState({ benchmarks: [{}], n_tagged: 6 }), "list");
  assert.equal(J.benchmarkListState({ benchmarks: [], n_tagged: 6 }), "empty_has_questions");
  assert.equal(J.benchmarkListState({ benchmarks: [], n_tagged: 0 }), "empty_no_questions");
});

test("evolutionToken", () => {
  assert.equal(J.evolutionToken("MISS", "OK"), "improved");
  assert.equal(J.evolutionToken("OK", "MISS"), "regressed");
  assert.equal(J.evolutionToken("OK", "OK"), "same");
  assert.equal(J.evolutionToken(null, "OK"), "new");
});
