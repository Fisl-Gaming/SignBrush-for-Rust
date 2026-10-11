"""OS-level input emulation and hotkeys (Windows).

Only documented user-mode APIs are used: SendInput (via pydirectinput) for the
mouse, GetAsyncKeyState polling for hotkeys (no global keyboard hook), GetCursorPos
for calibration. Nothing here touches the game process.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Callable, Protocol

IS_WINDOWS = sys.platform == "win32"

VK = {f"f{i}": 0x6F + i for i in range(1, 25)}
VK.update({"esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "enter": 0x0D, "space": 0x20,
           "pause": 0x13, "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E})


def set_dpi_aware() -> None:
    """Make screen coordinates physical pixels (mss, SendInput and Qt must agree)."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def cursor_pos() -> tuple[int, int]:
    if not IS_WINDOWS:
        return 0, 0

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def key_down(name: str) -> bool:
    """Physical key state, independent of any hook (works even if hooks fail)."""
    if not IS_WINDOWS:
        return False
    vk = VK.get(name.lower())
    if vk is None:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def foreground_title() -> str:
    if not IS_WINDOWS:
        return ""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def screen_size() -> tuple[int, int]:
    if not IS_WINDOWS:
        return 1920, 1080
    return ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)


# ---------------------------------------------------------------- mouse backends

class MouseBackend(Protocol):
    def move(self, x: int, y: int) -> None: ...
    def down(self) -> None: ...
    def up(self) -> None: ...
    def position(self) -> tuple[int, int]: ...


class WinMouse:
    """SendInput through pydirectinput (absolute moves, left button)."""

    def __init__(self) -> None:
        import pydirectinput
        pydirectinput.PAUSE = 0          # we do our own, interruptible, pacing
        pydirectinput.FAILSAFE = False   # our own stop key replaces the corner fail-safe
        self._pdi = pydirectinput
        self._pressed = False

    def move(self, x: int, y: int) -> None:
        self._pdi.moveTo(int(x), int(y))

    def down(self) -> None:
        self._pdi.mouseDown()
        self._pressed = True

    def up(self) -> None:
        self._pdi.mouseUp()
        self._pressed = False

    def position(self) -> tuple[int, int]:
        return cursor_pos()


class RecordingMouse:
    """Test / dry-run backend: records every event, never touches the OS."""

    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.pos = (0, 0)
        self.pressed = False

    def move(self, x: int, y: int) -> None:
        self.pos = (int(x), int(y))
        self.events.append(("move", *self.pos))

    def down(self) -> None:
        self.pressed = True
        self.events.append(("down", *self.pos))

    def up(self) -> None:
        self.pressed = False
        self.events.append(("up", *self.pos))

    def position(self) -> tuple[int, int]:
        return self.pos


# ---------------------------------------------------------------- hotkeys

class HotkeyWatcher:
    """Calls ``callbacks[key]`` when a key is pressed.

    Polls GetAsyncKeyState every ~15 ms in a background thread. No global
    keyboard hook is installed (hooks look like keyloggers to antivirus software
    and to users), and polling cannot be blocked by another program's hook, so the
    emergency stop always works. Presses are debounced: one call per press.
    """

    def __init__(self, callbacks: dict[str, Callable[[], None]], poll_interval: float = 0.015):
        self.callbacks = {k.lower(): v for k, v in callbacks.items()}
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._last_fire: dict[str, float] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def _fire(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_fire.get(key, 0.0) < 0.25:
                return
            self._last_fire[key] = now
        try:
            self.callbacks[key]()
        except Exception as e:  # never let a callback kill the watcher
            print("hotkey callback error:", e, file=sys.stderr)

    def start(self) -> "HotkeyWatcher":
        self._thread = threading.Thread(target=self._poll, name="hotkeys", daemon=True)
        self._thread.start()
        return self

    def _poll(self) -> None:
        was = {k: False for k in self.callbacks}
        while not self._stop.is_set():
            for k in self.callbacks:
                now = key_down(k)
                if now and not was[k]:
                    self._fire(k)
                was[k] = now
            self._stop.wait(self.poll_interval)

    def stop(self) -> None:
        self._stop.set()

    def __enter__(self) -> "HotkeyWatcher":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
