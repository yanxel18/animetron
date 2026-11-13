# AnimeTron: Proposed Creator Studio UX

Status: Dark creator studio with cyan accents approved November 13, 2026.
Module specifications approved for implementation November 14, 2026.
Detailed tokens still require measurement and the responsiveness target requires
agreement; no interface has been implemented or runtime-validated.

## Design evidence

The ui-ux-pro-max design-system searches for "video creator workflow dashboard"
and the narrower "creator studio video editing" returned Enterprise Gateway
and Scroll-Triggered Storytelling patterns respectively. Neither fits a working
node editor. No verified product-wide match was found after one retry.

The direction below is explicitly custom general guidance, not an adopted
generated MASTER. Relevant verified local search guidance:

- UX / Accessibility / Dragging Movements: provide single-pointer alternatives
  to dragging as well as keyboard operation.
- React / Performance / Batch state updates: keep normal batching; do not use
  flushSync as a routine progress-update mechanism.
- React / Accessibility / Announce dynamic content: announce meaningful state
  changes without streaming every frame or progress tick to screen readers.

## Product identity

AnimeTron is a production studio, not a marketing landing page. The interface
should foreground the current reel, pipeline state and next safe action.

- Dark-neutral workspace with restrained cyan accents; optional light theme.
- Dense controls, spacious video preview, legible labels and stable panels.
- No decorative parallax, animated backgrounds or autoplaying hero videos.
- Original branding and content; no dependency on existing anime characters.
- One vector icon family, visible text on consequential actions.
- Locally hosted licensed fonts or a system font stack; no runtime font-service
  dependency in a self-hosted local-first product.

## Proposed semantic tokens

These are candidate tokens. Measure contrast for actual composed surfaces and
states before approval; the table is not accessibility certification.

| Role | Dark candidate | Light candidate |
| --- | --- | --- |
| Workspace | #0B1020 | #F8FAFC |
| Surface | #151D30 | #FFFFFF |
| Primary text | #F8FAFC | #0F172A |
| Secondary text | #B8C4D8 | #475569 |
| Action | #67E8F9 | #155E75 |
| On action | #082F49 | #FFFFFF |
| Focus ring | #67E8F9 | #155E75 |

Success, warning, error and approval states need both text/icon semantics and
independently verified contrast. Do not use accent color to imply approval.
Use a 4/8px spacing rhythm, approximately 14-16px body text and monospace only
for identifiers or logs. Respect reduced motion and browser text enlargement.

## Information architecture

| Screen | Primary job | Primary action |
| --- | --- | --- |
| Studio | Compose and validate a workflow | Run workflow |
| Runs | Inspect execution and failures | Open run / cancel / eligible retry |
| Library | Preview outputs and character references | Open artifact |
| Review | See exact revision and destination approval scope | Approve / reject |
| Models | Inspect readiness, license and storage requirements | Confirm download |
| Schedules | Configure execution cadence and overlap behavior | Save schedule |
| Connections | Validate Telegram and destination credentials | Test connection |
| Settings | Resource limits, retention and access settings | Save settings |

## Studio layout

```text
Navigation | Workflow title / Saved revision / Validate / Run
           |---------------------------------------------------
           | Node palette | Canvas                    | Inspector
           |              |                           | Preview
           |---------------------------------------------------
           | Run status / node timeline / logs / queue position
```

- Inspector tabs: Parameters, Inputs/Outputs, Preview, Errors.
- Node status: Pending, Queued, Running, Succeeded, Failed, Skipped, Cancelled.
- Show queue position separately from progress. Use determinate progress only
  when the engine supplies a meaningful denominator; otherwise show activity.
- Render errors beside the affected node with an actionable explanation.
- Visually distinguish draft edits from the immutable revision used by a run.
- Reconnect by fetching durable run state and replaying ordered events; a
  disconnected WebSocket must never appear as a successful completed run.

## Canonical workflow

```text
Story -> Scene plan -> Character/keyframes -> Scene animation
      -> Voice + alignment -> Render -> Telegram review
      -> Approved destination publications
```

Voice and animation consume the same scene plan and join at rendering. The final
workflow specification must define typed ports, join rules and artifact schemas.
There is no arbitrary "run anything" node.

## Human review and publication

- Preview a 9:16 video with voice and burned-in subtitles; do not autoplay audio.
- Show caption, output revision, destination accounts and approval expiry.
- Approve and Reject are explicit, equally discoverable actions.
- A rejection never publishes; edits create a new review revision.
- Display per-platform outcomes: Pending, Uploading, Processing, Published,
  Failed, Unknown. Mixed destination results are not a global success.
- Timeout with unknown publication outcome offers reconciliation, not a blind
  "Retry all" action.
- Mobile web prioritizes preview/review and run monitoring. Use list-based
  workflow editing rather than forcing a full desktop canvas onto small screens.

## Interaction acceptance proposals

- Add/connect/reorder nodes through buttons or menus without dragging.
- Keyboard access to every control, visible focus and no focus obscured by panels.
- Announce node completion/failure and review decisions, not rapid progress ticks.
- Preserve form input after errors; focus a linked summary for multiple errors.
- Clear empty/loading/disconnected/failed states for every screen.
- No secrets in previews, logs, URLs, clipboard exports or workflow JSON.
- Measure normal text at >=4.5:1 and meaningful controls at >=3:1.
- Validate at 375px, 768px, 1024px and 1440px, with 200% zoom and reduced motion.
- Proposed canvas benchmark: 100 nodes and 150 edges without whole-graph
  rerendering on each progress update. Agree a measured responsiveness target
  before implementing performance gates.

## Next design deliverables after scope approval

1. Approved theme and semantic state colors with measured contrast pairs.
2. Screen/state wireframes tied to each module's acceptance criteria.
3. Component contracts for node cards, inspector, run timeline and approval card.
4. Keyboard/single-pointer workflow and small-screen fallback specification.

No UI code or screenshots have been produced in this planning phase.
