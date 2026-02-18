import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ReferenceCard from "./ReferenceCard";
import ThinkingBlock from "./ThinkingBlock";

interface Ref {
  num: string;
  url: string;
}

export interface ThinkingData {
  source: string;
  label: string;
  content: string;
}

interface Props {
  role: "user" | "assistant" | "tool";
  content: string;
  files?: string[];
  references?: Ref[];
  thinking?: ThinkingData[];
}

export default function MessageBubble({ role, content, files, references, thinking }: Props) {
  if (role === "tool") return null;

  return (
    <div className={`message ${role}`}>
      {thinking && thinking.length > 0 && (
        <div className="thinking-blocks">
          {thinking.map((t, i) => (
            <ThinkingBlock key={i} label={t.label} content={t.content} />
          ))}
        </div>
      )}
      <div className="message-content">
        {role === "assistant" ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        ) : (
          <p>{content}</p>
        )}

        {files && files.length > 0 && (
          <div className="message-files">
            {files.map((f, i) =>
              f.endsWith(".png") ? (
                <img key={i} src={f} alt="chart" className="chart-image" />
              ) : (
                <a key={i} href={f} target="_blank" rel="noopener noreferrer" className="file-link">
                  {f.split("/").pop()}
                </a>
              )
            )}
          </div>
        )}

        {references && references.length > 0 && <ReferenceCard references={references} />}
      </div>
    </div>
  );
}
