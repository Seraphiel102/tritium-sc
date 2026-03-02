# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shared BGR color constants from CYBERCORE CSS for OpenCV analysis.

All colors are in BGR format (OpenCV native). Hex values in comments
are RGB (CSS native). Import from here instead of hardcoding in each test.
"""

# Primary UI colors
CYAN_PRIMARY_BGR = (255, 240, 0)       # #00f0ff
MAGENTA_BGR = (109, 42, 255)           # #ff2a6d
GREEN_BGR = (161, 255, 5)              # #05ffa1
YELLOW_BGR = (10, 238, 252)            # #fcee0a

# Alliance colors (same as above, aliased for clarity)
FRIENDLY_GREEN_BGR = GREEN_BGR
HOSTILE_RED_BGR = MAGENTA_BGR
NEUTRAL_BLUE_BGR = (255, 160, 0)       # #00a0ff
UNKNOWN_YELLOW_BGR = YELLOW_BGR

# Background colors
VOID_BLACK_BGR = (15, 10, 10)          # #0a0a0f
DARK_BG_BGR = (26, 18, 18)            # #12121a
MID_GRAY_BGR = (58, 42, 42)           # #2a2a3a

# Text colors
LIGHT_TEXT_BGR = (224, 224, 224)       # #e0e0e0
WHITE_BGR = (255, 255, 255)           # #ffffff

# Alert / accent
ORANGE_BGR = (0, 165, 255)            # #ffa500

# Full palette for compliance checking
CYBERCORE_PALETTE = {
    "cyan": CYAN_PRIMARY_BGR,
    "magenta": MAGENTA_BGR,
    "green": GREEN_BGR,
    "yellow": YELLOW_BGR,
    "void_black": VOID_BLACK_BGR,
    "dark_bg": DARK_BG_BGR,
    "mid_gray": MID_GRAY_BGR,
    "light_text": LIGHT_TEXT_BGR,
    "white": WHITE_BGR,
    "orange": ORANGE_BGR,
    "neutral_blue": NEUTRAL_BLUE_BGR,
}
