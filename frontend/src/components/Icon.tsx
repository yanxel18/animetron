export type IconName =
  | "activity"
  | "brand"
  | "connections"
  | "info"
  | "library"
  | "menu"
  | "models"
  | "review"
  | "runs"
  | "schedules"
  | "settings"
  | "studio"
  | "workflow";

interface IconProps {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 18 }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {name === "brand" && (
        <>
          <path d="M12 2.8 20 7.4v9.2L12 21.2l-8-4.6V7.4z" />
          <path d="m8 14.8 4-7 4 7" />
          <path d="M9.8 12.2h4.4" />
        </>
      )}
      {name === "studio" && (
        <>
          <rect x="3.5" y="4" width="17" height="16" rx="2" />
          <path d="M7.5 8h9M7.5 12h5M7.5 16h3" />
        </>
      )}
      {name === "runs" && (
        <>
          <path d="M5 4.5h14M5 9.5h14M5 14.5h8" />
          <circle cx="18" cy="17" r="3" />
          <path d="m17.3 16.3 1.4 1.4 2.3-2.6" />
        </>
      )}
      {name === "library" && (
        <>
          <path d="M4 5.5h11l5 4v9H4z" />
          <path d="M15 5.5v4h5M7.5 13h9M7.5 16.5h6" />
        </>
      )}
      {name === "review" && (
        <>
          <path d="M5 4h14v16H5zM8 9l2 2 4-4M8 15h8" />
        </>
      )}
      {name === "models" && (
        <>
          <path d="M12 3.5 20 8v8l-8 4.5L4 16V8z" />
          <path d="m4.5 8.3 7.5 4.3 7.5-4.3M12 12.8v7.4" />
        </>
      )}
      {name === "schedules" && (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7v5l3.5 2" />
        </>
      )}
      {name === "connections" && (
        <>
          <path d="M9.5 14.5 7.8 16a3 3 0 0 1-4.3-4.2l4-4A3 3 0 0 1 11.7 8" />
          <path d="m14.5 9.5 1.7-1.6a3 3 0 0 1 4.3 4.2l-4 4a3 3 0 0 1-4.2-.2" />
          <path d="m9 15 6-6" />
        </>
      )}
      {name === "settings" && (
        <>
          <circle cx="12" cy="12" r="3" />
          <path d="m19.4 15 .1.1 1.1.9-1.1 1.9-1.4-.5a7.8 7.8 0 0 1-1.4.8l-.3 1.5h-2.2l-.3-1.5a7.8 7.8 0 0 1-1.5-.8l-1.4.5-1.1-1.9 1.1-.9a6 6 0 0 1 0-1.7l-1.1-.9L9 10.6l1.4.5a7.8 7.8 0 0 1 1.4-.8l.3-1.5h2.2l.3 1.5a7.8 7.8 0 0 1 1.5.8l1.4-.5 1.1 1.9-1.1.9a6 6 0 0 1-.1 1.6Z" />
        </>
      )}
      {name === "menu" && <path d="M4 6.5h16M4 12h16M4 17.5h16" />}
      {name === "workflow" && (
        <>
          <rect x="3.5" y="4" width="6" height="5" rx="1" />
          <rect x="14.5" y="15" width="6" height="5" rx="1" />
          <rect x="14.5" y="4" width="6" height="5" rx="1" />
          <path d="M9.5 6.5h5M6.5 9v8.5h8" />
        </>
      )}
      {name === "activity" && (
        <>
          <path d="M3.5 12h4l2.2-6 4.2 12 2.2-6h4.4" />
        </>
      )}
      {name === "info" && (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 11v5M12 8h.01" />
        </>
      )}
    </svg>
  );
}
