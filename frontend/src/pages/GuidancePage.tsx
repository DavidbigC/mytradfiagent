import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useT } from "../i18n";

const GuidancePage: React.FC = () => {
    const { lang } = useT();

    const contentEn = `
# Financial Research Agent - User Guide

Welcome to the **Financial Research Agent**, your AI-powered assistant for deep market analysis and investment research. This guide covers how to access the platform, navigate the interface, and utilize its advanced debate capabilities.

## 1. Access & Login

**URL**: [http://154.64.240.10:8000/](http://154.64.240.10:8000/)

To access the platform, you will need a registered account. For demonstration purposes, you can use the following credentials:
- **Username**: \`showcase\`
- **Password**: \`showcase\`

## 2. Interface Overview

Once logged in, you will see the main chat interface. The design is clean and focused on financial inquiry.

![Main Interface](/images/main_chat_interface_1771507684537.png)

### Navigation (Sidebar)
The left sidebar provides access to the core modules:
- **+ New Chat**: Clears the context and starts a fresh conversation.
- **Hypothesis Debate**: Opens the advanced multi-agent debate tool (see section 3).
- **My Reports**: Access your history of generated analysis reports.
- **User Profile**: View current user and logout option.
- **Language**: Toggle the UI language between English and Chinese.

## 3. Key Features

### 💬 Financial Chat
The central chat window is your primary workspace. You can ask natural language questions about:
- **Real-time Data**: "What is the current price of AAPL?" or "Start a market scan."
- **Company Research**: "Analyze the latest earnings for Tencent (0700.HK)."
- **Comparisons**: "Compare the dividend yield of Coca-Cola vs. Pepsi."

**Pro Tip**: For simple data lookups, just ask directly. The agent will fetch live data from financial APIs.

### ⚖️ Hypothesis Debate (Deep Analysis)
This is the agent's most powerful feature. Instead of a single answer, it orchestrates a debate between 4 AI analysts (Bull vs. Bear) to verify an investment thesis.

1. Click the **Hypothesis Debate** button in the sidebar.
2. The debate configuration modal will appear.

![Debate Modal](/images/debate_modal_1771507812053.png)

3. **Enter your Hypothesis**: Type a specific investment question or thesis.
   - *Example*: "Is China Merchants Bank (600036) a good buy right now?"
   - *Example*: "Will the AI sector continue to rally in Q3?"
4. Click **Start Debate**.

The system will then:
- Use **4 independent AI analysts** to research data.
- Conduct a round-table debate.
- Have a "Judge" AI synthesize the findings into a final report with a conviction score.

## 4. Best Practices
- **Be Specific**: Include stock codes (e.g., "600519") for better accuracy with A-share stocks.
- **Use the Debate for Decisions**: Don't rely on the simple chat for complex investment decisions; use the Debate mode to see both sides of the argument.
- **Check Sources**: All data responses include citations. Always verify critical financial data.
`;

    const contentZh = `
# 金融研究智能体 - 用户指南

欢迎使用 **金融研究智能体 (Financial Research Agent)**。这是一个由AI驱动的助手，致力于深度市场分析和投资研究。本指南涵盖如何访问平台、导航界面以及使用高级辩论功能。

## 1. 访问与登录

**网址**: [http://154.64.240.10:8000/](http://154.64.240.10:8000/)

访问平台需要注册账号。演示账号如下：
- **用户名**: \`showcase\`
- **密码**: \`showcase\`

## 2. 界面概览

登录后，您将看到主聊天界面。设计简洁，专注于金融问答。

![主界面](/images/main_chat_interface_1771507684537.png)

### 导航栏 (左侧)
侧边栏提供核心模块的访问：
- **+ 新对话**: 清空上下文并开始新对话。
- **假设辩论**: 打开高级多智能体辩论工具（见第3节）。
- **我的报告**: 查看您生成的分析报告历史。
- **用户资料**: 查看当前用户及退出选项。
- **语言**: 切换中英文界面。

## 3. 核心功能

### 💬 金融对话
中央聊天窗口是您的主要工作区。您可以询问自然语言问题，例如：
- **实时数据**: "苹果现在的股价是多少？" 或 "开始市场扫描。"
- **公司研究**: "分析腾讯 (0700.HK) 最新的财报。"
- **比较分析**: "对比可口可乐和百事的股息率。"

**小贴士**: 简单的查询直接提问即可，智能体会从金融API获取实时数据。

### ⚖️ 假设辩论 (深度分析)
这是智能体最强大的功能。它不仅仅给出单一答案，而是组织4位AI分析师（多空双方）进行辩论，以验证投资论点。

1. 点击侧边栏的 **假设辩论** 按钮。
2. 辩论配置窗口将弹出。

![辩论窗口](/images/debate_modal_1771507812053.png)

3. **输入您的假设**: 输入具体的投资问题或论点。
   - *例如*: "招商银行 (600036) 现在值得买入吗？"
   - *例如*: "AI板块在三季度还会继续上涨吗？"
4. 点击 **开始辩论**。

系统将：
- 调度 **4位独立的AI分析师** 调研数据。
- 进行圆桌辩论。
- 由"裁判"AI综合发现，生成带有确信度评分的最终报告。

## 4. 最佳实践
- **具体明确**: 包含股票代码（如 "600519"）以提高准确性。
- **决策辅助**: 不要依赖简单对话做复杂投资决策；使用辩论模式查看正反两面的观点。
- **核对来源**: 所有数据回复均包含引用。请务必核对关键财务数据。
`;

    const content = lang === "zh" ? contentZh : contentEn;

    return (
        <div className="guidance-page" style={{
            maxWidth: "800px",
            margin: "0 auto",
            padding: "40px 20px",
            lineHeight: "1.6",
            color: "var(--text-primary)"
        }}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                    h1: ({ node, ...props }) => <h1 style={{ color: "var(--accent)", borderBottom: "1px solid var(--border)", paddingBottom: "10px", marginBottom: "24px" }} {...props} />,
                    h2: ({ node, ...props }) => <h2 style={{ color: "var(--text-primary)", marginTop: "32px", marginBottom: "16px" }} {...props} />,
                    h3: ({ node, ...props }) => <h3 style={{ color: "var(--text-secondary)", marginTop: "24px", marginBottom: "12px" }} {...props} />,
                    p: ({ node, ...props }) => <p style={{ marginBottom: "16px" }} {...props} />,
                    ul: ({ node, ...props }) => <ul style={{ paddingLeft: "24px", marginBottom: "16px" }} {...props} />,
                    li: ({ node, ...props }) => <li style={{ marginBottom: "8px" }} {...props} />,
                    img: ({ node, ...props }) => (
                        <div style={{ margin: "24px 0", border: "1px solid var(--border)", borderRadius: "8px", overflow: "hidden", boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}>
                            <img style={{ display: "block", maxWidth: "100%", height: "auto" }} {...props} />
                        </div>
                    ),
                    code: ({ node, inline, className, children, ...props }: any) => (
                        <code style={{
                            background: "var(--bg-tertiary)",
                            padding: inline ? "2px 6px" : "12px",
                            borderRadius: "4px",
                            fontFamily: "monospace",
                            display: inline ? "inline" : "block",
                            overflowX: "auto"
                        }} {...props}>
                            {children}
                        </code>
                    ),
                    a: ({ node, ...props }) => <a style={{ color: "var(--accent)", textDecoration: "underline" }} {...props} />
                }}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
};

export default GuidancePage;
