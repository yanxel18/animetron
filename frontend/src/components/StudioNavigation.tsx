import { Icon, type IconName } from "./Icon";

interface StudioNavigationProps {
  activeSection: "studio" | "review";
  mobileOpen: boolean;
  onStudioNavigate: () => void;
  onReviewNavigate: () => void;
}

const unavailableAreas: { label: string; icon: IconName }[] = [
  { label: "Runs", icon: "runs" },
  { label: "Library", icon: "library" },
  { label: "Models", icon: "models" },
  { label: "Schedules", icon: "schedules" },
  { label: "Connections", icon: "connections" },
  { label: "Settings", icon: "settings" },
];

export function StudioNavigation({
  activeSection,
  mobileOpen,
  onStudioNavigate,
  onReviewNavigate,
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
        <p id="navigation-availability" className="navigation-explanation">
          Review shows owner-only metadata. Decisions require an exact media
          preview; other sections are not implemented.
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
