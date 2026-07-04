#!/usr/bin/env python3
"""
mouse2pad.py - Translate raw mouse input into a virtual Xbox 360 controller so
Minecraft: Bedrock Edition (GDK builds) becomes playable with a mouse again.

WHY THIS EXISTS
---------------
On the GDK builds of Minecraft Bedrock (1.21.120+), the game's *mouse* input path
is broken client-side: camera-look and left/right/middle clicks do nothing in the
world, even though the cursor still moves in Windows and works in every other game.
The game's *controller* input path, however, works perfectly. So instead of fighting
the broken mouse path, this tool reads the mouse at the device level and feeds a
virtual Xbox 360 pad (via the ViGEmBus driver) - the game sees a controller and
responds normally.

TWO MODES (v1.1)
----------------
The right stick is great for the *camera* but useless on Bedrock's inventory/chest/
menu screens, which move a pointer with the LEFT stick and select with A. So this
tool now has two mapping modes and switches between them:

* GAMEPLAY MODE - mouse -> right stick (camera), clicks -> triggers, wheel -> hotbar.
* MENU MODE     - mouse -> left stick (drives Bedrock's on-screen pointer),
                  left click -> A (select), right click -> X, wheel -> right-stick Y
                  nudges (scroll lists).

Switching is either AUTOMATIC (we watch whether Windows is showing the mouse cursor -
Bedrock hides it during gameplay and shows it in menus) or MANUAL (a toggle key,
Caps Lock by default). See the CURSOR-DETECTION and MODE-SWITCHING notes below.

In menu mode the broken GDK input path leaves the OS cursor roaming free while the
game draws its own pointer from our left stick - two desynced pointers. So in menu
mode we also PIN the OS cursor to the window center each frame (SetCursorPos), which
parks the stray arrow so you track a single pointer (the game's). It's purely visual:
we read motion from raw deltas and SetCursorPos does not generate raw input. We do
NOT try to fully hide the OS cursor - that needs a global cursor swap (SetSystemCursor)
which is process-wide and risky, so it's deliberately skipped.

KEY DESIGN DECISIONS (the "why")
--------------------------------
* RAW INPUT DELTAS, not cursor position.
  We register for WM_INPUT (Raw Input API) and read per-event mouse *deltas*
  (lLastX/lLastY). We deliberately do NOT read the cursor's screen position:
  under this bug the cursor can hit a screen edge or wander to another monitor,
  and position-based capture would stall or jump. Deltas keep working regardless
  of where the cursor physically is.

* RATE-BASED CAMERA THAT DECAYS TO CENTER.
  A controller stick reports a *position* (an angular velocity for the camera),
  while a mouse reports *displacement*. Each frame we sum the deltas seen since the
  last frame, set the right stick proportional to that sum, then reset the sum to
  zero. When the mouse stops, the next frame sees zero delta -> the stick returns
  to center -> the camera stops. This prevents drift and stick "stick".

* CAMERA FEEL KNOBS (v1.1).
  - sensitivity_x / sensitivity_y let you trim horizontal vs vertical speed
    independently on top of the base `sensitivity`.
  - expo applies a power curve so small mouse motions map to a gentler stick
    push (finer aim near center) without lowering your top turn speed.
  - flick overflow carry: one big fast motion can demand more than a full stick
    deflection in a single frame; instead of clipping and losing it, we carry the
    overflow (capped at one extra frame) into the next frame so fast flicks keep
    turning smoothly rather than hitting a wall.

* CURSOR-VISIBILITY MODE DETECTION.
  Bedrock hides the OS cursor during gameplay and shows it on menu screens. We poll
  GetCursorInfo(); CURSOR_SHOWING => menu mode, hidden => gameplay mode. This is a
  heuristic - the GDK build's input path is broken, so it may not manage the cursor
  the way a healthy game would. If it proves unreliable, set auto_menu_mode=0 and
  use the manual toggle key; everything degrades gracefully (auto simply stops
  driving the mode and the manual key is fully in charge).

* MODE SWITCHING PRECEDENCE.
  If both auto and manual are enabled, the manual toggle WINS: the moment you press
  it, auto detection is ignored and you're in manual control (press again to flip).
  Every effective mode change is logged with its source (auto/manual) for debugging.

* FOCUS-GATING.
  Translation only happens while Minecraft is the foreground window. The moment
  focus is lost (Alt-Tab, etc.) we neutralize the pad, so your mouse behaves
  normally on the desktop and in other apps.

* PLUG/UNPLUG LIFECYCLE.
  The virtual pad is created only while Minecraft.Windows.exe is running and
  destroyed the moment it exits. No virtual controller exists on your system while
  you play other games (some games change their button prompts if they detect a
  connected pad). Your real controller is never touched and coexists fine.

INPUT MAPPING
-------------
  GAMEPLAY MODE                       MENU MODE
  Mouse move  -> Right stick (camera) Mouse move  -> Left stick (menu pointer)
  Left btn    -> Right trigger        Left btn    -> A button (select)
  Right btn   -> Left trigger         Right btn   -> X button
  Middle btn  -> Y button             Middle btn  -> (unused)
  Wheel up/dn -> LB / RB (hotbar)     Wheel up/dn -> Right stick Y +/- (scroll list)

RUNTIME
-------
  Hotkey  : Ctrl+Alt+M          pauses / resumes translation.
  Menu key: Caps Lock (default) toggles menu/gameplay mode (configurable; also
            supports mouse side buttons x1/x2). Manual toggle overrides auto.
  Tuning  : edit mouse2pad_config.txt next to this file (live-reloaded ~1x/sec).
  Shutdown: killing the process auto-disconnects the pad (ViGEmBus drops the
            virtual device when its owning process exits).

This file has no third-party imports other than `vgamepad`; everything else is
ctypes against user32/kernel32. It is intended to be run headless via pythonw.exe.
"""

import ctypes
from ctypes import wintypes
import os
import sys
import gc
import time
import math

# --------------------------------------------------------------------------- #
# Default configuration (overridable live via mouse2pad_config.txt)
# --------------------------------------------------------------------------- #
SENSITIVITY    = 0.020   # camera speed. Larger = faster. ~0.010 slow .. 0.040 fast.
SENSITIVITY_X  = 1.0     # horizontal multiplier applied on top of SENSITIVITY.
SENSITIVITY_Y  = 1.0     # vertical multiplier applied on top of SENSITIVITY.
EXPO           = 0.0     # power-curve shaping. 0 = linear; try 0.3 .. 0.8 for fine aim.
INVERT_Y       = 0       # 0 = mouse up looks up; 1 = inverted (camera only).
MAX_STICK      = 1.0     # stick clamp (do not change unless you know why).
WHEEL_PULSE_MS = 40      # how long each scroll notch "holds" its mapped output.
FRAME_MS       = 8       # update period (~125 Hz).
TARGET_EXE     = "minecraft.windows.exe"   # focus/plug gate (compared lower-case).

# Menu mode ----------------------------------------------------------------- #
MENU_SENSITIVITY    = 0.080   # menu-pointer speed (left stick). ~0.04 slow .. 0.15 fast.
MENU_EXPO           = 0.5     # menu power curve: slow moves stay precise, big moves fast.
PIN_CURSOR_IN_MENUS = 1       # 1 = recenter the OS cursor each frame while in menu mode.
AUTO_MENU_MODE      = 1       # 1 = auto-detect menu vs gameplay via cursor visibility.
MENU_TOGGLE_KEY     = "capslock"   # manual mode toggle key (see _KEY_NAME_TO_VK).
MENU_TOGGLE_VK      = 0x14         # resolved VK code for MENU_TOGGLE_KEY (Caps Lock).

# Files live next to this script, wherever it is installed (fully portable).
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "mouse2pad_config.txt")
LOG_PATH    = os.path.join(SCRIPT_DIR, "mouse2pad.log")

_MAX_LOG_BYTES = 256 * 1024

# Names accepted for menu_toggle_key -> Windows virtual-key code. Mouse side
# buttons (x1/x2) work here because GetAsyncKeyState reports them via the
# VK_XBUTTON1/2 codes - handy since they're otherwise unused by this tool.
_KEY_NAME_TO_VK = {
    "capslock": 0x14, "caps": 0x14,
    "scrolllock": 0x91, "scroll": 0x91,
    "pause": 0x13, "numlock": 0x90,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "apps": 0x5D,
    "x1": 0x05, "xbutton1": 0x05, "mouse4": 0x05,
    "x2": 0x06, "xbutton2": 0x06, "mouse5": 0x06,
    "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F, "f17": 0x80, "f18": 0x81,
    "f19": 0x82, "f20": 0x83, "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
}


def log(message):
    """Best-effort diagnostic logging (there is no console under pythonw.exe)."""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > _MAX_LOG_BYTES:
            os.remove(LOG_PATH)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# vgamepad (requires the ViGEmBus driver to be installed + one reboot)
# --------------------------------------------------------------------------- #
try:
    import vgamepad as vg
except Exception as e:  # pragma: no cover - environment dependent
    log("vgamepad import failed: %r" % (e,))
    sys.exit(1)

user32   = ctypes.WinDLL("user32",   use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --------------------------------------------------------------------------- #
# Win32 types / structures
# --------------------------------------------------------------------------- #
LRESULT   = ctypes.c_ssize_t
UINT_PTR  = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class _RM_S(ctypes.Structure):
    _fields_ = [("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT)]


class _RM_U(ctypes.Union):
    _fields_ = [("ulButtons", wintypes.ULONG), ("s", _RM_S)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT), ("u", _RM_U),
                ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG), ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUT(ctypes.Structure):
    # We only ever register for mice, so the payload is always a RAWMOUSE.
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE), ("ptScreenPos", POINT)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ULONG_PTR),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


# --------------------------------------------------------------------------- #
# Win32 constants
# --------------------------------------------------------------------------- #
WM_INPUT = 0x00FF
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100          # receive input even when not foreground
RI_L_DOWN = 0x0001; RI_L_UP = 0x0002
RI_R_DOWN = 0x0004; RI_R_UP = 0x0008
RI_M_DOWN = 0x0010; RI_M_UP = 0x0020
RI_WHEEL = 0x0400
VK_CONTROL = 0x11; VK_MENU = 0x12; VK_M = 0x4D
CURSOR_SHOWING = 0x00000001
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# --------------------------------------------------------------------------- #
# Function prototypes.
# Setting argtypes/restype is REQUIRED for correctness on 64-bit Python: handle-
# returning calls (OpenProcess, CreateToolhelp32Snapshot, CreateWindowExW, ...)
# default to a 32-bit int restype and would truncate pointer-sized handles.
# --------------------------------------------------------------------------- #
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetCursorInfo.restype = wintypes.BOOL
user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetClientRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.SetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.RegisterClassW.restype = wintypes.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
user32.SetTimer.restype = UINT_PTR
user32.SetTimer.argtypes = [wintypes.HWND, UINT_PTR, wintypes.UINT, wintypes.LPVOID]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]

kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

# --------------------------------------------------------------------------- #
# Mutable runtime state (single-threaded: everything runs on the message loop)
# --------------------------------------------------------------------------- #
acc_dx = 0            # summed mouse X delta since last frame
acc_dy = 0            # summed mouse Y delta since last frame
carry_x = 0.0         # flick overflow carried into next frame (X)
carry_y = 0.0         # flick overflow carried into next frame (Y)
lmb = rmb = mmb = False
wheel_up_ms = 0.0     # remaining "hold" time from a scroll-up notch
wheel_down_ms = 0.0   # remaining "hold" time from a scroll-down notch

paused = False        # toggled by Ctrl+Alt+M
plugged = False       # is the virtual pad currently connected?
gamepad = None        # the vgamepad.VX360Gamepad instance (or None)
prev_hotkey = False   # edge detection for the pause hotkey
prev_toggle = False   # edge detection for the menu-mode toggle key
manual_menu = False   # manual-desired menu state (flipped by the toggle key)
manual_engaged = False  # has the user taken manual control this session?
menu_mode = False     # current EFFECTIVE mode (True = menu, False = gameplay)
tick = 0


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config():
    """Reload tunables from mouse2pad_config.txt. Missing/garbage lines are ignored."""
    global SENSITIVITY, SENSITIVITY_X, SENSITIVITY_Y, EXPO, INVERT_Y, WHEEL_PULSE_MS
    global MENU_SENSITIVITY, MENU_EXPO, PIN_CURSOR_IN_MENUS
    global AUTO_MENU_MODE, MENU_TOGGLE_KEY, MENU_TOGGLE_VK
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = [x.strip() for x in line.split("=", 1)]
                if key == "sensitivity":
                    SENSITIVITY = float(val)
                elif key == "sensitivity_x":
                    SENSITIVITY_X = float(val)
                elif key == "sensitivity_y":
                    SENSITIVITY_Y = float(val)
                elif key == "expo":
                    EXPO = float(val)
                elif key == "invert_y":
                    INVERT_Y = int(val)
                elif key == "wheel_pulse_ms":
                    WHEEL_PULSE_MS = float(val)
                elif key == "menu_sensitivity":
                    MENU_SENSITIVITY = float(val)
                elif key == "menu_expo":
                    MENU_EXPO = float(val)
                elif key == "pin_cursor_in_menus":
                    PIN_CURSOR_IN_MENUS = int(val)
                elif key == "auto_menu_mode":
                    AUTO_MENU_MODE = int(val)
                elif key == "menu_toggle_key":
                    name = val.strip().lower()
                    vk = _KEY_NAME_TO_VK.get(name)
                    if vk is None:
                        log("unknown menu_toggle_key %r; keeping %s" % (val, MENU_TOGGLE_KEY))
                    elif name != MENU_TOGGLE_KEY:
                        MENU_TOGGLE_KEY = name
                        MENU_TOGGLE_VK = vk
                        log("menu_toggle_key set to %s" % name)
    except FileNotFoundError:
        pass
    except Exception as e:
        log("config parse error: %r" % (e,))


# --------------------------------------------------------------------------- #
# Process / focus / cursor helpers
# --------------------------------------------------------------------------- #
def foreground_is_target():
    """True if the focused window belongs to TARGET_EXE."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return False
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return False
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower() == TARGET_EXE
    finally:
        kernel32.CloseHandle(h)
    return False


def cursor_showing():
    """True if Windows is currently displaying the mouse cursor.

    Bedrock hides the cursor during gameplay and shows it on menu screens, so this
    is our automatic menu/gameplay signal. Defaults to False (gameplay) if the call
    fails - gameplay is the safer fallback and matches the common state.
    """
    ci = CURSORINFO()
    ci.cbSize = ctypes.sizeof(CURSORINFO)
    if user32.GetCursorInfo(ctypes.byref(ci)):
        return bool(ci.flags & CURSOR_SHOWING)
    return False


def pin_cursor_to_focused_center():
    """Recenter the physical cursor on the focused window's client area.

    Menu mode only. The GDK build leaves the OS cursor roaming free (following the
    hand) while the game's own pointer follows our left stick - two desynced
    pointers. We drive input from raw deltas, and SetCursorPos does NOT generate
    raw input, so snapping the OS cursor back to center every frame is purely
    visual: it parks the stray arrow out of the way and never feeds back into our
    motion. Callers must only invoke this while menu mode is active and Minecraft
    is focused; simply not calling it (gameplay / focus loss / pause) releases the
    cursor instantly, with no state to unwind.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return
    rc = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return
    pt = POINT()
    pt.x = (rc.right - rc.left) // 2
    pt.y = (rc.bottom - rc.top) // 2
    if user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        user32.SetCursorPos(pt.x, pt.y)


def target_is_running():
    """True if TARGET_EXE has a live process (used to gate plug/unplug)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return False
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            return False
        while True:
            if pe.szExeFile.lower() == TARGET_EXE:
                return True
            if not kernel32.Process32NextW(snap, ctypes.byref(pe)):
                return False
    finally:
        kernel32.CloseHandle(snap)


# --------------------------------------------------------------------------- #
# Virtual pad lifecycle
# --------------------------------------------------------------------------- #
def plug():
    """Connect the virtual pad. Safe to call when ViGEmBus isn't ready yet."""
    global gamepad, plugged
    if plugged:
        return
    try:
        gamepad = vg.VX360Gamepad()
        plugged = True
        log("virtual pad connected")
    except Exception as e:
        # Most common cause: ViGEmBus installed but system not yet rebooted.
        gamepad = None
        plugged = False
        log("plug failed (ViGEmBus not ready?): %r" % (e,))


def neutralize():
    """Zero all virtual inputs without unplugging (used on focus loss / pause)."""
    if plugged and gamepad is not None:
        try:
            gamepad.reset()
            gamepad.update()
        except Exception as e:
            log("neutralize error: %r" % (e,))


def unplug():
    """Disconnect the virtual pad entirely (Minecraft exited / shutdown)."""
    global gamepad, plugged
    if not plugged:
        return
    try:
        gamepad.reset()
        gamepad.update()
    except Exception:
        pass
    gamepad = None          # destroying the object disconnects the ViGEm target
    plugged = False
    gc.collect()
    log("virtual pad disconnected")


def clampf(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def apply_expo(v, expo):
    """Power-curve response shaping within the normalized [-1, 1] range.

    expo == 0 -> linear. Larger expo -> a gentler push for small motions (finer
    aim near center) while keeping the same top speed at full deflection. Values
    already beyond full deflection (fast flicks) pass through unchanged so the
    overflow-carry logic can distribute them across frames.
    """
    if expo <= 0.0:
        return v
    a = abs(v)
    if a >= 1.0:
        return v
    return math.copysign(a ** (1.0 + expo), v)


# --------------------------------------------------------------------------- #
# Raw input handler (WM_INPUT): accumulate deltas, track buttons + wheel
# --------------------------------------------------------------------------- #
def on_raw(h_raw_input):
    global acc_dx, acc_dy, lmb, rmb, mmb, wheel_up_ms, wheel_down_ms
    size = wintypes.UINT(0)
    # First call sizes the buffer; second call fills it.
    user32.GetRawInputData(h_raw_input, RID_INPUT, None, ctypes.byref(size),
                           ctypes.sizeof(RAWINPUTHEADER))
    if size.value == 0:
        return
    buf = (ctypes.c_byte * size.value)()
    got = user32.GetRawInputData(h_raw_input, RID_INPUT, buf, ctypes.byref(size),
                                 ctypes.sizeof(RAWINPUTHEADER))
    if got != size.value:
        return
    ri = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
    if ri.header.dwType != 0:   # 0 == RIM_TYPEMOUSE
        return
    m = ri.mouse
    acc_dx += m.lLastX
    acc_dy += m.lLastY
    flags = m.u.s.usButtonFlags
    if flags & RI_L_DOWN: lmb = True
    if flags & RI_L_UP:   lmb = False
    if flags & RI_R_DOWN: rmb = True
    if flags & RI_R_UP:   rmb = False
    if flags & RI_M_DOWN: mmb = True
    if flags & RI_M_UP:   mmb = False
    if flags & RI_WHEEL:
        delta = ctypes.c_short(m.u.s.usButtonData).value   # signed wheel delta
        if delta > 0:
            wheel_up_ms = WHEEL_PULSE_MS
        elif delta < 0:
            wheel_down_ms = WHEEL_PULSE_MS


# --------------------------------------------------------------------------- #
# Per-frame update (WM_TIMER): manage lifecycle + push state to the pad
# --------------------------------------------------------------------------- #
def on_frame():
    global acc_dx, acc_dy, carry_x, carry_y, paused, prev_hotkey, prev_toggle
    global manual_menu, manual_engaged, menu_mode, tick, wheel_up_ms, wheel_down_ms
    tick += 1

    # Live config reload ~1x/sec so tuning applies without a restart.
    if tick % max(1, int(1000 / FRAME_MS)) == 0:
        load_config()

    # Ctrl+Alt+M toggles pause (edge-triggered so one press = one toggle).
    hotkey = ((user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) and
              (user32.GetAsyncKeyState(VK_MENU) & 0x8000) and
              (user32.GetAsyncKeyState(VK_M) & 0x8000))
    if hotkey and not prev_hotkey:
        paused = not paused
        log("paused" if paused else "resumed")
    prev_hotkey = bool(hotkey)

    # Manual menu-mode toggle key (edge-triggered). Once pressed, the user has
    # taken manual control and auto detection is ignored (manual overrides auto).
    toggle = bool(user32.GetAsyncKeyState(MENU_TOGGLE_VK) & 0x8000)
    if toggle and not prev_toggle:
        manual_menu = not manual_menu
        manual_engaged = True
        log("manual toggle -> %s" % ("menu" if manual_menu else "gameplay"))
    prev_toggle = toggle

    # Plug/unplug based on whether Minecraft is running (~2x/sec is plenty).
    if tick % max(1, int(500 / FRAME_MS)) == 0:
        running = target_is_running()
        if running and not plugged:
            plug()
        elif not running and plugged:
            unplug()

    if not plugged:
        acc_dx = 0
        acc_dy = 0
        carry_x = 0.0
        carry_y = 0.0
        return

    # Only translate while Minecraft is focused and we aren't paused.
    if paused or not foreground_is_target():
        acc_dx = 0
        acc_dy = 0
        carry_x = 0.0
        carry_y = 0.0
        wheel_up_ms = 0
        wheel_down_ms = 0
        neutralize()
        return

    # --- Decide menu vs gameplay. Manual overrides auto once engaged. ---
    if AUTO_MENU_MODE and not manual_engaged:
        desired_menu = cursor_showing()
        source = "auto"
    else:
        desired_menu = manual_menu
        source = "manual"
    if desired_menu != menu_mode:
        log("mode: %s -> %s (%s)" % ("menu" if menu_mode else "gameplay",
                                     "menu" if desired_menu else "gameplay", source))
        menu_mode = desired_menu
        carry_x = 0.0   # don't let a leftover flick bleed across a mode switch
        carry_y = 0.0

    try:
        if menu_mode:
            # ---- MENU MODE: mouse -> left stick (pointer), clicks -> A / X ----
            # menu_expo keeps slow, precise moves controllable while big sweeps
            # still cross the whole grid.
            mx = apply_expo(acc_dx * MENU_SENSITIVITY, MENU_EXPO)
            my = apply_expo(acc_dy * MENU_SENSITIVITY, MENU_EXPO)
            acc_dx = 0
            acc_dy = 0
            msx = clampf(mx, -MAX_STICK, MAX_STICK)
            msy = clampf(-my, -MAX_STICK, MAX_STICK)

            ry = 0.0   # scroll wheel nudges the right stick Y to scroll lists
            if wheel_up_ms > 0:
                ry = 1.0
                wheel_up_ms -= FRAME_MS
            elif wheel_down_ms > 0:
                ry = -1.0
                wheel_down_ms -= FRAME_MS

            gamepad.left_joystick_float(x_value_float=float(msx), y_value_float=float(msy))
            gamepad.right_joystick_float(x_value_float=0.0, y_value_float=float(ry))

            if lmb:
                gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)   # select
            else:
                gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
            if rmb:
                gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
            else:
                gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_X)

            # Release everything gameplay-only so nothing sticks across the switch.
            gamepad.right_trigger_float(value_float=0.0)
            gamepad.left_trigger_float(value_float=0.0)
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_Y)
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER)
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER)

            # Collapse the two visible pointers into one: park the stray OS cursor
            # at window center. Only reached while menu mode is active AND focused
            # AND not paused, so gameplay/focus-loss/pause release it automatically.
            if PIN_CURSOR_IN_MENUS:
                pin_cursor_to_focused_center()
        else:
            # ---- GAMEPLAY MODE: mouse -> right stick (camera) ----
            raw_x = acc_dx * SENSITIVITY * SENSITIVITY_X
            raw_y = acc_dy * SENSITIVITY * SENSITIVITY_Y
            acc_dx = 0
            acc_dy = 0
            raw_x = apply_expo(raw_x, EXPO)
            raw_y = apply_expo(raw_y, EXPO)

            # Flick overflow carry: clamp to the stick, stash the remainder (capped
            # at one extra frame) so a fast flick keeps turning next frame.
            tx = raw_x + carry_x
            sx = clampf(tx, -MAX_STICK, MAX_STICK)
            carry_x = clampf(tx - sx, -MAX_STICK, MAX_STICK)
            ty = raw_y + carry_y
            vy = clampf(ty, -MAX_STICK, MAX_STICK)
            carry_y = clampf(ty - vy, -MAX_STICK, MAX_STICK)
            sy = vy if INVERT_Y else -vy       # default: mouse up -> look up

            gamepad.right_joystick_float(x_value_float=float(sx), y_value_float=float(sy))
            gamepad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
            gamepad.right_trigger_float(value_float=1.0 if lmb else 0.0)
            gamepad.left_trigger_float(value_float=1.0 if rmb else 0.0)

            if mmb:
                gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_Y)
            else:
                gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_Y)

            if wheel_up_ms > 0:
                gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER)
                wheel_up_ms -= FRAME_MS
            else:
                gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER)
            if wheel_down_ms > 0:
                gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER)
                wheel_down_ms -= FRAME_MS
            else:
                gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER)

            # Release menu-only buttons so a click doesn't stick across the switch.
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_X)

        gamepad.update()
    except Exception as e:
        # If the pad vanished under us, drop it; the next tick will re-plug.
        log("update error, dropping pad: %r" % (e,))
        unplug()


# --------------------------------------------------------------------------- #
# Window procedure + message loop
# --------------------------------------------------------------------------- #
@WNDPROC
def wnd_proc(hwnd, msg, wparam, lparam):
    try:
        if msg == WM_INPUT:
            on_raw(lparam)
            # WM_INPUT requires DefWindowProc to be called for cleanup.
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == WM_TIMER:
            on_frame()
            return 0
        if msg == WM_DESTROY:
            unplug()
            user32.PostQuitMessage(0)
            return 0
    except Exception as e:
        log("wnd_proc error: %r" % (e,))
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    load_config()
    log("mouse2pad starting (auto_menu_mode=%d, menu_toggle_key=%s, pin_cursor_in_menus=%d)"
        % (AUTO_MENU_MODE, MENU_TOGGLE_KEY, PIN_CURSOR_IN_MENUS))

    h_inst = kernel32.GetModuleHandleW(None)
    cls = WNDCLASS()
    cls.lpfnWndProc = wnd_proc
    cls.hInstance = h_inst
    cls.lpszClassName = "Mouse2PadHiddenWnd"
    if not user32.RegisterClassW(ctypes.byref(cls)):
        log("RegisterClassW failed: %d" % ctypes.get_last_error())
        return

    # A normal window that we never show: invisible, but still receives WM_INPUT.
    hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "mouse2pad", 0,
                                  0, 0, 0, 0, None, None, h_inst, None)
    if not hwnd:
        log("CreateWindowExW failed: %d" % ctypes.get_last_error())
        return

    # Register for raw MOUSE input, INPUTSINK = deliver even when not foreground.
    rid = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)
    if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)):
        log("RegisterRawInputDevices failed: %d" % ctypes.get_last_error())
        return

    user32.SetTimer(hwnd, 1, FRAME_MS, None)

    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        unplug()
        log("mouse2pad stopped")


if __name__ == "__main__":
    main()
