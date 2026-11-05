"""Shared UI helpers: page chrome, status pills, cards. Restrained dark
palette - one accent colour, semantic status colours only."""

from __future__ import annotations

import streamlit as st

STATUS_COLORS = {
    "open": "#9aa4b2", "investigating": "#4f8bf9",
    "diagnosed": "#7c9cff", "awaiting_approval": "#f5a623",
    "approved": "#2ecc71", "rejected": "#9aa4b2",
    "resolved": "#2ecc71", "failed": "#e74c3c", "escalated": "#e74c3c",
    "RESOLVED": "#2ecc71", "PARTIALLY_RESOLVED": "#f5a623",
    "NOT_RESOLVED": "#e74c3c", "VERIFICATION_FAILED": "#e74c3c",
}

CSS = """
<style>
    .block-container { padding-top: 1.6rem; padding-bottom: 3rem;
                       max-width: 1240px; }
    .ks-card { background: #171c26; border: 1px solid #232a36;
               border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: .8rem; }
    .ks-pill { display: inline-block; padding: .12rem .6rem; border-radius: 999px;
               font-size: .78rem; font-weight: 600; letter-spacing: .02em; }
    .ks-muted { color: #9aa4b2; }
    .ks-metric-label { color: #9aa4b2; font-size: .8rem;
                       text-transform: uppercase; letter-spacing: .06em; }
    .ks-evidence { border-left: 3px solid #4f8bf9; padding: .3rem .7rem;
                   margin: .35rem 0; background: #141924; border-radius: 4px; }
</style>
"""


def page_chrome(title: str, subtitle: str = "") -> None:
    st.set_page_config(page_title=f"KubeSentra — {title}",
                       page_icon="◼", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f"## {title}")
    if subtitle:
        st.markdown(f'<span class="ks-muted">{subtitle}</span>',
                    unsafe_allow_html=True)
    st.markdown("---")


def pill(text: str) -> str:
    color = STATUS_COLORS.get(text, "#9aa4b2")
    return (f'<span class="ks-pill" style="background:{color}22;'
            f'color:{color};border:1px solid {color}55">{text}</span>')


def card(html: str) -> None:
    st.markdown(f'<div class="ks-card">{html}</div>', unsafe_allow_html=True)


def metric_row(pairs: list[tuple[str, str, str | None]]) -> None:
    """pairs of (label, value, delta-ish hint)."""
    cols = st.columns(len(pairs))
    for col, (label, value, hint) in zip(cols, pairs):
        col.markdown(
            f'<div class="ks-card"><div class="ks-metric-label">{label}</div>'
            f'<div style="font-size:1.55rem;font-weight:700">{value}</div>'
            + (f'<div class="ks-muted">{hint}</div>' if hint else "")
            + "</div>", unsafe_allow_html=True)


def api_error(exc: Exception) -> None:
    st.error(f"Backend unavailable: {exc}. Is the API running on "
             f"the configured DASHBOARD_API_URL?")
