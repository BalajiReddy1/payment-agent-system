"""
Audit Logging
Maintains a complete audit trail of all agent decisions and actions.
Supports regulatory compliance and debugging.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AuditEntry:
    """Single audit log entry."""
    timestamp: str
    event_type: str  # decision, action, rollback, pattern, error
    details: Dict[str, Any]
    outcome: Optional[str] = None
    

class AuditLogger:
    """
    Maintains audit trail for all agent decisions.
    
    Every decision includes:
    - Context: What data triggered the analysis
    - Reasoning: Why this pattern is significant  
    - Options: What actions were considered
    - Decision: What was chosen and why
    - Outcome: Actual results vs predictions
    """
    
    def __init__(self, log_dir: Optional[Path] = None):
        self.entries: List[AuditEntry] = []
        self.log_dir = log_dir
        self.max_entries = 1000  # Keep last 1000 entries in memory
    
    def log_decision(
        self,
        pattern_type: str,
        options_considered: List[Dict],
        selected_action: Optional[Dict],
        reasoning: str,
        confidence: float
    ):
        """Log a decision made by the agent."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type='decision',
            details={
                'pattern_type': pattern_type,
                'options_count': len(options_considered),
                'options': [opt.get('type', 'unknown') for opt in options_considered],
                'selected': selected_action.get('type') if selected_action else None,
                'reasoning_summary': reasoning[:200],
                'confidence': confidence
            }
        )
        self._add_entry(entry)
    
    def log_action(
        self,
        action_type: str,
        target: str,
        parameters: Dict,
        authorization_level: str,
        expected_impact: Dict
    ):
        """Log an action executed by the agent."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type='action',
            details={
                'action_type': action_type,
                'target': target,
                'parameters': parameters,
                'authorization': authorization_level,
                'expected_impact': expected_impact
            }
        )
        self._add_entry(entry)
    
    def log_rollback(
        self,
        action_id: str,
        reason: str,
        metrics_before: Dict,
        metrics_after: Dict
    ):
        """Log a rollback event."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type='rollback',
            details={
                'action_id': action_id,
                'reason': reason,
                'metrics_before': metrics_before,
                'metrics_after': metrics_after
            }
        )
        self._add_entry(entry)
    
    def log_pattern(
        self,
        pattern_type: str,
        severity: float,
        affected_entities: List[str],
        hypotheses: List[Dict]
    ):
        """Log a detected pattern."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type='pattern',
            details={
                'pattern_type': pattern_type,
                'severity': severity,
                'affected': affected_entities,
                'hypotheses': [h.get('cause', 'unknown') for h in hypotheses]
            }
        )
        self._add_entry(entry)
    
    def log_outcome(
        self,
        action_id: str,
        predicted_impact: Dict,
        actual_impact: Dict,
        success: bool
    ):
        """Log the outcome of an action for learning."""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            event_type='outcome',
            details={
                'action_id': action_id,
                'predicted': predicted_impact,
                'actual': actual_impact,
                'success': success,
                'prediction_accuracy': self._calc_accuracy(predicted_impact, actual_impact)
            }
        )
        self._add_entry(entry)
    
    def _add_entry(self, entry: AuditEntry):
        """Add entry to log, maintaining size limit."""
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]
    
    def _calc_accuracy(self, predicted: Dict, actual: Dict) -> float:
        """Calculate prediction accuracy."""
        if not predicted or not actual:
            return 0.0
        
        pred_rate = predicted.get('success_rate_delta', 0)
        actual_rate = actual.get('success_rate_delta', 0)
        
        if pred_rate == 0:
            return 1.0 if actual_rate == 0 else 0.0
        
        accuracy = 1 - abs(pred_rate - actual_rate) / abs(pred_rate)
        return max(0, min(1, accuracy))
    
    def get_recent_entries(
        self,
        event_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent audit entries."""
        entries = self.entries
        
        if event_type:
            entries = [e for e in entries if e.event_type == event_type]
        
        return [asdict(e) for e in entries[-limit:]]
    
    def get_decision_trail(self, action_id: str) -> List[Dict]:
        """Get the complete decision trail for an action."""
        return [
            asdict(e) for e in self.entries 
            if e.details.get('action_id') == action_id
        ]
    
    def export_to_json(self, filepath: Path):
        """Export audit log to JSON file."""
        with open(filepath, 'w') as f:
            json.dump([asdict(e) for e in self.entries], f, indent=2)
