import { BootSequence } from "./components/BootSequence";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { ReconfigureChoice } from "./components/ReconfigureChoice";
import { SetupWizard } from "./components/SetupWizard";
import StudioLayout from "./components/StudioLayout";
import { WelcomePage } from "./components/WelcomePage";
import { useStudio } from "./hooks/useStudio";

export default function AppShell() {
  const studio = useStudio();

  if (studio.phase === "welcome") {
    return <WelcomePage appName={studio.config?.app.name} tagline={studio.config?.app.tagline} onEnter={studio.beginBoot} />;
  }

  if (studio.phase === "booting") {
    return <BootSequence onComplete={studio.finishBoot} />;
  }

  if (studio.phase === "setup") {
    return <SetupWizard initial={studio.setupDraft} onSubmit={studio.submitSetup} busy={studio.busy} error={studio.error} />;
  }

  if (studio.phase === "reconfigure-choice") {
    return (
      <ReconfigureChoice
        onEdit={studio.reconfigureEdit}
        onRefill={studio.reconfigureRefill}
        onCancel={studio.cancelReconfigure}
        busy={studio.busy}
      />
    );
  }

  if (studio.phase === "connected" && studio.setupResult) {
    return (
      <ConnectionStatus
        result={studio.setupResult}
        onEnterStudio={studio.enterStudio}
        onReconfigure={studio.beginReconfigure}
      />
    );
  }

  return <StudioLayout studio={studio} />;
}
