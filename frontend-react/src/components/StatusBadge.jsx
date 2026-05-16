export function StatusBadge({ status = "neutral", children }) {
  return <span className={`status-badge ${status}`}>{children}</span>;
}
