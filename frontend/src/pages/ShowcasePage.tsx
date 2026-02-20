import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { showcaseData } from "../data/showcaseData";
import { useT } from "../i18n";

const ShowcasePage: React.FC = () => {
    const { lang, t } = useT();
    const [expandedId, setExpandedId] = useState<string | null>(null);

    const toggleExpand = (id: string) => {
        setExpandedId(expandedId === id ? null : id);
    };

    return (
        <div className="showcase-page" style={{
            maxWidth: "900px",
            margin: "0 auto",
            padding: "40px 20px",
            color: "var(--text-primary)"
        }}>
            <header style={{ marginBottom: "40px", textAlign: "center" }}>
                <h1 style={{ color: "var(--accent)", marginBottom: "12px", fontSize: "2rem" }}>
                    {lang === "zh" ? "A股投资洞察展示" : "A-Share Investment Insights Showcase"}
                </h1>
                <p style={{ color: "var(--text-secondary)", fontSize: "1.1rem" }}>
                    {lang === "zh"
                        ? "专家级分析、高股息策略及行业深度研究。"
                        : "Expert analysis, high-dividend strategies, and deep sector research."}
                </p>
            </header>

            <div className="faq-list" style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                {showcaseData.map((item) => (
                    <div key={item.id} className="faq-item" style={{
                        border: "1px solid var(--border)",
                        borderRadius: "8px",
                        background: "var(--bg-secondary)",
                        overflow: "hidden",
                        transition: "box-shadow 0.2s ease"
                    }}>
                        <button
                            onClick={() => toggleExpand(item.id)}
                            style={{
                                width: "100%",
                                padding: "20px 24px",
                                textAlign: "left",
                                background: "none",
                                border: "none",
                                fontSize: "1.1rem",
                                fontWeight: "600",
                                color: "var(--text-primary)",
                                cursor: "pointer",
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center"
                            }}
                        >
                            <span>{item.question[lang]}</span>
                            <span style={{
                                transform: expandedId === item.id ? "rotate(180deg)" : "rotate(0deg)",
                                transition: "transform 0.3s ease",
                                color: "var(--accent)"
                            }}>
                                ▼
                            </span>
                        </button>

                        {expandedId === item.id && (
                            <div className="faq-answer" style={{
                                padding: "0 24px 24px 24px",
                                borderTop: "1px solid var(--border)",
                                background: "var(--bg-primary)",
                                lineHeight: "1.7"
                            }}>
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={{
                                        h1: ({ node, ...props }) => <h3 style={{ color: "var(--accent)", marginTop: "20px", marginBottom: "12px", fontSize: "1.3rem" }} {...props} />,
                                        h2: ({ node, ...props }) => <h4 style={{ color: "var(--text-primary)", marginTop: "16px", marginBottom: "10px", fontSize: "1.1rem" }} {...props} />,
                                        h3: ({ node, ...props }) => <h5 style={{ color: "var(--text-secondary)", marginTop: "12px", marginBottom: "8px", fontSize: "1rem", fontWeight: "bold" }} {...props} />,
                                        p: ({ node, ...props }) => <p style={{ marginBottom: "12px" }} {...props} />,
                                        table: ({ node, ...props }) => (
                                            <div style={{ overflowX: "auto", margin: "16px 0", border: "1px solid var(--border)", borderRadius: "6px" }}>
                                                <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "600px" }} {...props} />
                                            </div>
                                        ),
                                        thead: ({ node, ...props }) => <thead style={{ background: "var(--bg-tertiary)" }} {...props} />,
                                        th: ({ node, ...props }) => <th style={{ padding: "10px", textAlign: "left", borderBottom: "1px solid var(--border)", color: "var(--accent)", fontWeight: "600" }} {...props} />,
                                        td: ({ node, ...props }) => <td style={{ padding: "10px", borderBottom: "1px solid var(--border)", color: "var(--text-primary)" }} {...props} />,
                                        ul: ({ node, ...props }) => <ul style={{ paddingLeft: "24px", marginBottom: "12px" }} {...props} />,
                                        li: ({ node, ...props }) => <li style={{ marginBottom: "4px" }} {...props} />,
                                        strong: ({ node, ...props }) => <strong style={{ color: "var(--text-primary)", fontWeight: "700" }} {...props} />,
                                    }}
                                >
                                    {item.answer[lang]}
                                </ReactMarkdown>
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
};

export default ShowcasePage;
