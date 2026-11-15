---
applyTo: '**'
---

# Project progress

- Treat `tasks/todo.md` as the single project-wide progress checklist.
- Before a task and in its PR, reconcile merged work against `master` and update
  the affected checklist items, links, blockers and reconciliation date.
- After each completed task or slice, record the accomplished items and their
  evidence in `tasks/todo.md`, then recalculate the overall percentage and
  per-phase counts from the tracker's stated counting method. Update the
  snapshot even when only a nested slice was completed and the percentage is
  unchanged.
- Mark an item complete only after its work is merged and its checks pass. Keep
  open-PR work unchecked and identify it as in review. Reconcile newly merged
  items on the next task branch. The owner has authorized merging reviewed,
  verified PRs.
- Preserve the specification approval and external-action gates in the tracker.
