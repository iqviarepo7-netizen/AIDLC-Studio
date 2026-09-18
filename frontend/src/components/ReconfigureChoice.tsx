type Props = {
  onEdit: () => void;
  onRefill: () => void;
  onCancel: () => void;
  busy?: boolean;
};

export function ReconfigureChoice({ onEdit, onRefill, onCancel, busy }: Props) {
  return (
    <div className="setup-overlay">
      <div className="connection-card reconfigure-card">
        <p className="eyebrow">Reconfigure</p>
        <h2>Edit or start fresh?</h2>
        <p className="muted">Edit keeps your current Jira and Git settings prefilled. Refill clears the form for a new setup.</p>
        <div className="connection-actions">
          <button onClick={onEdit} disabled={busy}>Edit existing</button>
          <button className="ghost" onClick={onRefill} disabled={busy}>Refill form</button>
          <button className="ghost" onClick={onCancel} disabled={busy}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
