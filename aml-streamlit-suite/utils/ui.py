"""
utils/ui.py

UI helpers shared across all tabs — an advanced, colorful, classy theme.

Public API (unchanged signatures → existing callers in app.py keep working):
  - inject_custom_css()            one-time CSS injection for the vibrant theme
  - risk_color(level)              hex color for a risk level
  - risk_badge_html(level)         pill badge HTML for a risk level
  - metric_card(...) / metric_row(...)   styled metric widgets
  - notify(message, status)        toast notification wrapper
  - app_header(title, subtitle)    branded page header

New additions (used by the upgraded app.py):
  - section_header(title, icon)    colorful gradient section banner
  - stat_card(...)                 large vibrant statistic card
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

# Main brand gradient used for headers / accents
BRAND_GRADIENT = "linear-gradient(135deg, #667eea 0%, #764ba2 50%, #2EC4B6 100%)"

# Surface / card palette — semi-transparent glassmorphism
CARD_BG = "rgba(255, 255, 255, 0.55)"
CARD_BORDER = "rgba(255, 255, 255, 0.4)"
CARD_SHADOW = "0 8px 32px rgba(15, 23, 42, 0.10)"

# Risk palette (kept identical to before so downstream callers are unaffected)
RISK_COLORS = {
    "HIGH": "#FF4D4D",
    "MEDIUM": "#FFB703",
    "LOW": "#2EC4B6",
}

RISK_LABELS = {
    "HIGH": "🔴 High Risk",
    "MEDIUM": "🟡 Medium Risk",
    "LOW": "🟢 Low Risk",
}

# Accent colors for stat/metric cards (cycled)
ACCENT_COLORS = [
    "rgba(255, 99, 132, 0.85)",    # red-pink
    "rgba(255, 159, 139, 0.85)",   # orange
    "rgba(255, 205, 89, 0.85)",    # amber
    "rgba(102, 126, 234, 0.85)",   # indigo
    "rgba(46, 196, 182, 0.85)",    # teal
    "rgba(153, 102, 255, 0.85)",   # purple
]


def risk_color(level: str) -> str:
    return RISK_COLORS.get(str(level).upper(), "#94A3B8")


def risk_badge_html(level: str) -> str:
    """A pill-shaped colored badge for a risk level, safe to drop straight
    into st.markdown(..., unsafe_allow_html=True)."""
    level_u = str(level).upper()
    color = risk_color(level_u)
    label = RISK_LABELS.get(level_u, level_u or "UNKNOWN")

    def contrast_text(hex_color: str) -> str:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(ch * 2 for ch in hex_color)
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#0f172a" if luminance > 0.6 else "#ffffff"

    text_color = contrast_text(color)
    return (
        f'<span class="risk-badge" '
        f'style="background:{color};color:{text_color};border:1px solid {color};box-shadow:0 6px 18px rgba(15,23,42,0.08);">'
        f"{label}</span>"
    )


def notify(message: str, status: str = "info") -> None:
    """Fire a toast notification for uploads / syncs / runs.

    status: "success" | "error" | "warning" | "info"
    """
    icons = {"success": "✅", "error": "❌", "warning": "⚠️", "info": "ℹ️"}
    try:
        st.toast(message, icon=icons.get(status, "ℹ️"))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Metric / stat cards
# ---------------------------------------------------------------------------

def metric_card(label: str, value, sublabel: str | None = None, color: str | None = None) -> str:
    """Return HTML for a single styled metric card (glassmorphism, rounded
    corners, optional colored left accent). Render with:
        st.markdown(metric_card(...), unsafe_allow_html=True)
    """
    accent = f"border-left: 4px solid {color};" if color else ""
    sub_html = f'<div class="metric-card-sub">{sublabel}</div>' if sublabel else ""
    return f"""
    <div class="metric-card" style="{accent}">
        <div class="metric-card-label">{label}</div>
        <div class="metric-card-value">{value}</div>
        {sub_html}
    </div>
    """


def metric_row(cards: list[dict]) -> None:
    """Render a row of metric_card() dicts: {"label", "value", "sublabel", "color"}."""
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            st.markdown(
                metric_card(
                    card.get("label", ""),
                    card.get("value", ""),
                    card.get("sublabel"),
                    card.get("color"),
                ),
                unsafe_allow_html=True,
            )


def stat_card(title: str, value, subtitle: str | None = None, color: str | None = None) -> str:
    """A larger, more vibrant statistic card for dashboard highlights.

    Render with:
        st.markdown(stat_card(...), unsafe_allow_html=True)
    """
    bg_color = color or ACCENT_COLORS[0]
    sub_html = f'<div class="stat-card-sub">{subtitle}</div>' if subtitle else ""
    return f"""
    <div class="stat-card" style="background:{bg_color};">
        <div class="stat-card-title">{title}</div>
        <div class="stat-card-value">{value}</div>
        {sub_html}
    </div>
    """


def section_header(title: str, icon: str = "") -> None:
    """Render a colorful gradient section banner with an optional icon.
    Uses st.markdown with unsafe HTML — purely visual, no logic change."""
    icon_html = f'<span class="section-icon">{icon}</span>' if icon else ""
    st.markdown(
        f'<div class="section-header-banner">'
        f'<div class="section-header-gradient"></div>'
        f'<span class="section-header-title">{icon_html}{title}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def sub_section(title: str, icon: str = "") -> None:
    """Compact colored subsection label with a soft gradient dot + title.
    Lighter than section_header(), ideal for mid-level groupings."""
    icon_html = f'<span class="sub-section-icon">{icon}</span>' if icon else ""
    st.markdown(
        f'<div class="sub-section-label">{icon_html}<span class="sub-section-text">{title}</span></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------

def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        /* ================================================================
           Page background — vibrant gradient
        ================================================================= */
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(160deg, #f0f4ff 0%, #e0f2fe 40%, #f0fdfa 100%);
            background-attachment: fixed;
            font-feature-settings: "tnum";
        }
        [data-testid="stAppViewContainer"]::before {
            content: "";
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: radial-gradient(circle at 18% 22%, rgba(102,126,234,.18), transparent 60%),
                        radial-gradient(circle at 82% 30%, rgba(46,196,182,.15), transparent 55%),
                        radial-gradient(circle at 50% 80%, rgba(255,159,139,.10), transparent 60%);
            pointer-events: none;
            z-index: 0;
        }

        /* ================================================================
           Layout & typography
        ================================================================= */
        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 3rem;
            max-width: 1200px;
            position: relative;
            z-index: 1;
        }
        h1, h2, h3, h4 {
            font-weight: 700;
            letter-spacing: -0.01em;
            background: linear-gradient(135deg, #1e293b 0%, #475569 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        h1 { font-size: 2.4rem; }
        h2 { font-size: 1.7rem; }
        h3 { font-size: 1.3rem; }

        /* ================================================================
           App header — classy gradient badge
        ================================================================= */
        .app-header {
            display: flex;
            align-items: center;
            gap: 0.85rem;
            margin-bottom: 0.5rem;
            padding: 0.4rem 0;
        }
        .app-header .app-title {
            font-size: 2rem;
            font-weight: 800;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 60%, #2EC4B6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .app-header .app-subtitle {
            color: #475569;
            font-size: 0.95rem;
            margin-top: 0.15rem;
            font-weight: 400;
        }
        .app-header .logo-badge {
            width: 44px; height: 44px;
            border-radius: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            box-shadow: 0 6px 16px rgba(102, 126, 234, 0.35);
        }

        /* ================================================================
           Metric cards — glassmorphism
        ================================================================= */
        .metric-card {
            background: rgba(255, 255, 255, 0.65);
            border-radius: 16px;
            padding: 1.1rem 1.2rem;
            box-shadow: 0 8px 32px rgba(15, 23, 42, 0.08),
                        inset 0 1px 0 rgba(255, 255, 255, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.5);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
        }
        .metric-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.14);
            border-color: rgba(102, 126, 234, 0.45);
        }
        .metric-card-label {
            font-size: 0.78rem;
            color: #475569;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 0.3rem;
        }
        .metric-card-value {
            font-size: 2rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.2;
        }
        .metric-card-sub {
            font-size: 0.8rem;
            color: #64748b;
            margin-top: 0.25rem;
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }

        /* Stat cards (larger) */
        .stat-card {
            background: rgba(255, 255, 255, 0.85);
            border-radius: 20px;
            padding: 1.5rem 1.6rem;
            box-shadow: 0 8px 32px rgba(15, 23, 42, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.45);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            position: relative;
            overflow: hidden;
        }
        .stat-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 16px 40px rgba(15, 23, 42, 0.18);
        }
        .stat-card::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 4px;
        }
        .stat-card-title {
            font-size: 0.85rem;
            color: rgba(255,255,255,0.92);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.4rem;
        }
        .stat-card-value {
            font-size: 2.4rem;
            font-weight: 800;
            color: rgba(255,255,255,0.95);
            line-height: 1.1;
        }
        .stat-card-sub {
            font-size: 0.82rem;
            color: rgba(255,255,255,0.78);
            margin-top: 0.3rem;
        }

        /* ================================================================
           Risk badges
        ================================================================= */
        .risk-badge {
            display: inline-block;
            padding: 0.22rem 0.8rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 700;
            white-space: nowrap;
            backdrop-filter: blur(2px);
            letter-spacing: 0.02em;
        }

        .investigation-column {
            display: flex;
            flex-direction: column;
            gap: 1rem;
            height: 100%;
        }
        .investigation-panel {
            display: flex;
            flex-direction: column;
            gap: 0.8rem;
            height: 100%;
        }

        /* ================================================================
           Section header banner (new)
        ================================================================= */
        .section-header-banner {
            position: relative;
            border-radius: 14px;
            padding: 0.7rem 1.1rem;
            margin-bottom: 1rem;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.5);
            background: rgba(255,255,255,0.45);
            backdrop-filter: blur(10px);
        }
        .section-header-banner .section-header-gradient {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: linear-gradient(90deg, rgba(102,126,234,.22), rgba(46,196,182,.18), rgba(255,159,139,.12));
            border-radius: 10px;
            z-index: 0;
        }
        .section-header-banner .section-header-title {
            position: relative;
            z-index: 1;
            font-weight: 700;
            font-size: 1.05rem;
            color: #0f172a;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
        }
        .section-header-banner .section-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 30px; height: 30px;
            border-radius: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-size: 1.1rem;
            color: white;
        }

        /* Sub-section labels (compact colored headers) */
        .sub-section-label {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.35rem 0.9rem;
            border-radius: 8px;
            background: rgba(255,255,255,.55);
            border: 1px solid rgba(255,255,255,.45);
            backdrop-filter: blur(6px);
            margin-bottom: 0.5rem;
        }
        .sub-section-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px; height: 24px;
            border-radius: 6px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-size: 0.9rem;
            color: white;
        }
        .sub-section-text {
            font-weight: 700;
            font-size: 0.92rem;
            color: #0f172a;
        }

        /* Audit reasoning box */
        .audit-reasoning-box {
            background: rgba(255,255,255,.75);
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,.5);
            padding: 1rem 1.2rem;
            box-shadow: 0 4px 18px rgba(15, 23, 42, 0.06);
            backdrop-filter: blur(6px);
        }

        /* ================================================================
           Section cards — vibrant glassmorphism
        ================================================================= */
        .section-card {
            background: rgba(255, 255, 255, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.45);
            border-radius: 16px;
            padding: 1.2rem 1.3rem;
            box-shadow: 0 8px 32px rgba(15, 23, 42, 0.08),
                        inset 0 1px 0 rgba(255, 255, 255, 0.4);
            margin-bottom: 1rem;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: box-shadow 0.2s ease, border-color 0.2s ease;
        }
        .section-card:hover {
            box-shadow: 0 12px 36px rgba(15, 23, 42, 0.13);
            border-color: rgba(102, 126, 234, 0.35);
        }
        .section-card-title {
            font-weight: 700;
            font-size: 1.1rem;
            margin-bottom: 0.3rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: #0f172a;
        }
        .section-card-title .emoji-icon {
            width: 28px; height: 28px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 1.1rem;
            flex-shrink: 0;
        }

        /* Status pills */
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            font-size: 0.78rem;
            font-weight: 700;
            padding: 0.18rem 0.7rem;
            border-radius: 999px;
            background: linear-gradient(135deg, #d1fae5 0%, #6ee7b7 100%);
            color: #065f46;
            border: 1px solid #6ee7b7;
        }
        .status-pill.neutral {
            background: #e2e8f0;
            color: #334155;
            border-color: #cbd5e1;
        }
        .status-pill.high {
            background: linear-gradient(135deg, #fecaca 0%, #fca5a5 100%);
            color: #991b1b;
            border-color: #fca5a5;
        }
        .status-pill.medium {
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            color: #92400e;
            border-color: #fde68a;
        }

        /* ================================================================
           File upload dropzones
        ================================================================= */
        [data-testid="stFileUploaderDropzone"] {
            border-radius: 14px !important;
            border: 2px dashed rgba(102,126,234,.45) !important;
            background: rgba(255,255,255,.55) !important;
            padding: 0.6rem !important;
            transition: all 0.2s ease;
        }
        [data-testid="stFileUploaderDropzone"]:hover {
            border-color: #667eea !important;
            background: rgba(255,255,255,.7) !important;
            box-shadow: 0 6px 20px rgba(102,126,234,.15);
        }

        /* ================================================================
           Buttons — gradient primary, classy secondary
        ================================================================= */
        .stButton>button {
            border-radius: 12px;
            font-weight: 600;
            transition: all 0.2s cubic-bezier(.25,.8,.5,1);
            border: none;
        }
        .stButton>button[kind="primary"] {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            box-shadow: 0 4px 14px rgba(102,126,234,.35);
            border: 1px solid rgba(102,126,234,.4);
        }
        .stButton>button[kind="primary"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 22px rgba(102,126,234,.45);
        }
        .stButton>button[kind="secondary"],
        .stButton>button:not([kind]) {
            background: rgba(255,255,255,.6);
            color: #334059;
            border: 1px solid rgba(255,255,255,.5);
            backdrop-filter: blur(6px);
        }
        .stButton>button[kind="secondary"]:hover,
        .stButton>button:not([kind]):hover {
            background: rgba(255,255,255,.85);
            border-color: rgba(102,126,234,.4);
        }
        .stButton>button:active {
            transform: translateY(0);
        }

        /* ================================================================
           Chat prompt chips
        ================================================================= */
        div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
            border-radius: 999px !important;
            font-size: 0.82rem !important;
            padding: 0.3rem 1rem !important;
            background: rgba(255,255,255,.6) !important;
            border: 1px solid rgba(255,255,255,.5) !important;
            backdrop-filter: blur(6px) !important;
            color: #334059 !important;
            transition: all 0.18s ease;
        }
        div[data-testid="stHorizontalBlock"] button[kind="secondary"]:hover {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            color: white !important;
            transform: translateY(-1px);
            box-shadow: 0 4px 14px rgba(102,126,234,.25);
        }

        /* ================================================================
           Chat messages
        ================================================================= */
        .stChatMessage {
            background: rgba(255, 255, 255, 0.55);
            border-radius: 14px;
            border: 1px solid rgba(255, 255, 255, 0.4);
            padding: 0.8rem 1rem;
            backdrop-filter: blur(8px);
        }
        .stChatMessage[data-testid="stChatMessage"] {
            box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
        }

        /* ================================================================
           Tabs — classy active indicator
        ================================================================= */
        [data-baseweb="tabs"] {
            background: rgba(255, 255, 255, 0.5);
            border-radius: 14px;
            padding: 0.3rem;
            box-shadow: 0 4px 18px rgba(15, 23, 42, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.45);
            backdrop-filter: blur(6px);
        }
        [data-baseweb="tabs"] [data-testid="stTab"] {
            color: #64748b;
            font-weight: 600;
            border-radius: 10px;
            padding: 0.5rem 1rem;
            transition: all 0.18s ease;
        }
        [data-baseweb="tabs"] [data-testid="stTab"]:hover {
            color: #475569;
        }
        [data-baseweb="tab-indicator"] {
            background: linear-gradient(90deg, #667eea 0%, #764ba2 60%, #2EC4B6 100%) !important;
        }

        /* ================================================================
           Dataframe polish
        ================================================================= */
        [data-testid="stDataFrame"] {
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.4);
            backdrop-filter: blur(4px);
        }

        /* ================================================================
           Expanders — soft glass look
        ================================================================= */
        [data-testid="stExpander"] {
            background: rgba(255, 255, 255, 0.45);
            border-radius: 14px;
            border: 1px solid rgba(255, 255, 255, 0.45);
            backdrop-filter: blur(8px);
        }
        [data-testid="stExpander"] summary {
            font-weight: 600 !important;
            color: #0f172a !important;
        }

        /* ================================================================
           StForm / inputs — soft vibrancy
        ================================================================= */
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stSelectbox"] input,
        [data-testid="stMultiSelect"] input {
            background: rgba(255,255,255,.65) !important;
            border: 1px solid rgba(102,126,234,.3) !important;
            border-radius: 10px !important;
            color: #0f172a !important;
        }
        [data-testid="stTextInput"] input:focus,
        [data-testid="stTextArea"] textarea:focus,
        [data-testid="stSelectbox"] input:focus {
            border-color: #667eea !important;
            box-shadow: 0 0 0 2px rgba(102,126,234,.15) !important;
        }

        /* ================================================================
           Sidebar — subtle gradient
        ================================================================= */
        [data-testid="stSidebar"] .stSidebarContent {
            background: linear-gradient(180deg, rgba(255,255,255,.55) 0%, rgba(240,244,252,.55) 100%);
            border-right: 1px solid rgba(255,255,255,.4);
        }
        [data-testid="stSidebar"] h3, [data-testid="stSidebar"] .stMarkdown {
            color: #0f172a;
        }

        /* ================================================================
           Generic dividers — soft
        ================================================================= */
        .stDivider > div {
            border-color: rgba(102, 126, 234, 0.25) !important;
        }

        /* Status / error boxes — keep Streamlit defaults but soften */
        [data-testid="stAlert"] {
            border-radius: 12px;
            border: 1px solid rgba(255,255,255,.4);
        }

        /* ================================================================
           Scrollbar — subtle
        ================================================================= */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(15, 23, 42, 0.03);
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(102, 126, 234, 0.35);
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(102, 126, 234, 0.55);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def app_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="app-header">
            <div class="logo-badge">🛡️</div>
            <div>
                <p class="app-title">{title}</p>
                <div class="app-subtitle">{subtitle}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
