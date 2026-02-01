"""
Reusable UI Components for Dashboard
Clean, minimal components for consistent UI.
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import Dict, List, Optional


def render_header(is_active: bool = True):
    """Render the dashboard header."""
    col1, col2 = st.columns([4, 1])
    
    with col1:
        st.markdown("# 🏦 Payment Operations Command Center")
    
    with col2:
        status = "🟢 Active" if is_active else "🔴 Inactive"
        st.markdown(
            f"<div style='text-align: right; padding-top: 20px;'>"
            f"<span style='color: #8888aa;'>{datetime.now().strftime('%H:%M:%S')}</span><br/>"
            f"<span style='font-weight: 600;'>{status}</span></div>",
            unsafe_allow_html=True
        )


def render_pattern_card(pattern: Dict):
    """Render a detected pattern card."""
    from dashboard.styles import get_severity_emoji, get_severity_color
    
    severity = pattern.get('severity', 0)
    emoji = get_severity_emoji(severity)
    color = get_severity_color(severity)
    
    st.markdown(
        f"""
        <div style='
            background: linear-gradient(135deg, #1e1e30 0%, #252540 100%);
            border-left: 4px solid {color};
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 12px;
        '>
            <div style='display: flex; justify-content: space-between; align-items: center;'>
                <span style='font-weight: 600; color: #ffffff;'>
                    {emoji} {pattern.get('type', 'Unknown').replace('_', ' ').title()}
                </span>
                <span style='color: #8888aa; font-size: 12px;'>
                    Confidence: {pattern.get('confidence', 0):.0%}
                </span>
            </div>
            <div style='color: #aaaacc; font-size: 13px; margin-top: 6px;'>
                {pattern.get('description', '')}
            </div>
            <div style='color: #666688; font-size: 12px; margin-top: 4px;'>
                Affected: {pattern.get('affected', 'N/A')}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_intervention_pill(intervention: Dict):
    """Render an active intervention indicator."""
    action_type = intervention.get('type', 'Unknown')
    target = intervention.get('target', 'N/A')
    executed_at = intervention.get('executed_at', '')
    
    # Calculate time remaining (assume 15 min duration)
    if executed_at:
        try:
            exec_time = datetime.fromisoformat(executed_at)
            elapsed = (datetime.now() - exec_time).seconds // 60
            remaining = max(15 - elapsed, 0)
            time_str = f"{remaining} min left"
        except:
            time_str = "Active"
    else:
        time_str = "Active"
    
    icon_map = {
        'circuit_breaker': '🔒',
        'adjust_retry': '🔄',
        'route_change': '🔀',
        'method_suppress': '🚫',
        'alert_ops': '🚨',
    }
    icon = icon_map.get(action_type, '⚡')
    
    st.markdown(
        f"""
        <div style='
            background: linear-gradient(135deg, #2a2a4a 0%, #353560 100%);
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        '>
            <span style='color: #ffffff;'>
                {icon} <strong>{action_type.replace('_', ' ').title()}</strong>
                <span style='color: #8888aa;'> on {target}</span>
            </span>
            <span style='
                background: #3a3a5c;
                color: #aaaacc;
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 11px;
            '>{time_str}</span>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_decision_log_entry(action: Dict, index: int):
    """Render a decision log entry."""
    action_type = action.get('type', 'Unknown')
    target = action.get('target', 'N/A')
    risk_level = action.get('risk_level', 'low')
    
    risk_colors = {
        'low': '#00d26a',
        'medium': '#ffc107',
        'high': '#ff6b6b',
        'critical': '#ee5a5a'
    }
    risk_color = risk_colors.get(risk_level, '#8888aa')
    
    timestamp = datetime.now() - timedelta(minutes=index * 3)
    
    st.markdown(
        f"""
        <div style='
            padding: 8px 0;
            border-bottom: 1px solid #2a2a4a;
            display: flex;
            justify-content: space-between;
            align-items: center;
        '>
            <span style='color: #666688; font-size: 12px;'>
                [{timestamp.strftime('%H:%M:%S')}]
            </span>
            <span style='color: #ffffff; flex: 1; margin-left: 12px;'>
                <strong>{action_type.upper()}</strong> on {target}
            </span>
            <span style='
                color: {risk_color};
                font-size: 11px;
                text-transform: uppercase;
            '>{risk_level} Risk ✓</span>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_empty_state(message: str, icon: str = "📭"):
    """Render an empty state placeholder."""
    st.markdown(
        f"""
        <div style='
            text-align: center;
            padding: 40px 20px;
            color: #666688;
        '>
            <div style='font-size: 48px;'>{icon}</div>
            <div style='margin-top: 12px;'>{message}</div>
        </div>
        """,
        unsafe_allow_html=True
    )
