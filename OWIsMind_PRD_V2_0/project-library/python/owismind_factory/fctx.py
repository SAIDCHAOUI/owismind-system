"""FactoryContext: dry-run plumbing, action journal and markdown report.

Every factory function takes a FactoryContext as first argument and routes its
side effects through :meth:`FactoryContext.act`. In dry-run mode (the default)
nothing touches DSS: the action is recorded as PLANNED and the function returns
None. This gives a reviewable execution PLAN before anything runs for real.
"""

import logging
import traceback

logger = logging.getLogger("owismind.factory")

# Action statuses (stable strings, consumed by the console webapp and the report).
PLANNED = "PLANNED"   # dry-run: would have executed
DONE = "DONE"         # executed successfully
SKIPPED = "SKIPPED"   # nothing to do (object already exists / disabled step)
FAILED = "FAILED"     # executed and raised (the exception is captured, not re-raised)
MANUAL = "MANUAL"     # cannot or must not be automated: do this by hand (detail says how)
BLOCKED = "BLOCKED"   # not attempted: a prerequisite step failed earlier in the run


class FactoryContext(object):
    """Execution context shared by all factory steps.

    :param project: a ``dataikuapi`` project handle. Defaults to the current
        DSS project (``dataiku.api_client().get_default_project()``).
    :param bool dry_run: when True (default) no mutating call is executed.
    :param bool abort_on_failure: when True, :meth:`act` re-raises after
        recording a FAILED action (notebook usage); when False (webapp usage)
        the pipeline keeps going and the report shows the failure.
    """

    def __init__(self, project=None, dry_run=True, abort_on_failure=False):
        if project is None:
            import dataiku
            project = dataiku.api_client().get_default_project()
        self.project = project
        self.dry_run = bool(dry_run)
        self.abort_on_failure = bool(abort_on_failure)
        self.actions = []

    # ------------------------------------------------------------------ journal

    def record(self, step, status, detail=""):
        entry = {"step": step, "status": status, "detail": str(detail or "")}
        self.actions.append(entry)
        logger.info("[factory][%s] %s : %s", status, step, entry["detail"][:300])
        return entry

    def plan(self, step, detail=""):
        return self.record(step, PLANNED, detail)

    def done(self, step, detail=""):
        return self.record(step, DONE, detail)

    def skip(self, step, detail=""):
        return self.record(step, SKIPPED, detail)

    def fail(self, step, detail=""):
        return self.record(step, FAILED, detail)

    def manual(self, step, detail=""):
        return self.record(step, MANUAL, detail)

    def block(self, step, detail=""):
        return self.record(step, BLOCKED, detail)

    # ------------------------------------------------------------------ execute

    def act(self, step, detail, fn):
        """Run ``fn()`` unless in dry-run mode.

        Returns fn's return value, or None when the action was only planned or
        failed (with abort_on_failure=False).
        """
        if self.dry_run:
            self.plan(step, detail)
            return None
        try:
            result = fn()
            self.done(step, detail)
            return result
        except Exception as exc:  # noqa: BLE001 - reported, optionally re-raised
            self.fail(step, "%s :: %s" % (detail, exc))
            logger.error("[factory] step %r failed\n%s", step, traceback.format_exc())
            if self.abort_on_failure:
                raise
            return None

    # ------------------------------------------------------------------ report

    def has_failures(self):
        return any(a["status"] == FAILED for a in self.actions)

    def manual_steps(self):
        return [a for a in self.actions if a["status"] == MANUAL]

    def summary(self):
        counts = {}
        for a in self.actions:
            counts[a["status"]] = counts.get(a["status"], 0) + 1
        return {"dry_run": self.dry_run, "counts": counts, "actions": list(self.actions)}

    def report_markdown(self, title="Factory report"):
        lines = ["# %s" % title, ""]
        lines.append("Mode: %s" % ("DRY RUN (nothing executed)" if self.dry_run else "EXECUTE"))
        lines.append("")
        for a in self.actions:
            lines.append("- **%s** `%s` : %s" % (a["status"], a["step"], a["detail"]))
        manuals = self.manual_steps()
        if manuals:
            lines.append("")
            lines.append("## Manual steps remaining")
            for a in manuals:
                lines.append("- `%s` : %s" % (a["step"], a["detail"]))
        return "\n".join(lines)

    def runbook_markdown(self, title="Run book"):
        """Render a copy-pastable, ordered human runbook of what is left to do.

        Where :meth:`report_markdown` logs every action for the record, this
        renders the MANUAL actions as an ordered checklist the operator can tick
        off, preceded by a one-line count summary and, when any FAILED or BLOCKED
        action exists, a warning section that must be read first.
        """
        counts = {}
        for a in self.actions:
            counts[a["status"]] = counts.get(a["status"], 0) + 1
        summary = ", ".join("%d %s" % (counts[s], s) for s in sorted(counts))

        lines = ["# %s" % title, ""]
        lines.append("Summary: %s" % (summary or "no actions recorded"))

        blockers = [a for a in self.actions if a["status"] in (FAILED, BLOCKED)]
        if blockers:
            lines.append("")
            lines.append("## WARNING: unresolved before you start")
            for a in blockers:
                lines.append("- **%s** `%s` : %s" % (a["status"], a["step"], a["detail"]))

        lines.append("")
        lines.append("## Manual steps (do these in order)")
        manuals = self.manual_steps()
        if manuals:
            for index, a in enumerate(manuals, start=1):
                lines.append("%d. [ ] `%s` : %s" % (index, a["step"], a["detail"]))
        else:
            lines.append("- [x] none: no manual step required.")
        return "\n".join(lines)
