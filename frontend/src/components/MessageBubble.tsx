import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ReferenceCard from "./ReferenceCard";
import ThinkingBlock from "./ThinkingBlock";
import { useAuth } from "../store";

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
  const { token } = useAuth();
  if (role === "tool") return null;

  function handleDownload(url: string, filename: string) {
    if (!token) return;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (!res.ok) throw new Error("Download failed");
        return res.blob();
      })
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch(() => {});
  }

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
            {files.map((f, i) => {
              const filename = f.split("/").pop() || f;
              if (f.endsWith(".png")) {
                return <img key={i} src={`${f}?token=${token}`} alt="chart" className="chart-image" />;
              }
              return (
                <a
                  key={i}
                  href="#"
                  onClick={(e) => { e.preventDefault(); handleDownload(f, filename); }}
                  className="file-link"
                >
                  {filename}
                </a>
              );
            })}
          </div>
        )}

        {references && references.length > 0 && <ReferenceCard references={references} />}
      </div>
    </div>
  );
}
