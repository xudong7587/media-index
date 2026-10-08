"""Compatibility import for the built-in playback optimizer plugin."""
import sys
from plugins.playback_optimizer.gateway import transport as _implementation
sys.modules[__name__] = _implementation
