interface Props {
  text: string;
}

export default function StatusIndicator({ text }: Props) {
  return (
    <div className="status-indicator">
      <div className="status-dots">
        <span /><span /><span />
      </div>
      <span className="status-text">{text}</span>
    </div>
  );
}
