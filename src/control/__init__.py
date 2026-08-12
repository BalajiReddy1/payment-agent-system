"""Control plane: the versioned policy document the agent writes to."""

from src.control.plane import ControlPlane, ControlPlaneRevision, diff

__all__ = ['ControlPlane', 'ControlPlaneRevision', 'diff']
