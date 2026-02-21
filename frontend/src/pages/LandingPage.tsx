import { useNavigate } from "react-router-dom";
import { useT, useTheme } from "../i18n";
import "../styles/landing.css";

const TICKER = [
  { code: "600036", name: "招商银行", price: "38.42", change: "+1.23%", up: true },
  { code: "600519", name: "贵州茅台", price: "1582.00", change: "-0.32%", up: false },
  { code: "000858", name: "五粮液", price: "124.50", change: "+0.85%", up: true },
  { code: "000333", name: "美的集团", price: "51.28", change: "+2.14%", up: true },
  { code: "601318", name: "中国平安", price: "45.76", change: "-0.78%", up: false },
  { code: "002415", name: "海康威视", price: "32.90", change: "+1.45%", up: true },
  { code: "600276", name: "恒瑞医药", price: "44.15", change: "+0.23%", up: true },
  { code: "000001", name: "平安银行", price: "12.34", change: "-0.56%", up: false },
  { code: "300750", name: "宁德时代", price: "198.60", change: "+3.12%", up: true },
  { code: "601166", name: "兴业银行", price: "22.18", change: "-0.45%", up: false },
];

const FEATURES = [
  {
    icon: "🎙",
    title: { zh: "语音股票识别", en: "Voice Stock Recognition" },
    desc: {
      zh: "说出股票名称，AI自动识别并匹配A股代码，智能纠正语音识别偏差",
      en: "Speak any stock name in Mandarin. AI resolves it to the exact A-share code, correcting Whisper recognition errors automatically.",
    },
  },
  {
    icon: "📊",
    title: { zh: "深度研究分析", en: "Deep Research Analysis" },
    desc: {
      zh: "实时行情、财务数据、年报解读，多数据源综合分析，专业投研级输出",
      en: "Real-time quotes, financial data, and annual report analysis from multiple sources — research-grade output.",
    },
  },
  {
    icon: "⚖️",
    title: { zh: "多方辩论模式", en: "Multi-Analyst Debate" },
    desc: {
      zh: "4位AI分析师围绕投资假设展开辩论，1位评审综合裁定，全面评估投资逻辑",
      en: "4 AI analysts debate your investment hypothesis from opposing sides, with an impartial judge delivering a verdict.",
    },
  },
  {
    icon: "📑",
    title: { zh: "研究报告生成", en: "Research Report Generation" },
    desc: {
      zh: "自动生成结构化PDF研究报告，图表与分析一键导出，可直接用于投资决策",
      en: "Auto-generate structured PDF research reports with charts — exportable and ready for investment decision-making.",
    },
  },
];

const SAMPLE = {
  query: {
    zh: "帮我分析一下招商银行(600036.SH)近期的投资价值",
    en: "Analyze the investment value of China Merchants Bank (600036.SH)",
  },
  answer: {
    zh: `招商银行 (600036.SH)  ·  投资价值分析

核心指标
  市盈率 (PE)    7.8x       行业均值 6.2x
  股息收益率     4.8%       近5年平均
  净资产收益率   16.2%      连续8年高于15%
  不良贷款率     0.95%      行业最优水平

优势分析
招商银行以"零售之王"著称，个人存款占比达54%，资产质量优异。数字化转型领先同业，掌上生活月活突破1.1亿。中间业务收入占比持续提升，盈利结构更为多元。

风险提示
地产敞口约5.8%，需关注政策利率下行对净息差的压缩效应。

综合评估
当前估值处于历史低位区间 (PB 0.9x)，适合寻求稳定红利+价值修复的长期投资者。`,
    en: `China Merchants Bank (600036.SH)  ·  Investment Analysis

Key Metrics
  P/E Ratio        7.8x     Sector avg 6.2x
  Dividend Yield   4.8%     5-year average
  ROE              16.2%    Above 15% for 8 consecutive years
  NPL Ratio        0.95%    Best-in-class

Strengths
Known as the "King of Retail Banking", personal deposits account for 54% of total. Leading digital transformation with 110M+ monthly active users. Growing fee income diversifies revenue mix beyond net interest.

Risk Factors
Real estate exposure ~5.8%. Watch for NIM compression from policy rate cuts.

Overall View
Valuation at historical lows (PB 0.9x) — suited for long-term investors seeking stable dividends and value recovery.`,
  },
};

export default function LandingPage() {
  const navigate = useNavigate();
  const { lang, setLang } = useT();
  const { theme, toggleTheme } = useTheme();

  const doubled = [...TICKER, ...TICKER];

  return (
    <div className="landing-page">

      {/* ── Nav ── */}
      <nav className="landing-nav">
        <span className="landing-logo">金融研究智能体</span>
        <div className="landing-nav-right">
          <button
            className="landing-lang-toggle"
            onClick={toggleTheme}
            title={theme === "light" ? "Switch to dark" : "Switch to light"}
          >
            {theme === "light" ? "🌙" : "☀"}
          </button>
          <button
            className="landing-lang-toggle"
            onClick={() => setLang(lang === "zh" ? "en" : "zh")}
          >
            {lang === "zh" ? "EN" : "中文"}
          </button>
          <button className="landing-nav-btn" onClick={() => navigate("/login")}>
            {lang === "zh" ? "登录" : "Sign In"}
          </button>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="landing-hero">
        <div className="landing-hero-grid" />
        <div className="landing-hero-glow" />

        <div className="landing-badge">
          <span className="badge-dot" />
          {lang === "zh" ? "A股智能研究平台" : "A-Share AI Research Platform"}
        </div>

        <h1 className="landing-title-zh">
          {lang === "zh" ? "金融研究智能体" : "Financial Research Agent"}
        </h1>
        <p className="landing-title-en">
          {lang === "zh" ? "AI Financial Research Agent" : "AI驱动的A股研究平台"}
        </p>
        <p className="landing-subtitle">
          {lang === "zh"
            ? "语音输入、深度分析、多方辩论，一站式中国A股投资研究助手。"
            : "Voice input, deep analysis, multi-analyst debate — your all-in-one Chinese A-share investment research assistant."}
        </p>

        <div className="landing-cta-row">
          <button className="landing-cta-primary" onClick={() => navigate("/login")}>
            {lang === "zh" ? "进入平台" : "Enter Platform"} →
          </button>
          <button className="landing-cta-secondary" onClick={() => navigate("/showcase")}>
            {lang === "zh" ? "查看示例" : "View Showcase"}
          </button>
        </div>

        {/* Ticker */}
        <div className="landing-ticker">
          <div className="landing-ticker-track">
            {doubled.map((t, i) => (
              <span key={i} className="landing-ticker-item">
                <span className="t-code">{t.code}</span>
                <span className="t-name">{t.name}</span>
                <span className="t-price">{t.price}</span>
                <span className={t.up ? "t-up" : "t-down"}>{t.change}</span>
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="landing-features">
        <p className="landing-section-eyebrow">
          {lang === "zh" ? "核心能力" : "Capabilities"}
        </p>
        <h2 className="landing-section-title">
          {lang === "zh" ? "专为A股投资研究而生" : "Built for A-Share Research"}
        </h2>
        <div className="landing-features-grid">
          {FEATURES.map((f, i) => (
            <div key={i} className="landing-feature-card">
              <span className="landing-feature-icon">{f.icon}</span>
              <div className="landing-feature-title">{f.title[lang]}</div>
              <div className="landing-feature-desc">{f.desc[lang]}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Sample Analysis ── */}
      <section className="landing-sample">
        <p className="landing-section-eyebrow">
          {lang === "zh" ? "实际效果" : "See It in Action"}
        </p>
        <h2 className="landing-section-title" style={{ fontFamily: "'Georgia', 'Noto Serif SC', serif" }}>
          {lang === "zh" ? "专业级投资分析" : "Professional-Grade Analysis"}
        </h2>
        <div className="landing-sample-window">
          <div className="sample-titlebar">
            <div className="sample-dot" style={{ background: "#f0ebe0" }} />
            <div className="sample-dot" style={{ background: "#d4cbb8" }} />
            <div className="sample-dot" style={{ background: "#c5ba9e" }} />
            <span className="sample-title">金融研究智能体</span>
          </div>
          <div className="sample-query">
            <span className="sample-query-icon">›</span>
            {SAMPLE.query[lang]}
          </div>
          <div className="sample-answer">{SAMPLE.answer[lang]}</div>
        </div>
      </section>

      {/* ── CTA Band ── */}
      <section className="landing-cta-band">
        <h2 className="landing-cta-band-title">
          {lang === "zh" ? "开始您的研究之旅" : "Start Your Research Journey"}
        </h2>
        <p className="landing-cta-band-sub">
          {lang === "zh"
            ? "登录即可使用全部功能，无需任何配置"
            : "Sign in to access all features — no configuration required"}
        </p>
        <button
          className="landing-cta-primary"
          style={{ position: "relative" }}
          onClick={() => navigate("/login")}
        >
          {lang === "zh" ? "立即登录" : "Sign In Now"} →
        </button>
      </section>

      {/* ── Footer ── */}
      <footer className="landing-footer">
        <span className="landing-footer-brand">金融研究智能体</span>
        <div className="landing-footer-links">
          <button
            className="landing-footer-link"
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
            onClick={() => navigate("/login")}
          >
            {lang === "zh" ? "登录" : "Sign In"}
          </button>
          <button
            className="landing-footer-link"
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
            onClick={() => navigate("/guidance")}
          >
            {lang === "zh" ? "使用指南" : "Guide"}
          </button>
          <button
            className="landing-footer-link"
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
            onClick={() => navigate("/showcase")}
          >
            {lang === "zh" ? "能力展示" : "Showcase"}
          </button>
        </div>
      </footer>
    </div>
  );
}
