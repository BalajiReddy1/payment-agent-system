"""
Payment Operations Command Center
Production-quality Streamlit dashboard for monitoring the Payment Agent System.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from adk_agent import analyze_and_act
from payment_tools import executor as shared_executor, agent_state as shared_state
from dashboard.components import (
    render_decision_log_entry,
    render_empty_state,
    render_header,
    render_intervention_pill,
    render_pattern_card,
)
from dashboard.styles import DARK_THEME
from src.agent.core import PaymentAgent
from src.models.state import PaymentMethod
from src.safety.guardrails import SafetyGuardrails, SafetyLimits, AuthorizationLevel
from src.simulation.payment_simulator import PaymentSimulator

# Page configuration
st.set_page_config(
    page_title="Payment Operations Command Center",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Apply dark theme
st.markdown(DARK_THEME, unsafe_allow_html=True)


# Initialize session state
def init_session_state():
    """Initialize session state variables."""
    if 'agent' not in st.session_state:
        st.session_state.agent = PaymentAgent(
            window_size_minutes=5,
            analysis_interval_seconds=10,
            auto_approve_low_risk=True
        )
        # Force unified state
        st.session_state.agent.executor = shared_executor
        st.session_state.agent.state = shared_state
    
    if 'simulator' not in st.session_state:
        st.session_state.simulator = PaymentSimulator(base_success_rate=0.95)
    
    if 'cycle_history' not in st.session_state:
        st.session_state.cycle_history = []
    
    if 'last_cycle_time' not in st.session_state:
        st.session_state.last_cycle_time = 0
    
    if 'safety' not in st.session_state:
        st.session_state.safety = SafetyGuardrails(SafetyLimits())
        
    if 'agent_result' not in st.session_state:
        st.session_state.agent_result = None


def run_agent_cycle():
    """Generate transactions and run agent cycle."""
    agent = st.session_state.agent
    simulator = st.session_state.simulator
    
    # Generate transactions
    transactions = simulator.generate_stream(count=25, start_time=datetime.now())
    agent.process_batch(transactions)
    
    # Clean up expired scenarios
    simulator.cleanup_expired_scenarios()
    
    # Run agent cycle
    results = agent.run_cycle()
    
    # Store in history (keep last 20)
    st.session_state.cycle_history.append({
        'timestamp': datetime.now(),
        'success_rate': results['observation_summary']['overall_success_rate'],
        'latency': results['observation_summary']['overall_latency']['mean'],
        'transactions': results['observation_summary']['total_transactions'],
        'patterns': len(results['patterns_detected']),
        'actions': len(results['actions_taken']),
        'results': results
    })
    
    if len(st.session_state.cycle_history) > 20:
        st.session_state.cycle_history = st.session_state.cycle_history[-20:]
    
    return results


def render_sidebar():
    """Render the scenario injection sidebar."""
    simulator = st.session_state.simulator
    
    st.sidebar.markdown("## 🔥 Inject Scenarios")
    st.sidebar.markdown("---")
    
    # Issuer Degradation
    st.sidebar.markdown("### Issuer Degradation")
    issuer = st.sidebar.selectbox(
        "Select Issuer",
        simulator.issuers,
        key="issuer_select"
    )
    issuer_severity = st.sidebar.slider(
        "Severity",
        min_value=0.2,
        max_value=0.9,
        value=0.6,
        step=0.1,
        key="issuer_severity"
    )
    if st.sidebar.button("⚡ Inject Issuer Failure", key="inject_issuer"):
        simulator.inject_issuer_degradation(issuer, severity=issuer_severity, duration_seconds=120)
        st.sidebar.success(f"Injected {issuer} degradation!")
    
    st.sidebar.markdown("---")
    
    # Retry Storm
    st.sidebar.markdown("### Retry Storm")
    retry_duration = st.sidebar.slider(
        "Duration (seconds)",
        min_value=60,
        max_value=300,
        value=120,
        step=30,
        key="retry_duration"
    )
    if st.sidebar.button("🌪️ Inject Retry Storm", key="inject_retry"):
        simulator.inject_retry_storm(duration_seconds=retry_duration)
        st.sidebar.success("Injected retry storm!")
    
    st.sidebar.markdown("---")
    
    # Latency Spike
    st.sidebar.markdown("### Latency Spike")
    latency_mult = st.sidebar.slider(
        "Multiplier",
        min_value=2.0,
        max_value=5.0,
        value=3.0,
        step=0.5,
        key="latency_mult"
    )
    if st.sidebar.button("⏱️ Inject Latency Spike", key="inject_latency"):
        simulator.inject_latency_spike(multiplier=latency_mult, duration_seconds=90)
        st.sidebar.success(f"Injected {latency_mult}x latency spike!")
    
    st.sidebar.markdown("---")
    
    # Clear All
    if st.sidebar.button("🧹 Clear All Scenarios", key="clear_all"):
        simulator.failure_scenarios.clear()
        st.sidebar.success("All scenarios cleared!")
    
    # Active scenarios display
    active = simulator.get_active_scenarios()
    if active:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Active Scenarios")
        for scenario in active:
            st.sidebar.markdown(f"• {scenario['type']}")


def render_kpi_cards(results: dict):
    """Render the KPI metric cards."""
    summary = results.get('observation_summary', {})
    history = st.session_state.cycle_history
    
    # Calculate deltas
    if len(history) >= 2:
        prev = history[-2]
        success_delta = summary['overall_success_rate'] - prev['success_rate']
        latency_delta = summary['overall_latency']['mean'] - prev['latency']
    else:
        success_delta = 0
        latency_delta = 0
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="💰 Success Rate",
            value=f"{summary['overall_success_rate']:.1%}",
            delta=f"{success_delta:+.1%}" if success_delta != 0 else None,
            delta_color="normal"
        )
    
    with col2:
        st.metric(
            label="⚡ Avg Latency",
            value=f"{summary['overall_latency']['mean']:.0f}ms",
            delta=f"{latency_delta:+.0f}ms" if latency_delta != 0 else None,
            delta_color="inverse"
        )
    
    with col3:
        st.metric(
            label="📊 Transactions",
            value=f"{summary['total_transactions']:,}",
            delta=None
        )
    
    with col4:
        agent = st.session_state.agent
        st.metric(
            label="🎯 Agent Actions",
            value=f"{agent.state.actions_executed}",
            delta=f"+{len(results.get('actions_taken', []))}" if results.get('actions_taken') else None
        )


def render_anomaly_gauge(results: dict):
    """Render real-time anomaly score gauge."""
    st.markdown("#### 🎯 System Health Score")
    
    # Calculate anomaly score based on patterns and metrics
    summary = results.get('observation_summary', {})
    patterns = results.get('patterns_detected', [])
    
    # Base score from success rate
    success_rate = summary.get('overall_success_rate', 0.95)
    base_score = success_rate * 100
    
    # Penalty for patterns
    pattern_penalty = len(patterns) * 10
    
    # Final score (capped at 0-100)
    health_score = max(0, min(100, base_score - pattern_penalty))
    
    # Determine color and status
    if health_score >= 90:
        color = '#00d26a'
        status = 'HEALTHY'
    elif health_score >= 70:
        color = '#ffc107'
        status = 'WARNING'
    else:
        color = '#ff5252'
        status = 'CRITICAL'
    
    # Create gauge using plotly
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=health_score,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': status, 'font': {'size': 20, 'color': color}},
        number={'font': {'size': 40, 'color': color}},
        gauge={
            'axis': {'range': [0, 100], 'tickcolor': '#8888aa'},
            'bar': {'color': color},
            'bgcolor': '#1a1a2e',
            'bordercolor': '#2a2a5a',
            'steps': [
                {'range': [0, 70], 'color': 'rgba(255, 82, 82, 0.2)'},
                {'range': [70, 90], 'color': 'rgba(255, 193, 7, 0.2)'},
                {'range': [90, 100], 'color': 'rgba(0, 210, 106, 0.2)'}
            ],
            'threshold': {
                'line': {'color': 'white', 'width': 2},
                'thickness': 0.75,
                'value': health_score
            }
        }
    ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        font_color='#8888aa',
        height=200,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    
    st.plotly_chart(fig, width='stretch')


def render_explainability(results: dict):
    """Render decision explainability panel."""
    st.markdown("#### 🧠 Decision Explainability")
    
    actions = results.get('actions_taken', [])
    patterns = results.get('patterns_detected', [])
    
    if not actions and not patterns:
        st.markdown("""
        <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                    border-radius: 10px; padding: 20px; border: 1px solid #2a2a5a;
                    text-align: center; color: #8888aa;'>
            ✨ System operating normally. No interventions needed.
        </div>
        """, unsafe_allow_html=True)
        return
    
    # Show pattern detection reasoning
    if patterns:
        for pattern in patterns[:2]:  # Show max 2
            pattern_type = pattern.get('type', pattern.get('pattern_type', 'Unknown'))
            affected = pattern.get('affected', pattern.get('affected_value', 'Unknown'))
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                        border-radius: 10px; padding: 15px; border: 1px solid #ffc107;
                        margin-bottom: 10px;'>
                <div style='color: #ffc107; font-weight: bold; margin-bottom: 8px;'>
                    🔍 Pattern Detected: {pattern_type.replace('_', ' ').title()}
                </div>
                <div style='color: #8888aa; font-size: 0.9rem;'>
                    <b>Why detected:</b> Severity {pattern.get('severity', 0):.0%} exceeds threshold<br>
                    <b>Affected:</b> {affected}<br>
                    <b>Confidence:</b> {pattern.get('confidence', 0):.0%}
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    # Show action reasoning
    if actions:
        for action in actions[:2]:  # Show max 2
            action_type = action.get('type', action.get('action_type', 'Unknown'))
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                        border-radius: 10px; padding: 15px; border: 1px solid #00d26a;
                        margin-bottom: 10px;'>
                <div style='color: #00d26a; font-weight: bold; margin-bottom: 8px;'>
                    ⚡ Action Taken: {action_type.replace('_', ' ').title()}
                </div>
                <div style='color: #8888aa; font-size: 0.9rem;'>
                    <b>Target:</b> {action.get('target', 'System')}<br>
                    <b>Reasoning:</b> {action.get('reasoning', 'Optimize system performance')[:100]}<br>
                    <b>Expected Impact:</b> +{action.get('estimated_impact', {}).get('success_rate_delta', 0):.1%} success rate
                </div>
            </div>
            """, unsafe_allow_html=True)


def render_charts():
    """Render the trend charts."""
    history = st.session_state.cycle_history
    
    if len(history) < 2:
        st.info("📊 Collecting data... Charts will appear after a few cycles.")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Success Rate Trend")
        df = pd.DataFrame([
            {'Cycle': i+1, 'Success Rate': h['success_rate'] * 100}
            for i, h in enumerate(history)
        ])
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df['Cycle'],
            y=df['Success Rate'],
            mode='lines+markers',
            line=dict(color='#00d26a', width=3),
            marker=dict(size=8),
            fill='tozeroy',
            fillcolor='rgba(0, 210, 106, 0.1)'
        ))
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#8888aa',
            xaxis=dict(gridcolor='#2a2a4a', title=''),
            yaxis=dict(gridcolor='#2a2a4a', title='%', range=[0, 100]),
            margin=dict(l=40, r=20, t=20, b=40),
            height=250
        )
        st.plotly_chart(fig, width='stretch')
    
    with col2:
        st.markdown("#### Latency Trend")
        df = pd.DataFrame([
            {'Cycle': i+1, 'Latency': h['latency']}
            for i, h in enumerate(history)
        ])
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df['Cycle'],
            y=df['Latency'],
            mode='lines+markers',
            line=dict(color='#ffc107', width=3),
            marker=dict(size=8),
            fill='tozeroy',
            fillcolor='rgba(255, 193, 7, 0.1)'
        ))
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#8888aa',
            xaxis=dict(gridcolor='#2a2a4a', title=''),
            yaxis=dict(gridcolor='#2a2a4a', title='ms'),
            margin=dict(l=40, r=20, t=20, b=40),
            height=250
        )
        st.plotly_chart(fig, width='stretch')


def render_issuer_health():
    """Render issuer health bar chart."""
    st.markdown("#### 🏦 Issuer Health")
    
    observer = st.session_state.agent.observer
    stats = observer.stats.get('by_issuer', {})
    
    if not stats:
        st.info("📊 Waiting for issuer data...")
        return
    
    # Build data for chart
    issuer_data = []
    for issuer, data in stats.items():
        total = data.get('success', 0) + data.get('failed', 0)
        if total > 0:
            success_rate = data.get('success', 0) / total * 100
            issuer_data.append({
                'Issuer': issuer.replace('_', ' ').title(),
                'Success Rate': success_rate,
                'Transactions': total
            })
    
    if not issuer_data:
        st.info("📊 No issuer data yet...")
        return
    
    df = pd.DataFrame(issuer_data).sort_values('Success Rate', ascending=True)
    
    # Color based on success rate
    colors = ['#ff5252' if sr < 85 else '#ffc107' if sr < 95 else '#00d26a' 
              for sr in df['Success Rate']]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df['Success Rate'],
        y=df['Issuer'],
        orientation='h',
        marker_color=colors,
        text=[f"{sr:.1f}% ({t})" for sr, t in zip(df['Success Rate'], df['Transactions'])],
        textposition='inside',
        textfont=dict(color='white')
    ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font_color='#8888aa',
        xaxis=dict(gridcolor='#2a2a4a', title='Success Rate %', range=[0, 100]),
        yaxis=dict(gridcolor='#2a2a4a', title=''),
        margin=dict(l=100, r=20, t=20, b=40),
        height=250,
        showlegend=False
    )
    
    st.plotly_chart(fig, width='stretch')


def render_patterns_and_interventions(results: dict):
    """Render patterns and active interventions panels."""
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🔍 Detected Patterns")
        patterns = results.get('patterns_detected', [])
        
        if patterns:
            for pattern in patterns[:5]:  # Limit to 5
                render_pattern_card(pattern)
        else:
            render_empty_state("No patterns detected", "✅")
    
    with col2:
        st.markdown("#### 🛡️ Active Interventions")
        agent = st.session_state.agent
        interventions = agent.executor.get_active_interventions()
        
        if interventions:
            for intervention in interventions:
                render_intervention_pill({
                    'type': intervention.action_type.value,
                    'target': intervention.target,
                    'executed_at': intervention.executed_at.isoformat() if intervention.executed_at else None
                })
        else:
            render_empty_state("No active interventions", "🛡️")


def render_safety_guardrails():
    """Render the safety guardrails panel."""
    st.markdown("#### 🛡️ Safety Guardrails")
    
    safety = st.session_state.safety
    limits = safety.limits
    agent = st.session_state.agent
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                    border-radius: 10px; padding: 15px; border: 1px solid #2a2a5a;'>
            <div style='color: #00d26a; font-size: 0.9rem; margin-bottom: 5px;'>
                🔐 Authorization Levels
            </div>
            <div style='color: #8888aa; font-size: 0.8rem;'>
                • <span style='color: #00d26a;'>AUTOMATIC</span>: Retry, Alerts<br>
                • <span style='color: #ffc107;'>SEMI-AUTO</span>: Circuit Breaker, Routing<br>
                • <span style='color: #ff5252;'>MANUAL</span>: Method Suppress
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        actions_used = agent.state.actions_executed
        max_actions = limits.max_actions_per_hour * 24
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                    border-radius: 10px; padding: 15px; border: 1px solid #2a2a5a;'>
            <div style='color: #ffc107; font-size: 0.9rem; margin-bottom: 5px;'>
                ⚡ Safety Limits
            </div>
            <div style='color: #8888aa; font-size: 0.8rem;'>
                • Max Traffic Impact: <b>{limits.max_traffic_impact_percent}%</b><br>
                • Actions Used: <b>{actions_used}/{max_actions}</b><br>
                • Max Rollbacks/hr: <b>{limits.max_rollbacks_per_hour}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        rollbacks = agent.state.rollbacks_last_hour
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                    border-radius: 10px; padding: 15px; border: 1px solid #2a2a5a;'>
            <div style='color: #ff5252; font-size: 0.9rem; margin-bottom: 5px;'>
                🔄 Rollback Triggers
            </div>
            <div style='color: #8888aa; font-size: 0.8rem;'>
                • Success Drop: <b>5%</b> → Rollback<br>
                • Latency Spike: <b>50%</b> → Rollback<br>
                • Recent Rollbacks: <b>{rollbacks}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)


def render_decision_log(results: dict):
    """Render the decision log section with Gemini integration."""
    st.markdown("#### 📜 Recent Decisions (inc. 🤖 Gemini-led)")
    
    # Unified log from the shared executor
    all_logs = shared_executor.get_execution_history(limit=10)
    
    if all_logs:
        # Reverse to show newest first
        for i, log in enumerate(reversed(all_logs)):
            # Add a small visual tag if it was a Gemini-led action
            is_gemini = "Gemini" in log.get('reasoning', '') or "MCP" in log.get('reasoning', '')
            tag = " 🤖 <span style='color: #00d26a; font-size: 0.8rem;'>GEMINI AGENT</span>" if is_gemini else ""
            
            with st.expander(f"Action: {log['action_type'].replace('_', ' ').title()} - {log['target']}{tag}", expanded=(i == 0)):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Status:** {'✅ Success' if log['success'] else '❌ Failed'}")
                    st.write(f"**Time:** {log['executed_at']}")
                with col2:
                    st.write(f"**Message:** {log['message']}")
                st.write(f"**Parameters:** `{log['parameters']}`")
    else:
        st.markdown(
            "<div style='color: #666688; text-align: center; padding: 20px;'>"
            "No recorded decisions in this session</div>",
            unsafe_allow_html=True
        )


def main():
    """Main dashboard application."""
    init_session_state()
    
    # Header
    render_header(st.session_state.agent.state.is_active)
    
    # --- Agentic Reasoning Section ---
    st.divider()
    st.header("🧠 Agentic Reasoning (Gemini + MCP)")
    scenario_text = st.text_area("Simulated Scenario:", value="ALERT: ICICI Bank success rate dropped to 70%")
    
    col_a, col_b = st.columns([1, 5])
    with col_a:
        deploy_clicked = st.button("Deploy AI Agent", type="primary", use_container_width=True)
    with col_b:
        if st.button("Clear Analysis", use_container_width=True):
            st.session_state.agent_result = None
            st.rerun()

    if deploy_clicked:
        with st.spinner("Gemini is analyzing and deploying tools..."):
            result = analyze_and_act(scenario_text)
            st.session_state.agent_result = result
            st.rerun() # Force a rerun to show the state-stored result immediately
            
    # Display the persisted result if it exists
    if st.session_state.agent_result:
        res = st.session_state.agent_result
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.info(f"**Gemini reasoning:**\n\n{res.get('agent_reasoning')}")
        with c2:
            if res.get("tool_called"):
                st.success(f"🛠️ **Tool Deployed:**\n\n`{res.get('tool_called')}`")
                with st.expander("Tool Output Details"):
                    st.code(res.get("tool_result"))
    
    # Update global state in agent for frontend consistency
    st.session_state.agent.state = shared_state
    
    # Sidebar
    render_sidebar()
    
    st.markdown("---")
    
    # Run cycle if enough time has passed
    current_time = time.time()
    if current_time - st.session_state.last_cycle_time >= 5:
        results = run_agent_cycle()
        st.session_state.last_cycle_time = current_time
    else:
        # Use last results
        if st.session_state.cycle_history:
            results = st.session_state.cycle_history[-1]['results']
        else:
            results = run_agent_cycle()
            st.session_state.last_cycle_time = current_time
    
    # KPI Cards
    render_kpi_cards(results)
    
    # Anomaly Gauge and Explainability side by side
    col1, col2 = st.columns([1, 2])
    with col1:
        render_anomaly_gauge(results)
    with col2:
        render_explainability(results)
    
    st.markdown("---")
    
    # Charts
    render_charts()
    
    # Issuer Health Chart
    render_issuer_health()
    
    st.markdown("---")
    
    # Patterns and Interventions
    render_patterns_and_interventions(results)
    
    st.markdown("---")
    
    # Safety Guardrails
    render_safety_guardrails()
    
    st.markdown("---")
    
    # Decision Log
    render_decision_log(results)
    
    # Auto-refresh
    time.sleep(0.1)
    st.rerun()


if __name__ == "__main__":
    main()
