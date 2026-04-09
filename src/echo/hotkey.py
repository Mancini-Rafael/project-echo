"""Global hotkey chord parsing and detection.

`parse_chord` turns a list of human-readable key names from the config file
into a tuple of "slots", where each slot is a frozenset of pynput keys that
satisfy that slot (modifier names expand to left+right variants).

`ChordDetector` is a pure state machine driven by `on_press`/`on_release`
calls. It fires a single callback on the leading edge of "all slots
satisfied" and re-arms only when at least one target key is released.
"""
from __future__ import annotations

from typing import Callable

from pynput.keyboard import Key, KeyCode

from echo.config import ConfigError


_MODIFIERS: dict[str, list[Key]] = {
    "ctrl": [Key.ctrl_l, Key.ctrl_r],
    "alt": [Key.alt_l, Key.alt_r],
    "cmd": [Key.cmd_l, Key.cmd_r],
    "shift": [Key.shift_l, Key.shift_r],
}

_NAMED: dict[str, Key] = {
    "space": Key.space,
    "enter": Key.enter,
    "tab": Key.tab,
    "esc": Key.esc,
    "escape": Key.esc,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}


Slot = frozenset
ChordSlots = tuple[Slot, ...]


def parse_chord(names: list[str]) -> ChordSlots:
    """Parse a list of key names into a tuple of slots.

    Each slot is a frozenset of pynput Key/KeyCode values that satisfy
    that slot. Modifier slots include both left and right variants.
    """
    if not names:
        raise ConfigError("Hotkey chord cannot be empty")

    slots: list[Slot] = []
    for raw in names:
        name = raw.strip().lower()
        if name in _MODIFIERS:
            slots.append(frozenset(_MODIFIERS[name]))
        elif name in _NAMED:
            slots.append(frozenset({_NAMED[name]}))
        elif len(name) == 1 and name.isprintable():
            slots.append(frozenset({KeyCode.from_char(name)}))
        else:
            raise ConfigError(f"Unknown hotkey key: {raw!r}")
    return tuple(slots)


class ChordDetector:
    """Tracks pressed keys and fires `on_pressed` when the chord is complete.

    Fires exactly once on the transition into "all slots satisfied". Does
    not fire again until at least one target key is released and the chord
    is re-formed.
    """

    def __init__(
        self,
        *,
        slots: ChordSlots,
        on_pressed: Callable[[], None],
    ) -> None:
        self._slots = slots
        self._target_keys: frozenset = frozenset().union(*slots)
        self._on_pressed = on_pressed
        self._pressed: set = set()
        self._armed = True

    def _all_slots_satisfied(self) -> bool:
        return all(bool(slot & self._pressed) for slot in self._slots)

    def on_press(self, key) -> None:
        self._pressed.add(key)
        if self._armed and self._all_slots_satisfied():
            self._armed = False
            self._on_pressed()

    def on_release(self, key) -> None:
        self._pressed.discard(key)
        if key in self._target_keys and not self._all_slots_satisfied():
            self._armed = True
