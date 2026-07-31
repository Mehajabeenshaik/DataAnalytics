"""app_utils.py — Cached data loaders, KPI helpers, and chart builders.

All data access goes through the plaintext ecommerce.db (decrypted at startup).
Heavy queries are cached with @st.cache_data to avoid re-running on every
Streamlit rerun.
"""

import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_layer import DB_PATH, init_db, get_column_descriptions

# ── Plotly dark theme defaults ──────────────────────────────────────────

PLOTLY_TEMPLATE = "plotly_dark"
ACCENT_PURPLE   = "#7c3aed"
ACCENT_CYAN     = "#06b6d4"
ACCENT_GREEN    = "#10b981"
ACCENT_AMBER    = "#f59e0b"
ACCENT_ROSE     = "#f43f5e"

CATEGORY_COLORS = {
    "Electronics":    ACCENT_PURPLE,
    "Clothing":       ACCENT_CYAN,
    "Home & Kitchen": ACCENT_GREEN,
    "Books":          ACCENT_AMBER,
    "Sports":         ACCENT_ROSE,
}

REGION_COLORS = {
    "North": "#7c3aed",
    "South": "#06b6d4",
    "East":  "#10b981",
    "West":  "#f59e0b",
}

STATUS_COLORS = {
    "completed": ACCENT_GREEN,
    "pending":   ACCENT_AMBER,
    "cancelled": ACCENT_ROSE,
    "returned":  "#94a3b8",
}


def _chart_layout(fig: go.Figure, height: int = 380) -> go.Figure:
    """Apply shared layout to a Plotly figure."""
    fig.update_layout(
        height=height,
        margin=dict(l=16, r=16, t=32, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#e2e8f0"),
        legend=dict(
            bgcolor="rgba(15,23,42,0.6)",
            bordercolor="rgba(255,255,255,0.08)",
            borderwidth=1,
        ),
    )
    fig.update_xaxes(
        gridcolor="rgba(255,255,255,0.06)",
        zerolinecolor="rgba(255,255,255,0.1)",
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.06)",
        zerolinecolor="rgba(255,255,255,0.1)",
    )
    return fig


# ── Data loaders ────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_enriched() -> pd.DataFrame:
    """Return the full orders_enriched view as a DataFrame."""
    init_db()                          # no-op if already seeded
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM orders_enriched", conn)
    conn.close()
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_audit_logs(limit: int = 200) -> pd.DataFrame:
    from audit_logger import get_audit_logs
    rows = get_audit_logs(limit=limit)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ── KPI helpers ─────────────────────────────────────────────────────────

def compute_kpis(df: pd.DataFrame) -> dict:
    """Compute top-level KPI metrics from the enriched DataFrame."""
    completed = df[df["order_status"] == "completed"]
    total_revenue   = completed["line_total"].sum()
    total_profit    = completed["line_profit"].sum()
    total_orders    = df["order_id"].nunique()
    completed_orders = completed["order_id"].nunique()
    avg_order_value = completed.groupby("order_id")["line_total"].sum().mean() if completed_orders else 0
    margin_pct      = (total_profit / total_revenue * 100) if total_revenue else 0
    return {
        "total_revenue":    total_revenue,
        "total_profit":     total_profit,
        "total_orders":     total_orders,
        "completed_orders": completed_orders,
        "avg_order_value":  avg_order_value,
        "margin_pct":       margin_pct,
        "total_customers":  df["customer_id"].nunique(),
    }


def format_inr(value: float) -> str:
    """Format a number as Indian Rupees (lakhs/crores)."""
    if value >= 1e7:
        return f"₹{value/1e7:.2f} Cr"
    elif value >= 1e5:
        return f"₹{value/1e5:.2f} L"
    else:
        return f"₹{value:,.0f}"


# ── Chart builders ──────────────────────────────────────────────────────

def chart_revenue_over_time(df: pd.DataFrame) -> go.Figure:
    completed = df[df["order_status"] == "completed"].copy()
    monthly = (
        completed.groupby("order_month")["line_total"]
        .sum()
        .reset_index()
        .rename(columns={"order_month": "Month", "line_total": "Revenue"})
        .sort_values("Month")
    )
    monthly["Month_dt"] = pd.to_datetime(monthly["Month"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=monthly["Month_dt"],
        y=monthly["Revenue"],
        mode="lines+markers",
        name="Revenue",
        line=dict(color=ACCENT_CYAN, width=2.5),
        marker=dict(size=5, color=ACCENT_CYAN),
        fill="tozeroy",
        fillcolor="rgba(6,182,212,0.08)",
        hovertemplate="<b>%{x|%b %Y}</b><br>Revenue: ₹%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(title="Monthly Revenue (Completed Orders)")
    return _chart_layout(fig)


def chart_revenue_by_category(df: pd.DataFrame) -> go.Figure:
    completed = df[df["order_status"] == "completed"]
    cat = (
        completed.groupby("product_category")["line_total"]
        .sum()
        .reset_index()
        .sort_values("line_total", ascending=True)
    )
    fig = go.Figure(go.Bar(
        x=cat["line_total"],
        y=cat["product_category"],
        orientation="h",
        marker_color=[CATEGORY_COLORS.get(c, ACCENT_PURPLE) for c in cat["product_category"]],
        hovertemplate="<b>%{y}</b><br>₹%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(title="Revenue by Product Category", showlegend=False)
    return _chart_layout(fig)


def chart_revenue_by_region(df: pd.DataFrame) -> go.Figure:
    completed = df[df["order_status"] == "completed"]
    region = (
        completed.groupby("customer_region")["line_total"]
        .sum()
        .reset_index()
    )
    fig = px.pie(
        region,
        names="customer_region",
        values="line_total",
        color="customer_region",
        color_discrete_map=REGION_COLORS,
        hole=0.5,
        template=PLOTLY_TEMPLATE,
    )
    fig.update_traces(
        textinfo="percent+label",
        hovertemplate="<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>",
    )
    fig.update_layout(title="Revenue Share by Region", showlegend=True)
    return _chart_layout(fig)


def chart_order_status(df: pd.DataFrame) -> go.Figure:
    status = df.drop_duplicates("order_id")["order_status"].value_counts().reset_index()
    status.columns = ["Status", "Count"]
    fig = go.Figure(go.Bar(
        x=status["Status"],
        y=status["Count"],
        marker_color=[STATUS_COLORS.get(s, "#94a3b8") for s in status["Status"]],
        hovertemplate="<b>%{x}</b><br>%{y:,} orders<extra></extra>",
    ))
    fig.update_layout(title="Order Status Distribution", showlegend=False)
    return _chart_layout(fig)


def chart_top_products(df: pd.DataFrame, top_n: int = 10) -> go.Figure:
    completed = df[df["order_status"] == "completed"]
    top = (
        completed.groupby("product_name")["line_total"]
        .sum()
        .nlargest(top_n)
        .reset_index()
        .sort_values("line_total", ascending=True)
    )
    fig = go.Figure(go.Bar(
        x=top["line_total"],
        y=top["product_name"],
        orientation="h",
        marker=dict(
            color=top["line_total"],
            colorscale=[[0, "#312e81"], [1, ACCENT_CYAN]],
            showscale=False,
        ),
        hovertemplate="<b>%{y}</b><br>₹%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(title=f"Top {top_n} Products by Revenue", showlegend=False)
    return _chart_layout(fig, height=420)


def chart_payment_methods(df: pd.DataFrame) -> go.Figure:
    pay = df.drop_duplicates("order_id")["payment_method"].value_counts().reset_index()
    pay.columns = ["Method", "Count"]
    colors = [ACCENT_PURPLE, ACCENT_CYAN, ACCENT_GREEN, ACCENT_AMBER, ACCENT_ROSE]
    fig = px.bar(
        pay, x="Method", y="Count",
        color="Method",
        color_discrete_sequence=colors,
        template=PLOTLY_TEMPLATE,
    )
    fig.update_layout(title="Orders by Payment Method", showlegend=False)
    fig.update_traces(hovertemplate="<b>%{x}</b><br>%{y:,} orders<extra></extra>")
    return _chart_layout(fig)


def chart_profit_margin_by_category(df: pd.DataFrame) -> go.Figure:
    completed = df[df["order_status"] == "completed"]
    grp = completed.groupby("product_category").agg(
        revenue=("line_total", "sum"),
        profit=("line_profit", "sum"),
    ).reset_index()
    grp["margin"] = (grp["profit"] / grp["revenue"] * 100).round(1)
    fig = go.Figure(go.Bar(
        x=grp["product_category"],
        y=grp["margin"],
        marker_color=[CATEGORY_COLORS.get(c, ACCENT_PURPLE) for c in grp["product_category"]],
        hovertemplate="<b>%{x}</b><br>Margin: %{y:.1f}%<extra></extra>",
        text=grp["margin"].apply(lambda v: f"{v:.1f}%"),
        textposition="outside",
    ))
    fig.update_layout(title="Profit Margin % by Category", showlegend=False, yaxis_ticksuffix="%")
    return _chart_layout(fig)


def chart_monthly_orders(df: pd.DataFrame) -> go.Figure:
    monthly = (
        df.drop_duplicates("order_id")
        .groupby("order_month")["order_id"]
        .count()
        .reset_index()
        .rename(columns={"order_month": "Month", "order_id": "Orders"})
        .sort_values("Month")
    )
    monthly["Month_dt"] = pd.to_datetime(monthly["Month"])
    fig = go.Figure(go.Bar(
        x=monthly["Month_dt"],
        y=monthly["Orders"],
        marker_color=ACCENT_PURPLE,
        hovertemplate="<b>%{x|%b %Y}</b><br>%{y:,} orders<extra></extra>",
        opacity=0.85,
    ))
    fig.update_layout(title="Monthly Order Volume")
    return _chart_layout(fig)


def chart_revenue_heatmap(df: pd.DataFrame) -> go.Figure:
    """Revenue heatmap: region × product category."""
    completed = df[df["order_status"] == "completed"]
    pivot = (
        completed.groupby(["customer_region", "product_category"])["line_total"]
        .sum()
        .unstack(fill_value=0)
    )
    fig = go.Figure(go.Heatmap(
        z=pivot.values / 1e5,          # display in lakhs
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=[[0, "#0f172a"], [0.5, ACCENT_PURPLE], [1, ACCENT_CYAN]],
        hovertemplate="Region: <b>%{y}</b><br>Category: <b>%{x}</b><br>₹%{z:.1f}L<extra></extra>",
        text=(pivot.values / 1e5).round(1),
        texttemplate="%{text}L",
    ))
    fig.update_layout(title="Revenue Heatmap (₹ Lakhs): Region × Category")
    return _chart_layout(fig, height=320)


def chart_forecast(df: pd.DataFrame, periods: int = 6) -> go.Figure:
    """Prophet-based monthly revenue forecast."""
    try:
        from prophet import Prophet
    except ImportError:
        return None

    completed = df[df["order_status"] == "completed"].copy()
    monthly = (
        completed.groupby("order_month")["line_total"]
        .sum()
        .reset_index()
        .rename(columns={"order_month": "ds", "line_total": "y"})
        .sort_values("ds")
    )
    monthly["ds"] = pd.to_datetime(monthly["ds"])

    if len(monthly) < 6:
        return None

    m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False,
                changepoint_prior_scale=0.3)
    m.fit(monthly)
    future = m.make_future_dataframe(periods=periods, freq="MS")
    forecast = m.predict(future)

    fig = go.Figure()
    # Historical
    fig.add_trace(go.Scatter(
        x=monthly["ds"], y=monthly["y"],
        mode="lines+markers", name="Actual",
        line=dict(color=ACCENT_CYAN, width=2.5),
        marker=dict(size=5),
        hovertemplate="<b>%{x|%b %Y}</b><br>₹%{y:,.0f}<extra></extra>",
    ))
    # Forecast
    future_only = forecast[forecast["ds"] > monthly["ds"].max()]
    fig.add_trace(go.Scatter(
        x=future_only["ds"], y=future_only["yhat"],
        mode="lines+markers", name="Forecast",
        line=dict(color=ACCENT_PURPLE, width=2.5, dash="dash"),
        marker=dict(size=5),
        hovertemplate="<b>%{x|%b %Y}</b><br>Forecast: ₹%{y:,.0f}<extra></extra>",
    ))
    # Confidence band
    fig.add_trace(go.Scatter(
        x=pd.concat([future_only["ds"], future_only["ds"][::-1]]),
        y=pd.concat([future_only["yhat_upper"], future_only["yhat_lower"][::-1]]),
        fill="toself",
        fillcolor="rgba(124,58,237,0.12)",
        line=dict(color="rgba(255,255,255,0)"),
        name="Confidence",
        hoverinfo="skip",
    ))
    fig.update_layout(title=f"Revenue Forecast — Next {periods} Months")
    return _chart_layout(fig, height=420)
