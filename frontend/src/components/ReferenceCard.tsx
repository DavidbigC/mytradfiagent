interface Ref {
  num: string;
  name: string;
  url: string;
}

interface Props {
  references: Ref[];
}

export default function ReferenceCard({ references }: Props) {
  if (!references.length) return null;

  return (
    <div className="reference-card">
      <div className="ref-header">References</div>
      {references.map((r) => (
        <div key={r.num} className="ref-item">
          <span className="ref-num">[{r.num}]</span>
          <span className="ref-name">{r.name}</span>
          {r.url && r.url !== "(tool data)" && (
            <a href={r.url} target="_blank" rel="noopener noreferrer" className="ref-url">
              {r.url.length > 60 ? r.url.slice(0, 60) + "..." : r.url}
            </a>
          )}
        </div>
      ))}
    </div>
  );
}
