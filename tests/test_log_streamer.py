import pytest
from corral.log_streamer import _is_noise_line

def test_is_noise_line():
    # Empty or whitespace
    assert _is_noise_line("") is True
    assert _is_noise_line("   ") is True
    
    # Box drawing
    assert _is_noise_line("──────────") is True
    assert _is_noise_line("─── ───") is True
    
    # Status bar fragments
    assert _is_noise_line("worktree: main") is True
    assert _is_noise_line("model: claude-3") is True
    
    # Prompts
    assert _is_noise_line(">") is True
    assert _is_noise_line("❯ ") is True
    
    # Bare numbers
    assert _is_noise_line("1") is True
    assert _is_noise_line("  2  ") is True
    assert _is_noise_line("· 3") is True
    
    # TUI Noise
    assert _is_noise_line("Real-time Output Streaming") is True
    
    # Valid lines (Not noise)
    assert _is_noise_line("This is an actual log message") is False
    assert _is_noise_line("||PULSE:STATUS Working on it||") is False
    assert _is_noise_line("def foo():") is False
