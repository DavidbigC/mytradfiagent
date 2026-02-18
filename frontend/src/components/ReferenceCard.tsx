import { useT } from "../i18n";

interface Ref {
  num: string;
  url: string;
}

interface Props {
  references: Ref[];
}

export default function ReferenceCard({ references }: Props) {
  const { t } = useT();
  const validRefs = references.filter((r) => r.url && r.url.startsWith("http"));
  if (!validRefs.length) return null;

  return (
    <div className="reference-card">
      <div className="ref-header">{t("references.title")}</div>
      {validRefs.map((r) => (
        <div key={r.num} className="ref-item">
          <span className="ref-num">[{r.num}]</span>
          <a href={r.url} target="_blank" rel="noopener noreferrer" className="ref-url">
            {r.url.length > 80 ? r.url.slice(0, 80) + "..." : r.url}
          </a>
        </div>
      ))}
    </div>
  );
}
