(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.Journey = api;
})(typeof self !== "undefined" ? self : this, function () {
  function runnableLabel(detail) {
    var n = (detail && detail.runnable) || 0;
    if (n > 0) return { label: "Run pending (" + n + ")", enabled: true, hint: "" };
    return { label: "Run pending (0)", enabled: false,
             hint: "Nothing pending. Tag new questions to this agent, or flag a tested question to redo." };
  }
  function benchmarkListState(v) {
    var has = v && v.benchmarks && v.benchmarks.length > 0;
    if (has) return "list";
    return (v && v.n_tagged > 0) ? "empty_has_questions" : "empty_no_questions";
  }
  function createGate(nTagged) {
    return nTagged > 0 ? { canCreate: true, primaryAction: "create" }
                       : { canCreate: false, primaryAction: "tag" };
  }
  function cellChip(cell) {
    if (!cell || cell.status !== "tested") return { text: "Pending", kind: "pending" };
    return cell.verdict === "OK" ? { text: "OK", kind: "ok" } : { text: "MISS", kind: "miss" };
  }
  function evolutionToken(prev, cur) {
    if (prev == null) return "new";
    if (prev === cur) return "same";
    if (prev === "MISS" && cur === "OK") return "improved";
    if (prev === "OK" && cur === "MISS") return "regressed";
    return "same";
  }
  return { runnableLabel: runnableLabel, benchmarkListState: benchmarkListState,
           createGate: createGate, cellChip: cellChip, evolutionToken: evolutionToken };
});
