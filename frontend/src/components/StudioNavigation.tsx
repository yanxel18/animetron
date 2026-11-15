import { Icon, type IconName } from "./Icon";

interface StudioNavigationProps {
  activeSection: "studio" | "review" | "runs" | "schedules";
  mobileOpen: boolean;
  onStudioNavigate: () => void;
  onReviewNavigate: () => void;
  onRunsNavigate: () => void;
  onSchedulesNavigate: () => void;
}

const unavailableAreas: { label: string; icon: IconName }[] = [
  { label: "Library", icon: "library" },
  { label: "Models", icon: "models" },
  { label: "Connections", icon: "connections" },
  { label: "Settings", icon: "settings" },
];

export function StudioNavigation({
  activeSection,
  mobileOpen,
  onStudioNavigate,
  onReviewNavigate,
  onRunsNavigate,
  onSchedulesNavigate,
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
          Runs shows persisted history. Review is read-only; Schedules supports
          previews and pause or resume. Other sections are not implemented.
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
