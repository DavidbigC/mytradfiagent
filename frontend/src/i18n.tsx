import React, { createContext, useContext, useState, useEffect, useCallback } from "react";

type Lang = "en" | "zh";

const translations = {
  // Login
  "app.title": { en: "Financial Research Agent", zh: "金融研究智能体" },
  "app.subtitle": { en: "AI-powered market analysis", zh: "AI驱动的市场分析" },
  "login.username": { en: "Username", zh: "用户名" },
  "login.password": { en: "Password", zh: "密码" },
  "login.signIn": { en: "Sign In", zh: "登录" },

  // Sidebar
  "sidebar.newChat": { en: "+ New Chat", zh: "+ 新对话" },
  "sidebar.debate": { en: "Hypothesis Debate", zh: "假设辩论" },
  "sidebar.delete": { en: "Delete", zh: "删除" },
  "sidebar.admin": { en: "Admin", zh: "管理" },
  "sidebar.logout": { en: "Logout", zh: "退出" },
  "sidebar.guide": { en: "User Guide", zh: "用户指南" },
  "sidebar.showcase": { en: "Agent Showcase", zh: "能力展示" },

  // Chat
  "chat.title": { en: "Financial Research Agent", zh: "金融研究智能体" },
  "chat.subtitle": { en: "Ask about stocks, funds, bonds, or any financial topic.", zh: "查询股票、基金、债券或任何金融话题" },
  "chat.placeholder": { en: "Ask a question... (Shift+Enter for new line)", zh: "输入问题... (Shift+Enter换行)" },
  "chat.send": { en: "Send", zh: "发送" },
  "chat.stop": { en: "Stop", zh: "停止" },
  "chat.connecting": { en: "Connecting...", zh: "连接中..." },
  "chat.debateStarting": { en: "Starting debate...", zh: "辩论启动中..." },

  // Debate modal
  "debate.title": { en: "Hypothesis Debate", zh: "假设辩论" },
  "debate.description": { en: "Enter an investment question. The system will form a hypothesis and run a multi-analyst debate with 4 AI analysts and a judge.", zh: "输入投资问题，系统将形成假设并由4位AI分析师和1位评审进行多方辩论。" },
  "debate.placeholder": { en: "e.g. Is AAPL worth buying? / MSFT vs GOOG / Will tech sector keep rising?", zh: "例如: 600036值得买吗？/ 招商银行 vs 工商银行 / 银行板块还会涨吗？" },
  "debate.cancel": { en: "Cancel", zh: "取消" },
  "debate.start": { en: "Start Debate", zh: "开始辩论" },

  // Reports panel
  "sidebar.reports": { en: "My Reports", zh: "我的报告" },
  "reports.title": { en: "My Reports", zh: "我的报告" },
  "reports.all": { en: "All", zh: "全部" },
  "reports.pdfs": { en: "PDFs", zh: "PDF" },
  "reports.charts": { en: "Charts", zh: "图表" },
  "reports.markdowns": { en: "Markdown", zh: "Markdown" },
  "reports.charts_interactive": { en: "Charts", zh: "互动图表" },
  "reports.empty": { en: "No reports yet", zh: "暂无报告" },
  "reports.from": { en: "from", zh: "来自" },

  // Thinking
  "thinking.show": { en: "show", zh: "展开" },
  "thinking.hide": { en: "hide", zh: "收起" },

  // References
  "references.title": { en: "References", zh: "参考来源" },

  // Admin
  "admin.tables": { en: "Tables", zh: "数据表" },
  "admin.query": { en: "SQL Query", zh: "SQL查询" },
  "admin.createAccount": { en: "Create Account", zh: "创建账号" },
  "admin.selectTable": { en: "Select a table", zh: "选择表" },
  "admin.loading": { en: "Loading...", zh: "加载中..." },
  "admin.noRows": { en: "No rows", zh: "无数据" },
  "admin.prev": { en: "Prev", zh: "上一页" },
  "admin.next": { en: "Next", zh: "下一页" },
  "admin.runQuery": { en: "Run Query", zh: "执行查询" },
  "admin.running": { en: "Running...", zh: "执行中..." },
  "admin.queryHint": { en: "Ctrl+Enter to run. Read-only (SELECT/WITH/EXPLAIN).", zh: "Ctrl+Enter执行，仅支持只读查询。" },
  "admin.username": { en: "Username", zh: "用户名" },
  "admin.displayName": { en: "Display Name (optional)", zh: "显示名称（可选）" },
  "admin.passwordHint": { en: "Password (min 6 chars)", zh: "密码（至少6位）" },
} as const;

type Key = keyof typeof translations;

interface LangState {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: Key) => string;
}

const LangContext = createContext<LangState>({
  lang: "zh",
  setLang: () => { },
  t: (key) => key,
});

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(
    () => (localStorage.getItem("lang") as Lang) || "zh"
  );

  const setLang = useCallback((l: Lang) => {
    localStorage.setItem("lang", l);
    setLangState(l);
  }, []);

  const t = useCallback((key: Key) => translations[key]?.[lang] ?? key, [lang]);

  return (
    <LangContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LangContext.Provider>
  );
}

export function useT() {
  return useContext(LangContext);
}

// ── Theme ──────────────────────────────────────────────────────────────────────

type Theme = "light" | "dark";

interface ThemeState {
  theme: Theme;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeState>({
  theme: "light",
  toggleTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) || "light"
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
