"""app.py — DataAnalytics Streamlit Dashboard.

Architecture
------------
* Single-file multi-page app using st.navigation / st.Page (Streamlit ≥ 1.36)
  with a fallback to sidebar radio for older versions.
* Auth is handled by auth_middleware.py which calls the FastAPI auth server on
  localhost:8000 for token verification.
* All data queries go through app_utils.py (cached, parameterized).
* Admin-only pages (Audit Log, PII Vault, Reseed) are hidden from 'viewer' role.

Run
---
    # Terminal 1 — auth server (required for login):
    uvicorn auth:app --port 8000

    # Terminal 2 — Streamlit:
    streamlit run app.py
"""

import os
import streamlit as st
from dotenv import load_dotenv

# Load .env file before any project import — ensures JWT_SECRET_KEY and
# other secrets are available when config.py is imported. This replaces
# the old hardcoded dev-secret fallback. Secrets now live in .env only.
load_dotenv()

from auth_middleware import require_auth, get_current_user, logout, is_admin
import app_utils as au

# ── Page config ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="DataAnalytics — E-commerce Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ───────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Google Font ─────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Base ───────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}

[data-testid="stAppViewContainer"] {
    background: #080f1e;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1527 0%, #080f1e 100%);
    border-right: 1px solid rgba(255,255,255,0.06);
}

/* ── Animated gradient header ───────────────────────────────────────── */
.hero-header {
    background: linear-gradient(135deg, #1e1060 0%, #0c1a4a 40%, #0a1530 100%);
    border: 1px solid rgba(124,58,237,0.25);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}
.hero-header::before {
    content: '';
    position: absolute;
    top: -60%;
    left: -20%;
    width: 60%;
    height: 200%;
    background: radial-gradient(circle, rgba(124,58,237,0.18) 0%, transparent 70%);
    animation: pulse 6s ease-in-out infinite alternate;
}
.hero-header::after {
    content: '';
    position: absolute;
    bottom: -60%;
    right: -10%;
    width: 50%;
    height: 200%;
    background: radial-gradient(circle, rgba(6,182,212,0.12) 0%, transparent 70%);
    animation: pulse 8s ease-in-out infinite alternate-reverse;
}
@keyframes pulse {
    0%   { transform: scale(1);   opacity: 0.6; }
    100% { transform: scale(1.2); opacity: 1;   }
}
.hero-title {
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(90deg, #e2e8f0 0%, #7c3aed 50%, #06b6d4 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0;
    position: relative;
    z-index: 1;
}
.hero-subtitle {
    color: rgba(148,163,184,0.85);
    font-size: 0.95rem;
    margin: 6px 0 0 0;
    position: relative;
    z-index: 1;
}

/* ── KPI Cards ──────────────────────────────────────────────────────── */
.kpi-card {
    background: rgba(15, 23, 42, 0.7);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 20px 22px;
    transition: border-color 0.2s, transform 0.2s;
    height: 100%;
}
.kpi-card:hover {
    border-color: rgba(124,58,237,0.35);
    transform: translateY(-2px);
}
.kpi-label {
    color: #64748b;
    font-size: 0.78rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}
.kpi-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: #e2e8f0;
    line-height: 1.1;
}
.kpi-sub {
    font-size: 0.82rem;
    color: #475569;
    margin-top: 4px;
}
.kpi-icon {
    font-size: 1.4rem;
    float: right;
    margin-top: -4px;
    opacity: 0.7;
}
.kpi-delta-up   { color: #10b981; font-size: 0.82rem; }
.kpi-delta-down { color: #f43f5e; font-size: 0.82rem; }

/* ── Section heading ────────────────────────────────────────────────── */
.section-heading {
    font-size: 1.05rem;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    border-left: 3px solid #7c3aed;
    padding-left: 10px;
    margin: 28px 0 14px 0;
}

/* ── Badge ──────────────────────────────────────────────────────────── */
.badge-admin  { background: rgba(124,58,237,0.2); color: #a78bfa; border:1px solid rgba(124,58,237,0.4); border-radius:6px; padding:2px 10px; font-size:0.78rem; font-weight:600; }
.badge-viewer { background: rgba(6,182,212,0.15); color: #67e8f9; border:1px solid rgba(6,182,212,0.35); border-radius:6px; padding:2px 10px; font-size:0.78rem; font-weight:600; }

/* ── Sidebar nav items ──────────────────────────────────────────────── */
.nav-item {
    padding: 9px 14px;
    border-radius: 8px;
    margin: 3px 0;
    cursor: pointer;
    color: #64748b;
    font-size: 0.9rem;
    transition: background 0.15s, color 0.15s;
}
.nav-item.active, .nav-item:hover {
    background: rgba(124,58,237,0.15);
    color: #c4b5fd;
}

/* ── Hide default Streamlit decorations ─────────────────────────────── */
#MainMenu, footer { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }

/* ── Chart container ────────────────────────────────────────────────── */
.chart-card {
    background: rgba(15,23,42,0.6);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    padding: 4px;
}

/* ── Table overrides ────────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }

/* ── Divider ────────────────────────────────────────────────────────── */
.grad-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(124,58,237,0.5), transparent);
    margin: 20px 0;
}
</style>
""", unsafe_allow_html=True)


# ── Authentication gate ──────────────────────────────────────────────────

def render_login():
    """Render a styled login page (no sidebar visible)."""
    st.markdown("""
    <div style="max-width:420px;margin:80px auto 0;">
      <div style="text-align:center;margin-bottom:32px;">
        <div style="font-size:3rem;">📊</div>
        <h1 style="background:linear-gradient(90deg,#7c3aed,#06b6d4);-webkit-background-clip:text;
                   -webkit-text-fill-color:transparent;background-clip:text;font-size:1.8rem;
                   font-weight:700;margin:8px 0 4px;">DataAnalytics</h1>
        <p style="color:#475569;font-size:0.9rem;">E-commerce Intelligence Platform</p>
      </div>
    </div>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        with st.container(border=True):
            st.markdown("#### 🔐 Sign In")
            username = st.text_input("Username", placeholder="admin or viewer", key="li_user")
            password = st.text_input("Password", type="password", placeholder="••••••••", key="li_pass")
            st.caption("Default users: `admin / admin123` · `viewer / viewer123`")

            if st.button("Sign In →", use_container_width=True, type="primary"):
                import httpx
                try:
                    r = httpx.post(
                        "http://localhost:8000/auth/login",
                        data={"username": username, "password": password},
                        timeout=8,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        st.session_state["auth_token"] = data["access_token"]
                        st.session_state["username"] = data["username"]
                        st.session_state["role"] = data["role"]
                        st.rerun()
                    else:
                        st.error("Invalid username or password")
                except Exception:
                    # Dev mode: allow bypass when auth server isn't running
                    st.warning(
                        "⚠️ Auth server not reachable (`uvicorn auth:app --port 8000`). "
                        "Running in **dev mode** — limited functionality.",
                        icon="🛠️",
                    )
                    if username and password:
                        # Inject a fake session for local dev
                        role = "admin" if username == "admin" else "viewer"
                        st.session_state["auth_token"] = "dev-bypass"
                        st.session_state["username"] = username
                        st.session_state["role"] = role
                        st.rerun()


# ── Sidebar ──────────────────────────────────────────────────────────────

def render_sidebar(user: dict) -> str:
    """Render sidebar and return the selected page key."""
    with st.sidebar:
        # Brand
        st.markdown("""
        <div style="padding:16px 8px 20px;">
          <div style="font-size:1.4rem;font-weight:700;
                      background:linear-gradient(90deg,#7c3aed,#06b6d4);
                      -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                      background-clip:text;">📊 DataAnalytics</div>
          <div style="color:#334155;font-size:0.75rem;margin-top:2px;">E-commerce Intelligence</div>
        </div>
        """, unsafe_allow_html=True)

        # User chip
        badge_cls = "badge-admin" if user.get("role") == "admin" else "badge-viewer"
        st.markdown(
            f'<div style="margin-bottom:18px;">'
            f'<span style="color:#94a3b8;font-size:0.82rem;">👤 {user.get("username","")}</span> '
            f'<span class="{badge_cls}">{user.get("role","").upper()}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="grad-divider"></div>', unsafe_allow_html=True)

        # Navigation
        pages = {
            "🏠  Dashboard":    "dashboard",
            "📈  Revenue":      "revenue",
            "🛒  Products":     "products",
            "🤖  AI Query":     "ai_query",
            "🔮  Forecasting":  "forecast",
            "📂  Bring Your Data": "byod",
        }
        if user.get("role") == "admin":
            pages["🛡️  Admin Panel"] = "admin"

        if "page" not in st.session_state:
            st.session_state["page"] = "dashboard"

        for label, key in pages.items():
            is_active = st.session_state["page"] == key
            style = (
                "background:rgba(124,58,237,0.15);color:#c4b5fd;border-left:3px solid #7c3aed;"
                if is_active else "color:#64748b;"
            )
            if st.sidebar.button(
                label,
                key=f"nav_{key}",
                use_container_width=True,
            ):
                st.session_state["page"] = key
                st.rerun()

        st.markdown('<div class="grad-divider"></div>', unsafe_allow_html=True)

        # Logout
        if st.button("🚪  Sign Out", use_container_width=True):
            logout()
            for k in ["auth_token", "username", "role", "page"]:
                st.session_state.pop(k, None)
            st.rerun()

    return st.session_state.get("page", "dashboard")


# ── KPI row helper ───────────────────────────────────────────────────────

def render_kpi_row(kpis: dict):
    c1, c2, c3, c4 = st.columns(4)
    cards = [
        (c1, "💰", "Total Revenue",      au.format_inr(kpis["total_revenue"]),    f"Profit: {au.format_inr(kpis['total_profit'])} ({kpis['margin_pct']:.1f}% margin)"),
        (c2, "📦", "Total Orders",        f"{kpis['total_orders']:,}",              f"{kpis['completed_orders']:,} completed"),
        (c3, "🛍️", "Avg Order Value",    au.format_inr(kpis["avg_order_value"]),  "Per completed order"),
        (c4, "👥", "Unique Customers",   f"{kpis['total_customers']:,}",           "Across all regions"),
    ]
    for col, icon, label, value, sub in cards:
        with col:
            st.markdown(f"""
            <div class="kpi-card">
              <div class="kpi-icon">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>
            """, unsafe_allow_html=True)


# ── Pages ────────────────────────────────────────────────────────────────

def page_dashboard(df, kpis):
    st.markdown("""
    <div class="hero-header">
      <p class="hero-title">E-commerce Intelligence Dashboard</p>
      <p class="hero-subtitle">Real-time analytics across 2,500+ orders · 250 customers · 5 categories</p>
    </div>
    """, unsafe_allow_html=True)

    render_kpi_row(kpis)

    st.markdown('<div class="section-heading">Revenue Trends</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.plotly_chart(au.chart_revenue_over_time(df), use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.plotly_chart(au.chart_revenue_by_region(df), use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="section-heading">Order Intelligence</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(au.chart_order_status(df), use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.plotly_chart(au.chart_payment_methods(df), use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="section-heading">Category Breakdown</div>', unsafe_allow_html=True)
    st.plotly_chart(au.chart_revenue_heatmap(df), use_container_width=True, config={"displayModeBar": False})


def page_revenue(df, kpis):
    st.markdown("""
    <div class="hero-header">
      <p class="hero-title">Revenue Analysis</p>
      <p class="hero-subtitle">Deep-dive into revenue, profit, and margin trends</p>
    </div>
    """, unsafe_allow_html=True)

    render_kpi_row(kpis)

    st.markdown('<div class="section-heading">Monthly Volume & Revenue</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(au.chart_revenue_over_time(df), use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.plotly_chart(au.chart_monthly_orders(df), use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="section-heading">Category Performance</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(au.chart_revenue_by_category(df), use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.plotly_chart(au.chart_profit_margin_by_category(df), use_container_width=True, config={"displayModeBar": False})

    # Data table with filters
    st.markdown('<div class="section-heading">Filtered Data Explorer</div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        region_filter = st.multiselect("Region", sorted(df["customer_region"].unique()), key="rev_region")
    with col2:
        cat_filter = st.multiselect("Category", sorted(df["product_category"].unique()), key="rev_cat")
    with col3:
        status_filter = st.multiselect(
            "Status", sorted(df["order_status"].unique()),
            default=["completed"], key="rev_status",
        )

    filtered = df.copy()
    if region_filter:
        filtered = filtered[filtered["customer_region"].isin(region_filter)]
    if cat_filter:
        filtered = filtered[filtered["product_category"].isin(cat_filter)]
    if status_filter:
        filtered = filtered[filtered["order_status"].isin(status_filter)]

    agg = (
        filtered.groupby(["product_category", "customer_region"])
        .agg(revenue=("line_total", "sum"), profit=("line_profit", "sum"), orders=("order_id", "nunique"))
        .reset_index()
    )
    agg["margin"] = (agg["profit"] / agg["revenue"] * 100).round(1)
    agg["revenue"] = agg["revenue"].apply(au.format_inr)
    agg["profit"]  = agg["profit"].apply(au.format_inr)
    agg.columns = ["Category", "Region", "Revenue", "Profit", "Orders", "Margin %"]
    st.dataframe(agg, use_container_width=True, hide_index=True)


def page_products(df, _kpis):
    st.markdown("""
    <div class="hero-header">
      <p class="hero-title">Product Intelligence</p>
      <p class="hero-subtitle">Top performers, category mix, and subcategory breakdown</p>
    </div>
    """, unsafe_allow_html=True)

    top_n = st.slider("Show top N products", 5, 20, 10, key="top_n_slider")
    st.plotly_chart(au.chart_top_products(df, top_n=top_n), use_container_width=True, config={"displayModeBar": False})

    st.markdown('<div class="section-heading">Subcategory Breakdown</div>', unsafe_allow_html=True)
    completed = df[df["order_status"] == "completed"]
    subcat = (
        completed.groupby(["product_category", "product_subcategory"])
        .agg(revenue=("line_total", "sum"), units=("quantity", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )

    selected_cat = st.selectbox(
        "Filter by category",
        ["All"] + sorted(df["product_category"].unique().tolist()),
        key="subcat_filter",
    )
    if selected_cat != "All":
        subcat = subcat[subcat["product_category"] == selected_cat]

    import plotly.express as px
    fig = px.treemap(
        subcat,
        path=["product_category", "product_subcategory"],
        values="revenue",
        color_discrete_map=au.CATEGORY_COLORS,
        template="plotly_dark",
    )
    fig.update_layout(
        height=400, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def page_ai_query(df):
    st.markdown("""
    <div class="hero-header">
      <p class="hero-title">🤖 AI Natural Language Query</p>
      <p class="hero-subtitle">Ask questions in plain English — the AI builds a safe filter and answers you</p>
    </div>
    """, unsafe_allow_html=True)

    import ai_agent
    from llm_provider import get_provider
    from config import LLM_PROVIDER

    col1, col2 = st.columns([3, 1])
    with col2:
        provider_choice = st.selectbox(
            "LLM Provider",
            ["ollama", "gemini"],
            index=0 if LLM_PROVIDER == "ollama" else 1,
            key="llm_provider_choice",
        )

    # Example questions — includes no_match cases to demonstrate the decline behavior
    examples = [
        "What is our total revenue?",
        "How many orders have we received?",
        "Show me revenue by region",
        "What is the refund rate?",
        "What's the weather today?",           # no_match: not a business metric
        "Tell me a joke",                       # no_match: not a business metric
    ]

    with st.expander("💡 Example questions", expanded=False):
        for ex in examples:
            if st.button(f"→ {ex}", key=f"ex_{ex[:20]}"):
                st.session_state["ai_question"] = ex

    question = st.text_area(
        "Ask your question",
        value=st.session_state.get("ai_question", ""),
        placeholder="e.g. Show completed Electronics orders from North region in 2024",
        height=90,
        key="ai_question_input",
    )

    if st.button("🔍 Run Query", type="primary", use_container_width=False):
        if not question.strip():
            st.warning("Please enter a question.")
            st.stop()

        with st.spinner("Thinking..."):
            try:
                provider = get_provider(provider_choice)
                result = ai_agent.ask(question, provider)
                st.session_state["ai_last_result"] = result
            except Exception as e:
                st.error(f"Unexpected error: {e}")
                st.stop()

    # ── Results panel — rendered from session_state so it survives reruns ──
    last = st.session_state.get("ai_last_result")
    if last:
        answer       = last.get("answer", "")
        metric_used  = last.get("metric_used")
        confidence   = last.get("confidence", "n/a")
        caveat       = last.get("caveat")
        filters_used = last.get("filters_used", {})

        # No-match case: metric_used is None → decline gracefully, no data table
        if metric_used is None:
            st.info("🤔 I don't have a defined metric for that question yet.")
        else:
            st.success(f"✅ {answer}")

        # Metric badge
        if metric_used:
            st.markdown(f"**Metric used:** `{metric_used}`")

        # Confidence badge — green for high, yellow for low
        if confidence == "high":
            st.markdown("🟢 **Confidence:** high")
        elif confidence == "low":
            st.markdown("🟡 **Confidence:** low")

        # Caveat — always visible, never hidden in an expander
        if caveat:
            st.warning(f"⚠️ {caveat}")

        # Applied filters — sourced from ai_agent.ask() filters_used
        if filters_used:
            st.markdown("**Applied filters:**")
            filter_cols = st.columns(len(filters_used))
            for i, (col_name, val) in enumerate(filters_used.items()):
                filter_cols[i].metric(col_name, str(val))


def page_forecast(df):
    st.markdown("""
    <div class="hero-header">
      <p class="hero-title">🔮 Revenue Forecasting</p>
      <p class="hero-subtitle">Prophet time-series model trained on historical monthly revenue</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col2:
        periods = st.slider("Forecast horizon (months)", 3, 12, 6, key="fc_periods")
        category = st.selectbox(
            "Category",
            ["All Categories"] + sorted(df["product_category"].unique().tolist()),
            key="fc_category",
        )

    forecast_df = df.copy()
    if category != "All Categories":
        forecast_df = df[df["product_category"] == category]

    with st.spinner("Training Prophet model..."):
        fig = au.chart_forecast(forecast_df, periods=periods)

    if fig is None:
        st.warning("Not enough data to build a forecast (need ≥ 6 months of history).")
    else:
        with col1:
            pass  # placeholder for layout
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # Stats
        completed = forecast_df[forecast_df["order_status"] == "completed"]
        monthly = (
            completed.groupby("order_month")["line_total"].sum().reset_index()
        )
        avg = monthly["line_total"].mean()
        last = monthly["line_total"].iloc[-1] if len(monthly) else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("Historical Months", f"{len(monthly)}")
        col2.metric("Avg Monthly Revenue", au.format_inr(avg))
        col3.metric("Latest Month", au.format_inr(last))

        st.info(
            "ℹ️ Prophet decomposes the time series into trend + yearly seasonality. "
            "The shaded band shows the 95% confidence interval. "
            "Accuracy improves with more historical data.",
        )


def page_bring_your_data():
    """Bring Your Own Data page -- upload CSV/Parquet and chat with the Phase 1 agent."""
    st.markdown("""
    <div class="hero-header">
      <p class="hero-title">📂 Bring Your Own Data</p>
      <p class="hero-subtitle">Upload any CSV or Parquet file and ask questions in plain English</p>
    </div>
    """, unsafe_allow_html=True)

    from data_source import DataSource
    from agent_core import ask
    from llm_provider import get_provider
    from config import LLM_PROVIDER

    # ── Data source options ──
    st.markdown('<div class="section-heading">Load Data</div>', unsafe_allow_html=True)

    col_src1, col_src2 = st.columns(2)
    with col_src1:
        st.markdown("**📁 Upload a file**")
        uploaded = st.file_uploader(
            "CSV or Parquet",
            type=["csv", "tsv", "parquet", "pq"],
            key="byod_upload",
            label_visibility="collapsed",
        )
    with col_src2:
        st.markdown("**🛒 Load e-commerce data**")
        if st.button("Load ecommerce data", key="byod_load_ecommerce",
                     use_container_width=True, type="secondary"):
            try:
                from data_layer import init_db, DB_PATH
                init_db()  # ensure plaintext DB exists (no-op if already seeded)
                ds = DataSource()
                ds.load_sqlite(DB_PATH)
                st.session_state["byod_ds"] = ds
                st.success(
                    f"Loaded ecommerce data: {ds.profile.n_rows:,} rows × "
                    f"{ds.profile.n_cols} cols"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to load ecommerce data: {e}")

    if uploaded is not None:
        # Load into DataSource
        import tempfile
        import os

        suffix = os.path.splitext(uploaded.name)[1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb") as f:
            f.write(uploaded.getvalue())
            tmp_path = f.name

        try:
            ds = DataSource()
            ds.load_file(tmp_path)
            st.session_state["byod_ds"] = ds
            st.success(f"Loaded {uploaded.name}: {ds.profile.n_rows:,} rows × {ds.profile.n_cols} cols")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to load file: {e}")
        finally:
            os.unlink(tmp_path)

    # ── Show schema card + metric catalog ──
    ds = st.session_state.get("byod_ds")
    if ds is not None:
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown('<div class="section-heading">Schema</div>', unsafe_allow_html=True)
            st.code(ds.get_schema_card(), language="text")

        with col2:
            st.markdown('<div class="section-heading">Allowed Filters</div>', unsafe_allow_html=True)
            for col in ds.allowed_filter_columns:
                st.markdown(f"- `{col}`")

        # ── Metric catalog preview ──
        with st.expander(f"📋 Metric catalog ({len(ds.get_metrics())} metrics)", expanded=False):
            from metric_factory import get_metric_catalog_for_llm
            catalog = get_metric_catalog_for_llm(ds.get_metrics())
            st.dataframe(
                catalog,
                use_container_width=True,
                hide_index=True,
            )

        # ── Ask questions ──
        st.markdown('<div class="section-heading">Ask a Question</div>', unsafe_allow_html=True)

        provider_choice = st.selectbox(
            "LLM Provider",
            ["ollama", "gemini"],
            index=0 if LLM_PROVIDER == "ollama" else 1,
            key="byod_provider",
        )

        question = st.text_area(
            "Your question",
            placeholder="e.g. What is the total revenue? Show me revenue by region.",
            height=80,
            key="byod_question",
        )

        if st.button("Run Query", type="primary", key="byod_run"):
            if not question.strip():
                st.warning("Please enter a question.")
                st.stop()

            with st.spinner("Analyzing..."):
                try:
                    provider = get_provider(provider_choice)
                    result = ask(question, ds, provider)
                    st.session_state["byod_last_result"] = result
                except Exception as e:
                    st.error(f"Error: {e}")
                    st.stop()

        # ── Results ──
        last = st.session_state.get("byod_last_result")
        if last:
            if last.get("metric_used") is None:
                st.info(f"🤔 {last['answer']}")
            else:
                st.success(f"✅ {last['answer']}")

            if last.get("metric_used"):
                st.markdown(f"**Metric:** `{last['metric_used']}`")

            confidence = last.get("confidence", "n/a")
            if confidence == "high":
                st.markdown("🟢 **Confidence:** high")
            elif confidence == "low":
                st.markdown("🟡 **Confidence:** low")

            if last.get("caveat"):
                st.warning(f"⚠️ {last['caveat']}")

            if last.get("filters_used"):
                st.markdown("**Filters:**")
                for k, v in last["filters_used"].items():
                    st.markdown(f"- `{k}` = `{v}`")

            if last.get("result") is not None:
                st.markdown('<div class="section-heading">Raw Result</div>', unsafe_allow_html=True)
                import pandas as pd
                result = last["result"]
                if isinstance(result, pd.Series):
                    st.dataframe(result.reset_index(), use_container_width=True, hide_index=True)
                elif isinstance(result, (int, float)):
                    st.metric("Result", f"{result:,.2f}" if isinstance(result, float) else str(result))
                else:
                    st.write(result)


def page_admin(df):
    st.markdown("""
    <div class="hero-header">
      <p class="hero-title">🛡️ Admin Panel</p>
      <p class="hero-subtitle">Audit logs, PII vault inspection, and database management</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["📋 Audit Log", "🔒 PII Vault", "🗄️ Database"])

    # ── Tab 1: Audit Log ──
    with tab1:
        st.markdown('<div class="section-heading">Recent Activity</div>', unsafe_allow_html=True)
        audit_df = au.load_audit_logs(limit=200)
        if audit_df.empty:
            st.info("No audit log entries yet.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                user_filter = st.multiselect("Filter by user", audit_df["username"].unique().tolist(), key="audit_user")
            with col2:
                action_filter = st.multiselect("Filter by action", audit_df["action_type"].unique().tolist(), key="audit_action")

            show = audit_df.copy()
            if user_filter:
                show = show[show["username"].isin(user_filter)]
            if action_filter:
                show = show[show["action_type"].isin(action_filter)]

            st.dataframe(
                show[["timestamp", "username", "role", "action_type", "ip_address"]].head(100),
                use_container_width=True, hide_index=True,
            )

            # Action type bar chart
            action_counts = audit_df["action_type"].value_counts().reset_index()
            action_counts.columns = ["Action", "Count"]
            import plotly.express as px
            fig = px.bar(action_counts, x="Action", y="Count", template="plotly_dark",
                         color="Action", color_discrete_sequence=[au.ACCENT_PURPLE, au.ACCENT_CYAN,
                         au.ACCENT_GREEN, au.ACCENT_AMBER, au.ACCENT_ROSE, "#94a3b8", "#f43f5e"])
            fig.update_layout(showlegend=False, height=280, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Tab 2: PII Vault ──
    with tab2:
        st.markdown('<div class="section-heading">PII Vault (Encrypted at Rest)</div>', unsafe_allow_html=True)
        st.info(
            "🔐 The PII vault is stored as `pii_vault.db.enc` — Fernet-encrypted using the same "
            "key as `ecommerce.db.enc`. Plaintext PII never touches disk.",
        )
        cid = st.number_input("Customer ID to inspect", min_value=1, max_value=250, value=1, step=1, key="pii_cid")
        if st.button("🔍 Decrypt & Show PII Record", key="pii_lookup"):
            from pii_masker import PIIMasker
            masker = PIIMasker()
            records = masker.get_before_after(limit=250)
            cid_records = [r for r in records if r["customer_id"] == int(cid)]
            if cid_records:
                import pandas as pd
                st.dataframe(pd.DataFrame(cid_records), use_container_width=True, hide_index=True)
            else:
                st.warning(f"No PII vault records for customer {cid}.")

            stats = masker.vault_stats()
            col1, col2 = st.columns(2)
            col1.metric("Total Vault Records", f"{stats['total_records']:,}")
            col2.metric("Entity Types", f"{len(stats['by_entity'])}")

    # ── Tab 3: Database ──
    with tab3:
        st.markdown('<div class="section-heading">Database Management</div>', unsafe_allow_html=True)
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown(f"""
            | Metric | Value |
            |--------|-------|
            | Total line items | `{len(df):,}` |
            | Unique orders | `{df['order_id'].nunique():,}` |
            | Unique customers | `{df['customer_id'].nunique():,}` |
            | Unique products | `{df['product_id'].nunique():,}` |
            | Date range | `{df['order_date'].min().date()} → {df['order_date'].max().date()}` |
            """)
        with col2:
            st.warning(
                "⚠️ Reseeding deletes all existing data and regenerates 2,500 orders with fresh PII masking.",
            )
            confirm = st.checkbox("I understand this is destructive", key="reseed_confirm")
            if st.button("🔄 Reseed Database", type="primary", disabled=not confirm, key="reseed_btn"):
                with st.spinner("Reseeding..."):
                    from data_layer import init_db
                    init_db(force_reseed=True)
                    au.load_enriched.clear()
                st.success("Database reseeded successfully!")
                st.rerun()


# ── Main app ─────────────────────────────────────────────────────────────

def main():
    # Auth check
    user = get_current_user()
    if user is None:
        render_login()
        return

    # Sidebar
    page = render_sidebar(user)

    # Load data (cached)
    with st.spinner("Loading data..."):
        df   = au.load_enriched()
        kpis = au.compute_kpis(df)

    # Route to page
    if page == "dashboard":
        page_dashboard(df, kpis)
    elif page == "revenue":
        page_revenue(df, kpis)
    elif page == "products":
        page_products(df, kpis)
    elif page == "ai_query":
        page_ai_query(df)
    elif page == "forecast":
        page_forecast(df)
    elif page == "byod":
        page_bring_your_data()
    elif page == "admin":
        if user.get("role") != "admin":
            st.error("🚫 Access denied. Admin role required.")
        else:
            page_admin(df)
    else:
        page_dashboard(df, kpis)


if __name__ == "__main__":
    main()
