import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Icon } from "./components/Icon";
import { ReviewQueue } from "./components/ReviewQueue";
import { StudioNavigation } from "./components/StudioNavigation";

type StudioSection = "studio" | "review";

function studioSectionFromHash(hash: string): StudioSection {
  return hash === "#review" || hash === "#review-queue-title"
    ? "review"
    : "studio";
}

export function App() {
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<StudioSection>(() =>
    studioSectionFromHash(window.location.hash),
  );

  useEffect(() => {
    const updateActiveSection = () => {
      setActiveSection(studioSectionFromHash(window.location.hash));
    };

    window.addEventListener("hashchange", updateActiveSection);
    return () => window.removeEventListener("hashchange", updateActiveSection);
  }, []);

  const navigateTo = (section: StudioSection) => {
    setActiveSection(section);
    setMobileNavigationOpen(false);
  };
  const mobileNavigationToggleRef = useRef<HTMLButtonElement>(null);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && mobileNavigationOpen) {
      setMobileNavigationOpen(false);
      mobileNavigationToggleRef.current?.focus();
    }
  }

  return (
    <>
      <a
        className="skip-link"
        href={
          activeSection === "review" ? "#review-queue-title" : "#workspace"
        }
      >
        Skip to workspace
      </a>
      <div className="studio-shell" onKeyDown={handleKeyDown}>
        <header className="studio-header">
          <div className="brand-lockup" aria-label="AnimeTron">
            <Icon name="brand" size={26} />
            <span>AnimeTron</span>
          </div>
          <div className="header-controls">
            <button
              ref={mobileNavigationToggleRef}
              className="mobile-navigation-toggle"
              type="button"
              aria-label={
                mobileNavigationOpen ? "Close navigation" : "Open navigation"
              }
              aria-expanded={mobileNavigationOpen}
              aria-controls="studio-navigation"
              onClick={() => setMobileNavigationOpen((open) => !open)}
            >
              <Icon name="menu" />
            </button>
            <span className="backend-state">
              <span className="state-indicator" aria-hidden="true" />
              Backend not checked
            </span>
          </div>
        </header>

        <StudioNavigation
          activeSection={activeSection}
          mobileOpen={mobileNavigationOpen}
          onStudioNavigate={() => navigateTo("studio")}
          onReviewNavigate={() => navigateTo("review")}
        />

        <main
          id="workspace"
          className="workspace"
          aria-label={
            activeSection === "review" ? "Review workspace" : "Creator workspace"
          }
          tabIndex={-1}
        >
          {activeSection === "review" && <ReviewQueue />}
          <div
            className="page-heading"
            hidden={activeSection === "review"}
          >
            <div className="page-title">
              <p className="eyebrow">CREATOR WORKSPACE</p>
              <h1>Studio</h1>
              <p className="page-description">
                A local-first home for creator workflows. Editing and generation
                are not available in this foundation.
              </p>
            </div>
            <div className="workflow-actions" aria-label="Workflow actions">
              <button
                className="button button--secondary"
                type="button"
                disabled
                aria-describedby="workflow-actions-availability"
              >
                Validate
              </button>
              <button
                className="button button--primary"
                type="button"
                disabled
                aria-describedby="workflow-actions-availability"
              >
                Run workflow
              </button>
            </div>
          </div>

          <p
            id="workflow-actions-availability"
            className="availability-note"
            role="note"
            hidden={activeSection === "review"}
          >
            <Icon name="info" size={17} />
            Workflow editing, validation and authorized run actions are not
            implemented in P7-01.
          </p>

          <div
            className="studio-panels"
            hidden={activeSection === "review"}
          >
            <section className="panel canvas-panel" aria-labelledby="canvas-title">
              <div className="panel-heading">
                <div>
                  <p className="panel-kicker">WORKSPACE</p>
                  <h2 id="canvas-title">Workflow canvas</h2>
                </div>
                <span className="panel-state">No draft</span>
              </div>
              <div className="canvas-empty">
                <div className="empty-state">
                  <span className="empty-icon">
                    <Icon name="workflow" size={28} />
                  </span>
                  <h3>No workflow is loaded</h3>
                  <p>
                    Saved drafts and workflow editing arrive in a later studio
                    slice. This canvas contains no sample or generated data.
                  </p>
                </div>
              </div>
            </section>

            <section
              className="panel inspector-panel"
              aria-labelledby="inspector-title"
            >
              <div className="panel-heading">
                <div>
                  <p className="panel-kicker">DETAILS</p>
                  <h2 id="inspector-title">Inspector</h2>
                </div>
              </div>
              <div className="inspector-empty">
                <span className="empty-icon empty-icon--small">
                  <Icon name="studio" size={22} />
                </span>
                <h3>Nothing selected</h3>
                <p>Inspector fields are unavailable without a workflow.</p>
              </div>
            </section>
          </div>

          <section
            className="panel run-panel"
            aria-labelledby="run-title"
            hidden={activeSection === "review"}
          >
            <div className="panel-heading">
              <div>
                <p className="panel-kicker">EXECUTION</p>
                <h2 id="run-title">Run activity</h2>
              </div>
              <span className="panel-state">No run</span>
            </div>
            <div className="run-empty">
              <Icon name="activity" size={18} />
              <div>
                <h3>No run is loaded</h3>
                <p>
                  This workspace does not create, monitor or imply a successful
                  run.
                </p>
              </div>
            </div>
          </section>

          <p
            className="workspace-footnote"
            hidden={activeSection === "review"}
          >
            Liveness, GPU readiness and generated-output status are not queried
            or inferred by this screen.
          </p>
        </main>
      </div>
    </>
  );
}
