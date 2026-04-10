import pytest
from pynput.keyboard import Key, KeyCode

from echo.config import ConfigError
from echo.hotkey import ChordDetector, parse_chord

# ----- parse_chord -----


def test_parse_chord_modifiers() -> None:
    slots = parse_chord(["control", "option", "command"])
    # Each slot is a frozenset; modifier slots include both L and R variants.
    assert len(slots) == 3
    assert Key.ctrl_l in slots[0] and Key.ctrl_r in slots[0]
    assert Key.alt_l in slots[1] and Key.alt_r in slots[1]
    assert Key.cmd_l in slots[2] and Key.cmd_r in slots[2]


def test_parse_chord_legacy_aliases_rejected() -> None:
    """ctrl/alt/cmd are no longer accepted — only Mac-native names."""
    for legacy in ("ctrl", "alt", "cmd"):
        with pytest.raises(ConfigError, match="Unknown hotkey key"):
            parse_chord([legacy])


def test_parse_chord_named_keys() -> None:
    slots = parse_chord(["space", "f1"])
    assert Key.space in slots[0]
    assert Key.f1 in slots[1]


def test_parse_chord_letter() -> None:
    slots = parse_chord(["control", "a"])
    assert KeyCode.from_char("a") in slots[1]


def test_parse_chord_unknown_key_raises() -> None:
    with pytest.raises(ConfigError, match="Unknown hotkey key"):
        parse_chord(["control", "wat"])


def test_parse_chord_empty_raises() -> None:
    with pytest.raises(ConfigError, match="empty"):
        parse_chord([])


# ----- ChordDetector -----


def _make_detector():
    slots = parse_chord(["control", "option", "command"])
    fired = []
    detector = ChordDetector(slots=slots, on_pressed=lambda: fired.append(1))
    return detector, fired


def test_chord_fires_once_on_full_press() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    assert fired == [1]


def test_chord_does_not_fire_on_partial_press() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    assert fired == []


def test_chord_does_not_fire_again_while_held() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    # Press an extra key while still holding the chord — must NOT re-fire.
    detector.on_press(KeyCode.from_char("x"))
    assert fired == [1]


def test_chord_rearms_after_releasing_a_target_key() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    assert fired == [1]
    detector.on_release(Key.ctrl_l)
    detector.on_press(Key.ctrl_l)
    assert fired == [1, 1]


def test_chord_does_not_rearm_when_only_non_target_released() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    detector.on_press(KeyCode.from_char("x"))
    detector.on_release(KeyCode.from_char("x"))
    # All target keys still held — must remain disarmed.
    assert fired == [1]


def test_chord_left_and_right_modifiers_interchangeable() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_r)
    detector.on_press(Key.alt_r)
    detector.on_press(Key.cmd_r)
    assert fired == [1]
