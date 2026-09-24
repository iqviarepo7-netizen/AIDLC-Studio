import { useEffect, useState } from "react";
import { AgentActivityFeed } from "./AgentActivityFeed";
import { CreateJiraModal } from "./createJira/CreateJiraModal";
import { CodeEditor } from "./CodeEditor";
import { CommandBar } from "./CommandBar";
import { CompletionCard } from "./CompletionCard";
import { FileTree } from "./FileTree";
import { ModelSelectionPanel } from "./ModelSelectionPanel";
import { StageActivityCard } from "./StageActivityCard";
import { TerminalPanel } from "./TerminalPanel";
import { ImplementationReportModal } from "./ImplementationReportModal";
import { WorkflowProgress } from "./WorkflowProgress";
import type { useStudio } from "../hooks/useStudio";
import { canShowReport } from "../reportUtils";

type Props = {
  studio: ReturnType<typeof useStudio>;
};

export function StudioLayout({ studio }: Props) {
  const [createJiraOpen, setCreateJiraOpen] = useState(false);
  const [jiraSuccessNotice, setJiraSuccessNotice] = useState<string>();

  useEffect(() => {
    if (!jiraSuccessNotice) return undefined;
    const handle = window.setTimeout(() => setJiraSuccessNotice(undefined), 6000);
    return () => window.clearTimeout(handle);
  }, [jiraSuccessNotice]);

  return (
    <div className="studio-shell">
      <CommandBar
        config={studio.config}
        health={studio.health}
        jiraKey={studio.jiraKey}
        onJiraKeyChange={studio.setJiraKey}
        baseBranch={studio.baseBranch}
        onStart={studio.startWorkflow}
        onCreateJira={() => setCreateJiraOpen(true)}
        onReconfigure={studio.beginReconfigure}
        sessionSummary={studio.sessionSummary}
        busy={studio.busy}
        workflowState={studio.workflow?.state}
        showReport={canShowReport(studio.workflow)}
        reportPartial={studio.workflow?.state === "FAILED"}
        onViewReport={studio.openReport}
      />
      <WorkflowProgress config={studio.config} workflow={studio.workflow} deliveryComplete={studio.deliveryComplete} />
      {studio.error && <div className="banner error">{studio.error}</div>}
      {jiraSuccessNotice && <div className="banner success" role="status">{jiraSuccessNotice}</div>}
      <ModelSelectionPanel
        workflow={studio.workflow}
        selectedRoute={studio.selectedRoute}
        workBranch={studio.workBranch}
        onWorkBranchChange={studio.setWorkBranch}
        onSelectRoute={studio.setSelectedRoute}
        onConfirm={studio.confirmModel}
        busy={studio.busy}
      />
      <StageActivityCard
        workflow={studio.workflow}
        busy={studio.busy}
        onProceedPlan={studio.proceedPlan}
        onRegeneratePlan={studio.regeneratePlan}
      />
      <CompletionCard
        workflow={studio.workflow}
        onApprove={studio.approveWorkflow}
        onResume={studio.resumeWorkflow}
        onCheckJira={studio.checkJiraSync}
        onDeliveryComplete={studio.markDeliveryComplete}
        busy={studio.busy}
      />
      <div className="studio-grid">
        <FileTree workflow={studio.workflow} selectedFile={studio.selectedFile} onSelect={studio.setSelectedFile} />
        <div className="center-stack">
          <CodeEditor
            path={studio.selectedFile}
            content={
              studio.workflow?.generated_files.find((file) => file.path === studio.selectedFile)?.content ??
              studio.fileContent
            }
          />
          <TerminalPanel workflow={studio.workflow} />
        </div>
        <AgentActivityFeed workflow={studio.workflow} />
      </div>
      {studio.workflow && (
        <ImplementationReportModal
          workflow={studio.workflow}
          open={studio.reportOpen}
          onClose={studio.closeReport}
          onSelectFile={studio.viewReportFile}
        />
      )}
      <CreateJiraModal
        open={createJiraOpen}
        onClose={() => setCreateJiraOpen(false)}
        onCreated={(jiraKey, notice) => {
          studio.setJiraKey(jiraKey);
          if (notice) setJiraSuccessNotice(notice);
        }}
      />
    </div>
  );
}

export default StudioLayout;
