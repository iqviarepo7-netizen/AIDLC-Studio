import { useCallback, useEffect, useState } from "react";
import { api, setSessionId } from "../api";
import type { HealthStatus, PublicConfig, SetupRequest, SetupResponse, SetupSummary, Workflow } from "../types";

export type AppPhase = "welcome" | "booting" | "setup" | "connected" | "studio" | "reconfigure-choice";

export function useStudio() {
  const [phase, setPhase] = useState<AppPhase>("welcome");
  const [config, setConfig] = useState<PublicConfig>();
  const [health, setHealth] = useState<HealthStatus>();
  const [setupResult, setSetupResult] = useState<SetupResponse>();
  const [sessionSummary, setSessionSummary] = useState<SetupSummary>();
  const [jiraKey, setJiraKey] = useState("");
  const [branches, setBranches] = useState<string[]>([]);
  const [baseBranch, setBaseBranch] = useState("");
  const [workflow, setWorkflow] = useState<Workflow>();
  const [selectedFile, setSelectedFile] = useState<string>();
  const [fileContent, setFileContent] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [selectedRoute, setSelectedRoute] = useState<string>();
  const [workBranch, setWorkBranch] = useState("");
  const [setupDraft, setSetupDraft] = useState<SetupRequest>();
  const [deliveryComplete, setDeliveryComplete] = useState(false);

  useEffect(() => {
    api
      .publicConfig()
      .then((publicConfig) => {
        setConfig(publicConfig);
        applyTheme(publicConfig.theme);
        if (publicConfig.default_base_branch) setBaseBranch(publicConfig.default_base_branch);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Failed to load configuration."));
  }, []);

  useEffect(() => {
    if (phase !== "studio" && phase !== "connected") return;
    api.health().then(setHealth).catch(() => undefined);
  }, [phase]);

  useEffect(() => {
    if (phase !== "studio") return;
    api
      .branches()
      .then((response) => {
        setBranches(response.branches);
        setBaseBranch((current) => current || response.default_branch);
      })
      .catch(() => undefined);
  }, [phase]);

  useEffect(() => {
    if (workflow?.model_recommendation?.recommended_model_id) {
      setSelectedRoute(workflow.model_recommendation.recommended_model_id);
    }
    if (workflow?.branch_analysis?.suggested_work_branch) {
      setWorkBranch(workflow.branch_analysis.suggested_work_branch);
    }
  }, [workflow?.id, workflow?.model_recommendation?.recommended_model_id, workflow?.branch_analysis?.suggested_work_branch]);

  useEffect(() => {
    if (!workflow?.id) return;
    return api.subscribeWorkflow(workflow.id, (updated) => {
      setWorkflow(updated);
      if (updated.generated_files[0]) {
        setSelectedFile((current) => current ?? updated.generated_files[0].path);
      }
    });
  }, [workflow?.id]);

  useEffect(() => {
    if (!workflow || !selectedFile) return;
    api.file(workflow.id, selectedFile).then(setFileContent).catch((cause) => setError(cause instanceof Error ? cause.message : "Failed to load file."));
  }, [workflow, selectedFile]);

  const beginBoot = useCallback(() => {
    setError(undefined);
    setPhase("booting");
  }, []);

  const finishBoot = useCallback(() => {
    setPhase("setup");
  }, []);

  const submitSetup = useCallback(async (payload: SetupRequest) => {
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.validateSetup(payload);
      setSetupDraft(payload);
      setSessionId(result.session_id);
      setSetupResult(result);
      setSessionSummary(result.summary);
      setBranches(result.branches);
      setBaseBranch(result.default_branch);
      setPhase("connected");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Setup validation failed.");
    } finally {
      setBusy(false);
    }
  }, []);

  const enterStudio = useCallback(() => {
    setPhase("studio");
  }, []);

  const beginReconfigure = useCallback(() => {
    setError(undefined);
    setPhase("reconfigure-choice");
  }, []);

  const cancelReconfigure = useCallback(() => {
    setPhase(workflow ? "studio" : setupResult ? "connected" : "welcome");
  }, [setupResult, workflow]);

  const reconfigureEdit = useCallback(async () => {
    setBusy(true);
    setError(undefined);
    try {
      setSetupDraft(await api.sessionConfig());
      setPhase("setup");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load session settings.");
    } finally {
      setBusy(false);
    }
  }, []);

  const reconfigureRefill = useCallback(() => {
    setSessionId(undefined);
    setSetupResult(undefined);
    setSessionSummary(undefined);
    setSetupDraft(undefined);
    setWorkflow(undefined);
    setPhase("setup");
  }, []);

  const resetSession = useCallback(() => {
    setSessionId(undefined);
    setSetupResult(undefined);
    setSessionSummary(undefined);
    setSetupDraft(undefined);
    setWorkflow(undefined);
    setJiraKey("");
    setBranches([]);
    setWorkBranch("");
    setPhase("welcome");
  }, []);

  const reconfigure = reconfigureRefill;

  const startWorkflow = useCallback(async () => {
    setBusy(true);
    setError(undefined);
    try {
      const created = await api.create(jiraKey.trim().toUpperCase(), baseBranch || undefined);
      setDeliveryComplete(false);
      setWorkflow(created);
      if (!selectedFile && created.generated_files[0]) setSelectedFile(created.generated_files[0].path);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to start workflow.");
    } finally {
      setBusy(false);
    }
  }, [jiraKey, baseBranch, selectedFile]);

  const confirmModel = useCallback(async () => {
    if (!workflow || !selectedRoute) return;
    setBusy(true);
    setError(undefined);
    try {
      setWorkflow(await api.selectModel(workflow.id, selectedRoute, workBranch.trim() || undefined));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Model selection failed.");
    } finally {
      setBusy(false);
    }
  }, [workflow, selectedRoute, workBranch]);

  const approveWorkflow = useCallback(async () => {
    if (!workflow) return;
    setBusy(true);
    setError(undefined);
    try {
      setWorkflow(await api.approve(workflow.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Approval failed.");
    } finally {
      setBusy(false);
    }
  }, [workflow]);

  const resumeWorkflow = useCallback(async () => {
    if (!workflow) return;
    setBusy(true);
    setError(undefined);
    try {
      const updated = await api.resume(workflow.id);
      setWorkflow(updated);
      if (updated.generated_files[0]) setSelectedFile(updated.generated_files[0].path);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Resume failed.");
    } finally {
      setBusy(false);
    }
  }, [workflow]);

  const checkJiraSync = useCallback(async () => {
    if (!workflow) return false;
    const result = await api.jiraSync(workflow.id);
    return result.flow_complete;
  }, [workflow]);

  const markDeliveryComplete = useCallback(() => setDeliveryComplete(true), []);

  const proceedPlan = useCallback(async () => {
    if (!workflow) return;
    setBusy(true);
    setError(undefined);
    try {
      setWorkflow(await api.proceedPlan(workflow.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not continue with the plan.");
    } finally {
      setBusy(false);
    }
  }, [workflow]);

  const regeneratePlan = useCallback(async () => {
    if (!workflow) return;
    setBusy(true);
    setError(undefined);
    try {
      setWorkflow(await api.regeneratePlan(workflow.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not regenerate the plan.");
    } finally {
      setBusy(false);
    }
  }, [workflow]);

  return {
    phase,
    config,
    health,
    setupResult,
    sessionSummary,
    jiraKey,
    setJiraKey,
    branches,
    baseBranch,
    setBaseBranch,
    workflow,
    selectedFile,
    setSelectedFile,
    fileContent,
    error,
    busy,
    selectedRoute,
    setSelectedRoute,
    workBranch,
    setWorkBranch,
    beginBoot,
    finishBoot,
    submitSetup,
    setupDraft,
    beginReconfigure,
    cancelReconfigure,
    reconfigureEdit,
    reconfigureRefill,
    enterStudio,
    resetSession,
    reconfigure,
    startWorkflow,
    confirmModel,
    approveWorkflow,
    resumeWorkflow,
    checkJiraSync,
    deliveryComplete,
    markDeliveryComplete,
    proceedPlan,
    regeneratePlan,
  };
}

function applyTheme(theme: Record<string, string>) {
  const root = document.documentElement;
  Object.entries(theme).forEach(([key, value]) => root.style.setProperty(`--${key.replace(/_/g, "-")}`, value));
}
