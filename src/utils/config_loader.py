"""
Configuration Loader Utility
Loads YAML configuration files for the Payment Agent System.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# Default config directory
CONFIG_DIR = Path(__file__).parent.parent.parent / 'config'


def load_config(config_name: str, config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load a YAML configuration file.
    
    Args:
        config_name: Name of the config file (without .yaml extension)
        config_dir: Optional custom config directory
    
    Returns:
        Dictionary containing the configuration
    
    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid
    """
    if config_dir is None:
        config_dir = CONFIG_DIR
    
    config_path = config_dir / f"{config_name}.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    return config or {}


def load_agent_config() -> Dict[str, Any]:
    """Load agent configuration."""
    return load_config('agent_config')


def load_safety_rules() -> Dict[str, Any]:
    """Load safety rules configuration."""
    return load_config('safety_rules')


def load_simulation_config() -> Dict[str, Any]:
    """Load simulation configuration."""
    return load_config('simulation_config')


def get_config_value(config: Dict[str, Any], key_path: str, default: Any = None) -> Any:
    """
    Get a nested config value using dot notation.
    
    Args:
        config: Configuration dictionary
        key_path: Dot-separated path (e.g., 'agent.window_size_minutes')
        default: Default value if key not found
    
    Returns:
        The config value or default
    
    Example:
        >>> config = {'agent': {'window_size': 10}}
        >>> get_config_value(config, 'agent.window_size')
        10
    """
    keys = key_path.split('.')
    value = config
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value


# Quick access functions
def get_agent_setting(key_path: str, default: Any = None) -> Any:
    """Get a setting from agent config."""
    config = load_agent_config()
    return get_config_value(config, key_path, default)


def get_safety_limit(key_path: str, default: Any = None) -> Any:
    """Get a limit from safety rules."""
    config = load_safety_rules()
    return get_config_value(config, key_path, default)


if __name__ == '__main__':
    # Test the config loader
    print("Testing configuration loader...")
    
    try:
        agent_config = load_agent_config()
        print(f"✅ Agent config loaded: {len(agent_config)} sections")
        
        safety_rules = load_safety_rules()
        print(f"✅ Safety rules loaded: {len(safety_rules)} sections")
        
        sim_config = load_simulation_config()
        print(f"✅ Simulation config loaded: {len(sim_config)} sections")
        
        # Test nested access
        window_size = get_agent_setting('agent.window_size_minutes', 10)
        print(f"✅ Agent window size: {window_size} minutes")
        
        max_actions = get_safety_limit('limits.max_actions_per_hour', 10)
        print(f"✅ Max actions per hour: {max_actions}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
