"""
Augent Banner - ASCII art banner generator using pyfiglet ansi_shadow font.

Used for CLI splash, MCP startup, and as an MCP tool.
"""

import sys

import pyfiglet

# Augent brand green #00F060
AUGENT_GREEN = "\033[38;2;0;240;96m"
RESET = "\033[0m"

COLORS = {
    "green": "\033[38;2;0;240;96m",
    "purple": "\033[38;2;140;100;220m",
    "cyan": "\033[38;2;0;220;220m",
    "red": "\033[38;2;255;80;80m",
    "yellow": "\033[38;2;255;200;50m",
    "white": "\033[38;2;255;255;255m",
    "blue": "\033[38;2;80;140;255m",
    "orange": "\033[38;2;255;160;50m",
    "pink": "\033[38;2;255;100;200m",
    "teal": "\033[38;2;0;200;160m",
}


def render_banner(text="AUGENT", color="green", plain=False):
    """Render text as ASCII art banner.

    Args:
        text: Text to render (default: AUGENT)
        color: Color name from COLORS dict, or hex like '#FF0000' (default: green)
        plain: If True, return without ANSI color codes

    Returns:
        The rendered banner string.
    """
    banner = pyfiglet.figlet_format(text, font="ansi_shadow")
    # Strip trailing whitespace/empty lines
    lines = banner.rstrip().split("\n")

    if plain:
        return "\n".join(lines)

    # Resolve color
    ansi = _resolve_color(color)
    colored = "\n".join(f"{ansi}{line}{RESET}" for line in lines)
    return colored


def _resolve_color(color):
    """Resolve a color name or hex code to an ANSI escape sequence."""
    if color in COLORS:
        return COLORS[color]
    # Try hex code (#RRGGBB or RRGGBB)
    hex_str = color.lstrip("#")
    if len(hex_str) == 6:
        try:
            r, g, b = (
                int(hex_str[0:2], 16),
                int(hex_str[2:4], 16),
                int(hex_str[4:6], 16),
            )
            return f"\033[38;2;{r};{g};{b}m"
        except ValueError:
            pass
    return AUGENT_GREEN


def print_banner(text="AUGENT", color="green", file=sys.stderr):
    """Print the banner to a file (default: stderr)."""
    print(render_banner(text, color), file=file)
