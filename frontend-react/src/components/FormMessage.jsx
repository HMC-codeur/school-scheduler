export function FormMessage({ message }) {
  if (!message?.text) {
    return null;
  }

  return <div className={`notice ${message.type === "error" ? "danger" : ""}`}>{message.text}</div>;
}
