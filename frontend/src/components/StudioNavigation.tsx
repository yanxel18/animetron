import { Icon, type IconName } from "./Icon";

interface StudioNavigationProps {
  activeSection:
    | "studio"
    | "library"
    | "review"
    | "runs"
    | "schedules"
    | "workflows";
  mobileOpen: boolean;
  onStudioNavigate: () => void;
  onLibraryNavigate: () => void;
  onReviewNavigate: () => void;
  onRunsNavigate: () => void;
  onSchedulesNavigate: () => void;
  onWorkflowsNavigate: () => void;
}

const unavailableAreas: { label: string; icon: IconName }[] = [
  { label: "Models", icon: "models" },
  { label: "Connections", icon: "connections" },
  { label: "Settings", icon: "settings" },
];

export function StudioNavigation({
  activeSection,
  mobileOpen,
  onStudioNavigate,
  onLibraryNavigate,
  onReviewNavigate,
  onRunsNavigate,
  onSchedulesNavigate,
  onWorkflowsNavigate,
}: StudioNavigationProps) {
  return (
    <aside
      id="studio-navigation"
      className="studio-navigation"
      data-open={mobileOpen}
      aria-label="Workspace navigation"
    >
      <nav aria-label="Studio sections">
        <a
          className={`navigation-link${activeSection === "studio" ? " navigation-link--current" : ""}`}
          href="#workspace"
          aria-current={activeSection === "studio" ? "page" : undefined}
          onClick={onStudioNavigate}
        >
          <Icon name="studio" />
          <span>Studio</span>
        </a>
        <a
          className={`navigation-link${activeSection === "workflows" ? " navigation-link--current" : ""}`}
          href="#workflows"
          aria-current={activeSection === "workflows" ? "page" : undefined}
          onClick={onWorkflowsNavigate}
        >
          <Icon name="workflow" />
          <span>Workflows</span>
        </a>
        <a
          className={`navigation-link${activeSection === "library" ? " navigation-link--current" : ""}`}
          href="#library"
          aria-current={activeSection === "library" ? "page" : undefined}
          onClick={onLibraryNavigate}
        >
          <Icon name="library" />
          <span>Library</span>
        </a>
        <a
          className={`navigation-link${activeSection === "review" ? " navigation-link--current" : ""}`}
          href="#review"
          aria-current={activeSection === "review" ? "page" : undefined}
          onClick={onReviewNavigate}
        >
          <Icon name="review" />
          <span>Review</span>
        </a>
        <a
          className={`navigation-link${activeSection === "runs" ? " navigation-link--current" : ""}`}
          href="#runs"
          aria-current={activeSection === "runs" ? "page" : undefined}
          onClick={onRunsNavigate}
        >
          <Icon name="runs" />
          <span>Runs</span>
        </a>
        <a
          className={`navigation-link${activeSection === "schedules" ? " navigation-link--current" : ""}`}
          href="#schedules"
          aria-current={activeSection === "schedules" ? "page" : undefined}
          onClick={onSchedulesNavigate}
        >
          <Icon name="schedules" />
          <span>Schedules</span>
        </a>
        <p id="navigation-availability" className="navigation-explanation">
          Library looks up metadata for known artifact IDs only. Workflows can
          validate saved drafts and create revisions; Review is read-only. Runs
          shows persisted history. Schedules supports previews and pause or
          resume. Other sections are not implemented.
        </p>
        <ul className="navigation-list">
          {unavailableAreas.map(({ label, icon }) => (
            <li key={label}>
              <button
                className="navigation-link navigation-link--disabled"
                type="button"
                disabled
                aria-describedby="navigation-availability"
              >
                <Icon name={icon} />
                <span>{label}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <p className="navigation-footnote">
        Backend liveness and resource readiness are not checked here.
      </p>
    </aside>
  );
}
