"""
Custom CSS Styles for Dashboard
Clean, modern dark theme with fintech aesthetic.
"""

DARK_THEME = """
<style>
    /* Main background */
    .stApp {
        background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
    }
    
    /* Metric cards */
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #1e1e30 0%, #252540 100%);
        border: 1px solid #3a3a5c;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }
    
    div[data-testid="metric-container"] label {
        color: #8888aa !important;
        font-size: 14px !important;
    }
    
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 28px !important;
        font-weight: 600 !important;
    }
    
    /* Positive delta */
    div[data-testid="stMetricDelta"] svg[data-testid="stMetricDeltaIcon-Up"] {
        color: #00d26a !important;
    }
    
    /* Negative delta */
    div[data-testid="stMetricDelta"] svg[data-testid="stMetricDeltaIcon-Down"] {
        color: #ff6b6b !important;
    }
    
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #16162b 0%, #1a1a35 100%);
        border-right: 1px solid #2a2a4a;
    }
    
    section[data-testid="stSidebar"] .stButton button {
        background: linear-gradient(135deg, #ff6b35 0%, #f7461c 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 600;
        width: 100%;
        transition: all 0.3s ease;
    }
    
    section[data-testid="stSidebar"] .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(255, 107, 53, 0.4);
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #ffffff !important;
    }
    
    /* Expander */
    .streamlit-expanderHeader {
        background: #1e1e30;
        border-radius: 8px;
    }
    
    /* Divider */
    hr {
        border-color: #3a3a5c;
    }
    
    /* Status badges */
    .status-active {
        background: linear-gradient(135deg, #00d26a 0%, #00b85c 100%);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
    
    .status-warning {
        background: linear-gradient(135deg, #ffc107 0%, #ff9800 100%);
        color: #1a1a2e;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
    
    .status-critical {
        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a5a 100%);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
</style>
"""

def get_severity_color(severity: float) -> str:
    """Get color based on severity level."""
    if severity >= 0.7:
        return "#ff6b6b"  # Red
    elif severity >= 0.5:
        return "#ffc107"  # Yellow
    elif severity >= 0.3:
        return "#ffa726"  # Orange
    else:
        return "#00d26a"  # Green

def get_severity_emoji(severity: float) -> str:
    """Get emoji based on severity level."""
    if severity >= 0.7:
        return "🔴"
    elif severity >= 0.5:
        return "🟠"
    elif severity >= 0.3:
        return "🟡"
    else:
        return "🟢"
