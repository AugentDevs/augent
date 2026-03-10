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

    Uses background-colored spaces instead of Unicode block characters so the
    banner renders identically across all terminals (iTerm2, Terminal.app, SSH).

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

    # Convert Unicode block/box-drawing chars to background-colored spaces.
    # The ansi_shadow font uses █╗╔╚╝║═ which have "Ambiguous" Unicode width
    # and render inconsistently across terminals. Background-colored spaces
    # always fill exactly one cell.
    ansi_bg = _resolve_color_bg(color)
    result_lines = []
    for line in lines:
        out = ""
        in_block = False
        for ch in line:
            if ch != " ":
                if not in_block:
                    out += ansi_bg
                    in_block = True
                out += " "
            else:
                if in_block:
                    out += RESET
                    in_block = False
                out += " "
        if in_block:
            out += RESET
        result_lines.append(out)
    return "\n".join(result_lines)


def _resolve_color(color):
    """Resolve a color name or hex code to an ANSI foreground escape sequence."""
    if color in COLORS:
        return COLORS[color]
    r, g, b = _parse_hex(color)
    if r is not None:
        return f"\033[38;2;{r};{g};{b}m"
    return AUGENT_GREEN


def _resolve_color_bg(color):
    """Resolve a color name or hex code to an ANSI background escape sequence."""
    if color in COLORS:
        # Convert foreground \033[38;2;R;G;Bm to background \033[48;2;R;G;Bm
        return COLORS[color].replace("[38;", "[48;")
    r, g, b = _parse_hex(color)
    if r is not None:
        return f"\033[48;2;{r};{g};{b}m"
    return AUGENT_GREEN.replace("[38;", "[48;")


def _parse_hex(color):
    """Parse hex color string to (r, g, b) tuple, or (None, None, None)."""
    hex_str = color.lstrip("#")
    if len(hex_str) == 6:
        try:
            return (
                int(hex_str[0:2], 16),
                int(hex_str[2:4], 16),
                int(hex_str[4:6], 16),
            )
        except ValueError:
            pass
    return (None, None, None)


def print_banner(text="AUGENT", color="green", file=sys.stderr):
    """Print the banner to a file (default: stderr)."""
    print(render_banner(text, color), file=file)
