interface Props {
  text: string;
}

export default function StatusIndicator({ text }: Props) {
  // Parse "ModelName · status text" format
  const sepIdx = text.indexOf(" · ");
  const model = sepIdx !== -1 ? text.slice(0, sepIdx) : null;
  const statusText = sepIdx !== -1 ? text.slice(sepIdx + 3) : text;

  return (
    <div className="status-indicator">
      <div className="status-dots">
        <span /><span /><span />
      </div>
      {model && <span className="status-model">{model}</span>}
      <span className="status-text">{statusText}</span>
    </div>
  );
}
