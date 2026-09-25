import { useEffect, useState } from "react";
import { api } from "../api";
import type { LLMConfigurationSnapshot, LLMProviderModelsResponse } from "../types";

type Props = {
  onClose: () => void;
};

export function ModelConfigurationPanel({ onClose }: Props) {
  const [provider, setProvider] = useState("groq");
  const [config, setConfig] = useState<LLMConfigurationSnapshot | null>(null);
  const [models, setModels] = useState<LLMProviderModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([api.llmConfiguration(), api.llmProviderModels(provider)])
      .then(([snapshot, discovered]) => {
        if (cancelled) return;
        setConfig(snapshot);
        setModels(discovered);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [provider]);

  const groq = config?.providers.groq;
  const routing = config?.model_routing ?? [];

  return (
    <section className="model-config-panel">
      <div className="model-config-header">
        <div>
          <p className="eyebrow">Provider & routing</p>
          <h2 id="model-config-title">Model configuration</h2>
        </div>
        <button type="button" className="ghost small" onClick={onClose} aria-label="Close">
          Close
        </button>
      </div>

      <div className="setup-grid model-config-provider">
        <label>
          Provider
          <select value={provider} onChange={(event) => setProvider(event.target.value)}>
            <option value="groq">Groq</option>
          </select>
        </label>
      </div>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="banner error">{error}</p>}

      {config && (
        <table className="config-table">
          <thead>
            <tr>
              <th>Setting</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>API keys (ids)</td>
              <td>{(groq?.key_chain_ids ?? []).join(", ") || "—"}</td>
            </tr>
            <tr>
              <td>Default model</td>
              <td>{groq?.configured_models.default ?? "—"}</td>
            </tr>
          </tbody>
        </table>
      )}

      <label className="model-config-toggle">
        <input type="checkbox" checked={showDetails} onChange={(event) => setShowDetails(event.target.checked)} />
        <span>Show routing & discovered models</span>
      </label>

      {showDetails && config && (
        <>
          <table className="config-table">
            <thead>
              <tr>
                <th>Tier</th>
                <th>Model</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Low / medium / high</td>
                <td>
                  {groq?.configured_models.low} · {groq?.configured_models.medium} · {groq?.configured_models.high}
                </td>
              </tr>
            </tbody>
          </table>

          {routing.length > 0 && (
            <>
              <h4>Complexity routing</h4>
              <table className="config-table">
                <thead>
                  <tr>
                    <th>Score</th>
                    <th>Provider</th>
                    <th>Model</th>
                    <th>Max tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {routing.map((route) => (
                    <tr key={`${route.complexity_min}-${route.complexity_max}-${route.model}`}>
                      <td>
                        {route.complexity_min}–{route.complexity_max}
                      </td>
                      <td>{route.provider}</td>
                      <td>{route.model}</td>
                      <td>{route.max_tokens}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {models && (
            <>
              <h4>Discovered models</h4>
              <div className="model-config-scroll">
                <table className="config-table">
                  <thead>
                    <tr>
                      <th>Model id</th>
                      <th>Active</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.models.map((row) => (
                      <tr key={row.id}>
                        <td>{row.id}</td>
                        <td>{row.active === false ? "no" : "yes"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
