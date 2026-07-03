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
  Mouse move        -> Right stick   (camera; decays to center on stop)
  Left mouse button -> Right trigger (attack / mine)
  Right mouse button-> Left trigger  (use / place / eat)
  Middle button     -> Y button      (Bedrock has no 1:1 "pick block" on a pad;
                                       Y is a sensible, rebindable default)
  Wheel up / down   -> LB / RB       (hotbar cycle)

RUNTIME
-------
  Hotkey  : Ctrl+Alt+M  pauses / resumes translation.
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

# --------------------------------------------------------------------------- #
# Default configuration (overridable live via mouse2pad_config.txt)
# --------------------------------------------------------------------------- #
SENSITIVITY    = 0.020   # camera speed. Larger = faster. ~0.010 slow .. 0.040 fast.
INVERT_Y       = 0       # 0 = mouse up looks up; 1 = inverted.
MAX_STICK      = 1.0     # right-stick clamp (do not change unless you know why).
WHEEL_PULSE_MS = 40      # how long each scroll notch "holds" LB/RB.
FRAME_MS       = 8       # update period (~125 Hz).
TARGET_EXE     = "minecraft.windows.exe"   # focus/plug gate (compared lower-case).

# Files live next to this script, wherever it is installed (fully portable).
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "mouse2pad_config.txt")
LOG_PATH    = os.path.join(SCRIPT_DIR, "mouse2pad.log")

_MAX_LOG_BYTES = 256 * 1024


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
lmb = rmb = mmb = False
lb_ms_left = 0.0      # remaining LB "hold" time from a scroll notch
rb_ms_left = 0.0      # remaining RB "hold" time from a scroll notch

paused = False        # toggled by Ctrl+Alt+M
plugged = False       # is the virtual pad currently connected?
gamepad = None        # the vgamepad.VX360Gamepad instance (or None)
prev_hotkey = False   # edge detection for the pause hotkey
tick = 0


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config():
    """Reload tunables from mouse2pad_config.txt. Missing/garbage lines are ignored."""
    global SENSITIVITY, INVERT_Y, WHEEL_PULSE_MS
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = [x.strip() for x in line.split("=", 1)]
                if key == "sensitivity":
                    SENSITIVITY = float(val)
                elif key == "invert_y":
                    INVERT_Y = int(val)
                elif key == "wheel_pulse_ms":
                    WHEEL_PULSE_MS = float(val)
    except FileNotFoundError:
        pass
    except Exception as e:
        log("config parse error: %r" % (e,))


# --------------------------------------------------------------------------- #
# Process / focus helpers
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


# --------------------------------------------------------------------------- #
# Raw input handler (WM_INPUT): accumulate deltas, track buttons + wheel
# --------------------------------------------------------------------------- #
def on_raw(h_raw_input):
    global acc_dx, acc_dy, lmb, rmb, mmb, lb_ms_left, rb_ms_left
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
            lb_ms_left = WHEEL_PULSE_MS
        elif delta < 0:
            rb_ms_left = WHEEL_PULSE_MS


# --------------------------------------------------------------------------- #
# Per-frame update (WM_TIMER): manage lifecycle + push state to the pad
# --------------------------------------------------------------------------- #
def on_frame():
    global acc_dx, acc_dy, paused, prev_hotkey, tick, lb_ms_left, rb_ms_left
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
        return

    # Only translate while Minecraft is focused and we aren't paused.
    if paused or not foreground_is_target():
        acc_dx = 0
        acc_dy = 0
        lb_ms_left = 0
        rb_ms_left = 0
        neutralize()
        return

    # --- Right stick from accumulated deltas, then reset (decay to center). ---
    sx = clampf(acc_dx * SENSITIVITY, -MAX_STICK, MAX_STICK)
    sy = acc_dy * SENSITIVITY
    sy = sy if INVERT_Y else -sy       # default: mouse up -> look up
    sy = clampf(sy, -MAX_STICK, MAX_STICK)
    acc_dx = 0
    acc_dy = 0

    try:
        gamepad.right_joystick_float(x_value_float=float(sx), y_value_float=float(sy))
        gamepad.right_trigger_float(value_float=1.0 if lmb else 0.0)
        gamepad.left_trigger_float(value_float=1.0 if rmb else 0.0)

        if mmb:
            gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_Y)
        else:
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_Y)

        if lb_ms_left > 0:
            gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER)
            lb_ms_left -= FRAME_MS
        else:
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER)

        if rb_ms_left > 0:
            gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER)
            rb_ms_left -= FRAME_MS
        else:
            gamepad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER)

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
    log("mouse2pad starting")

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
