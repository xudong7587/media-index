"""Legacy import namespace; execution code lives in the plugin package."""
from pathlib import Path
__path__ = [str(Path(__file__).resolve().parent.parent / "plugins" / "playback_optimizer" / "worker")]
