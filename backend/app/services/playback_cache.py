"""Compatibility import for the built-in playback optimizer plugin."""
import sys
from plugins.playback_optimizer.gateway import cache as _implementation
sys.modules[__name__] = _implementation
