import { Icon, type IconName } from "./Icon";

interface StudioNavigationProps {
  mobileOpen: boolean;
  onStudioNavigate: () => void;
}

const unavailableAreas: { label: string; icon: IconName }[] = [
  { label: "Runs", icon: "runs" },
  { label: "Library", icon: "library" },
  { label: "Review", icon: "review" },
  { label: "Models", icon: "models" },
  { label: "Schedules", icon: "schedules" },
  { label: "Connections", icon: "connections" },
  { label: "Settings", icon: "settings" },
];

export function StudioNavigation({
  mobileOpen,
  onStudioNavigate,
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
          className="navigation-link navigation-link--current"
          href="#workspace"
          aria-current="page"
          onClick={onStudioNavigate}
        >
          <Icon name="studio" />
          <span>Studio</span>
        </a>
        <p id="navigation-availability" className="navigation-explanation">
          Only the Studio shell is available in this foundation. Other sections
          are not implemented.
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
