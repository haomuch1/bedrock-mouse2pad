<p align="center">
  <img src="assets/banner.svg" alt="bedrock-mouse2pad" width="820">
</p>

# bedrock-mouse2pad

**Minecraft: Bedrock Edition (Windows GDK build) killed your mouse in-game? This gets you playing again.**

If your keyboard works, your controller works, but **mouse camera-look and left/right/middle clicks do nothing inside Minecraft** — while the cursor still moves fine on your desktop and in every other game — this tool is for you. It turns your mouse into a virtual Xbox controller that Minecraft *does* listen to.

> ⚠️ This is a **workaround for a Mojang bug**, not an official fix. It's a bridge until Mojang patches the GDK mouse input path. See [Honest caveats](#honest-caveats).

---

## The problem

Starting with the **GDK builds of Minecraft Bedrock (1.21.120+)** on Windows 10/11, some players lose all mouse input *inside the game*:

- ❌ Moving the mouse doesn't move the camera.
- ❌ Left / right / middle click do nothing (mining, placing, menus).
- ✅ The Windows cursor still moves normally.
- ✅ Keyboard works. ✅ A game controller works perfectly.
- ✅ The mouse works flawlessly in **every other game and app**.

And it **survives everything you'd normally try**:

- Reinstalling Minecraft, resetting `options.txt`, Windows "Repair" / "Reset" on the app
- Toggling **Raw Input** in the game's settings
- A **different / second mouse** (so it's not your hardware)
- **Single monitor** vs multi-monitor
- Closing **Logitech G Hub**, KVM software, or other input utilities
- **Cursor-confinement** tools (they fix *cursor escaping*, not *dead input*)

That's because the bug is in Minecraft's **client-side mouse input path** on GDK — nothing on your PC is at fault.

## Why this works

Minecraft's **controller** input path is completely healthy — only the mouse path is broken. So instead of fighting the mouse path, this tool:

1. Installs a **virtual Xbox 360 controller** using the signed **ViGEmBus** driver.
2. Reads your **real mouse at the device level** (Raw Input) and **translates** it into that virtual controller — mouse movement becomes the right stick, clicks become the triggers, etc.
3. Does this **only while Minecraft is the focused window**, and only while Minecraft is running.

Minecraft sees "a controller," and responds normally. You play with your mouse.

## What it does / doesn't touch

- ✅ Your mouse is only **read**, never modified or blocked — it stays 100% normal everywhere else.
- ✅ The virtual controller **exists only while `Minecraft.Windows.exe` is running**, and is unplugged the instant it closes. No virtual pad lingers while you play other games.
- ✅ Translation is **paused whenever Minecraft isn't focused** — Alt-Tab and your mouse is a normal mouse again.
- ✅ Your **real controller keeps working** and coexists (a family member can still grab the Xbox pad).
- ✅ No kernel hooks on your mouse, no filter drivers, no changes to Minecraft's files.

---

## Requirements

- Windows 10 or 11 (x64)
- [Python 3](https://www.python.org/downloads/) (tick **"Add python.exe to PATH"** during install)
- Admin rights **once**, only for the first-time ViGEmBus driver install (then a reboot)

## Install

**Easiest (no PowerShell needed):** on this page click the green **`< > Code` ▸ Download ZIP**, extract it, then **double-click `install.bat`**. Approve the admin / "ViGEmBus Setup" prompts if they appear.

Prefer PowerShell? From the extracted folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The installer will:
1. Find Python.
2. `pip install vgamepad` — this **bundles the ViGEmBus driver installer**. Accept the UAC / "ViGEmBus Setup" prompt if it appears.
3. Copy files to `%LOCALAPPDATA%\Mouse2PadBedrock`.
4. Register a hidden **`MouseToPad`** scheduled task that runs at logon.
5. Start it and verify.

> 🔁 **First install needs a reboot.** ViGEmBus can't connect a virtual pad until Windows restarts once after the driver is installed. Reboot, then just launch Minecraft — the helper is already running in the background.

## Uninstall

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
```

Stops the helper (unplugging the pad), removes the task and files, and **asks** before removing the shared ViGEmBus driver (other tools like DS4Windows use it, so it's kept by default).

---

## Controls & mapping

mouse2pad has **two modes** because Bedrock uses the sticks differently in the world vs. in menus. It switches automatically (and you can force it with a key — see [Menus & inventory](#menus--inventory)).

**Gameplay mode** (in the world):

| Your input | Virtual controller | In Minecraft |
|---|---|---|
| Move mouse | Right stick | Look / aim camera |
| Left click | Right trigger | Attack / mine |
| Right click | Left trigger | Use / place / eat |
| Middle click | Y button | *(rebindable — Bedrock has no true "pick block" on a pad)* |
| Scroll up / down | LB / RB | Cycle hotbar |

**Menu mode** (inventory / chest / crafting / pause & settings screens):

| Your input | Virtual controller | In Minecraft |
|---|---|---|
| Move mouse | Left stick | Move the on-screen pointer |
| Left click | A button | Select / pick up / place stack |
| Right click | X button | *(split stack / secondary, per screen)* |
| Scroll up / down | Right stick Y | Scroll lists / pages |

**Always active:**

| Your input | Effect |
|---|---|
| **Ctrl + Alt + M** | **Pause / resume** translation |
| **Caps Lock** *(default, configurable)* | **Manually toggle** menu ⇄ gameplay mode |

## Configuration

Edit `%LOCALAPPDATA%\Mouse2PadBedrock\mouse2pad_config.txt` — changes apply **live within ~1 second**, no restart:

| Setting | Meaning |
|---|---|
| `sensitivity` | Camera speed. Higher = faster. `0.010` slow … `0.040` fast (default `0.020`). |
| `sensitivity_x` / `sensitivity_y` | Per-axis trim on top of `sensitivity`. `1.0` = no change; e.g. `sensitivity_y=0.8` slows vertical aim. |
| `expo` | Power-curve response. `0` = linear; higher = gentler for small movements (finer aim near center) with the same top speed. Try `0.3`–`0.8`. |
| `invert_y` | `0` = mouse up looks up (normal); `1` = inverted (camera only). |
| `wheel_pulse_ms` | How long each scroll notch holds its mapped output (hotbar in gameplay, list-scroll in menus). |
| `menu_sensitivity` | Menu **pointer** speed (left stick), tuned separately from the camera. Range ~`0.04` slow … `0.15` fast (default `0.08`). |
| `menu_expo` | Power curve for the menu pointer. `0` = linear; higher keeps slow moves precise while big sweeps cross the whole grid (default `0.5`). |
| `pin_cursor_in_menus` | `1` = in menu mode, snap the stray Windows cursor to the window center each frame so you see a single pointer; `0` = leave it. |
| `auto_menu_mode` | `1` = auto-switch menu/gameplay by watching cursor visibility; `0` = manual toggle only. |
| `menu_toggle_key` | Manual mode-toggle key. `capslock` (default), `scrolllock`, `pause`, `insert`, `home`, `end`, `apps`, `f13`–`f24`, or mouse side buttons `x1` / `x2`. |

**Tune the camera:** open the config, change `sensitivity`, save, and feel the difference in-game a second later.

---

## Menus & inventory

Bedrock's inventory, chest, crafting, and settings screens don't use the camera stick — they move an **on-screen pointer with the left stick** and select with **A**. So mouse2pad has a dedicated **menu mode**:

- **Move mouse** → moves the pointer (speed = `menu_sensitivity`, shaped by `menu_expo`).
- **Left click** → **A** (select / pick up / place a stack).
- **Right click** → **X** (split stack / secondary action, depending on the screen).
- **Scroll wheel** → nudges the **right stick Y** to scroll lists and pages.

**One pointer, not two.** Because the GDK input path is broken, Windows leaves its own cursor roaming freely over the game while Bedrock draws a *second* pointer from the controller — two arrows, desynced, which feels awful. So in menu mode mouse2pad **pins the Windows cursor to the center of the game window** every frame (`pin_cursor_in_menus=1`). Your motion still comes from raw mouse deltas, so this is purely visual: it parks the stray arrow out of the way and you track the single in-game pointer. Pinning is active **only** while menu mode is on and Minecraft is focused — it releases instantly in gameplay, on Alt-Tab, or when paused with Ctrl+Alt+M. *(The tool doesn't fully hide the OS cursor: doing that reliably needs a global, process-wide cursor swap that's risky if the helper ever crashes, so it's deliberately skipped.)*

**If the pointer scale feels off:** raise `menu_sensitivity` (default `0.08`, range ~`0.04`–`0.15`) so a normal hand motion crosses the grid. Add `menu_expo` (default `0.5`) if fast sweeps are fine but fine placement is twitchy — it softens small movements while keeping big ones fast. Both apply live on save.

**Switching modes — two ways, and they work together:**

1. **Automatic** (`auto_menu_mode=1`, default): mouse2pad watches whether Windows is showing the mouse cursor. Bedrock **hides** the cursor during gameplay and **shows** it on menu screens, so opening your inventory flips it to menu mode and closing it flips back — no key needed.
2. **Manual toggle** (default **Caps Lock**): press it to force a mode. **Manual always wins** — the instant you press the key, auto-detection steps aside and you're in manual control (press again to flip back).

> **If auto-switching misbehaves on your machine:** the GDK build's input path is broken, so it may not manage the cursor like a healthy game. If menu mode triggers at the wrong times (or never), set **`auto_menu_mode=0`** and just use the toggle key — everything degrades gracefully. Prefer a key that doesn't collide with anything? Set `menu_toggle_key` to a mouse side button (`x1`/`x2`) or an F13–F24 key. Every mode switch is written to `mouse2pad.log` so you can see what it's doing.

---

## Getting the best camera feel

The camera is **velocity-based** (mouse movement = how fast the stick is pushed), not native 1:1 aim — see [Honest caveats](#honest-caveats). These knobs get it as close as possible:

- **Start with `sensitivity`.** This is your master speed. Nudge it until a normal wrist motion turns you about the right amount, then stop.
- **Add a little `expo`** (try `0.4`) if fast turns feel fine but tiny corrections feel twitchy. Expo keeps your top speed but softens small movements, so lining up a block or a mob is easier.
- **Trim one axis** with `sensitivity_x` / `sensitivity_y` if vertical feels faster/slower than horizontal (common). Lowering `sensitivity_y` to `0.8`–`0.9` often feels more natural.
- **Fast flicks carry over** automatically: a single big swipe that would overshoot a full stick push is spread across the next frame instead of hitting a wall, so quick 180s feel smooth rather than clipped.
- **`invert_y`** flips vertical look if you fly/aim inverted. (It only affects the camera, never the menu pointer.)

All of these are live — save the config and feel the change in about a second.

---

## Troubleshooting

**The pad doesn't work right after installing.**
ViGEmBus needs **one reboot** after its first install before any virtual pad can connect. Restart Windows.

**"Python was not found."**
Install [Python 3](https://www.python.org/downloads/) and check **"Add python.exe to PATH"**, then re-run `install.ps1`.

**Nothing happens in-game after reboot.**
- Confirm the helper is running:
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*mouse2pad.py*' } | Select-Object ProcessId, CreationDate
  ```
- Confirm the task exists: `Get-ScheduledTask -TaskName MouseToPad`
- Start it manually: `Start-ScheduledTask -TaskName MouseToPad`
- Check `%LOCALAPPDATA%\Mouse2PadBedrock\mouse2pad.log` for errors.

**Camera moves when I'm not touching the mouse.**
It shouldn't (the stick decays to center on stop). Lower `sensitivity` and make sure only one instance is running.

**It's translating when I don't want it to.**
Press **Ctrl + Alt + M** to pause, or Alt-Tab out of Minecraft (translation only runs while Minecraft is focused).

---

## Is it the GameInput Service? (a root-cause lead worth checking)

GDK builds of Bedrock read mouse input through Microsoft's **GameInput** layer (part of Gaming Services), not the normal Windows message path. A broken or stopped GameInput layer would kill mouse input *in Bedrock specifically* while keyboard, controller, and the desktop cursor all keep working — which matches this bug's signature. On some machines this may be the actual cause, so it's worth a two-minute check **before** relying on this workaround:

```powershell
# Service state + startup type (Manual/on-demand is the correct default):
Get-Service GameInputSvc, GameInputRedistService | Format-Table Name, Status, StartType
# Gaming Services app health (want Status = Ok):
Get-AppxPackage Microsoft.GamingServices | Select-Object Name, Version, Status
# Any recent GameInput/GamingServices errors?
Get-WinEvent -FilterHashtable @{ LogName='System','Application'; Level=1,2,3;
  StartTime=(Get-Date).AddDays(-7) } -ErrorAction SilentlyContinue |
  Where-Object { $_.Message -match 'GameInput|GamingServices' } |
  Select-Object TimeCreated, ProviderName, Id, LevelDisplayName
```

- **`GameInputSvc` stopped or missing** → start it (`Start-Service GameInputSvc`, admin) and retest; if missing, install the current GameInput redistributable / Gaming Services.
- **Running but the mouse is still dead in-game** (as on the author's machine — service healthy, no error events) → this appears to be a **bug inside GameInput's mouse handling or Bedrock's use of it**, which a Gaming Services *reinstall* won't fix (that reinstalls the Store app, not the `GameInput.dll` / `GameInputSvc.exe` redist binaries serviced by Windows Update). In that case it's a genuine game/OS bug — use this workaround and, ideally, [report it to Mojang](https://bugs.mojang.com).

> **Tip:** to test whether your *native* mouse works, press **Ctrl + Alt + M** to pause mouse2pad first — otherwise the translator masks the result.

---

## Honest caveats

- **The camera feel is velocity-based, not native 1:1 mouse aim.** A controller stick reports *how far you've pushed it* (a turn speed), while a mouse reports *how far you moved*. This tool maps mouse movement to stick deflection, so aiming feels like a very responsive controller, **not** like raw mouse aim. It's very playable; it is not pixel-perfect FPS aiming.
- **This is a workaround, not a fix.** If your mouse cursor moves on screen but Minecraft Bedrock won't register clicks or camera movement — while keyboard and controller work fine — this tool fixes that. The root cause is a **game-side bug in the GDK builds of Minecraft Bedrock (1.21.120+)**, not anything on your PC. **Uninstall this tool once Mojang patches it.**
- **Tested on:** Windows 11 (25H2, build 26200) + Bedrock **1.26.32** (GDK). Bug still present as of this version. Other versions/configs may vary.
- **Use at your own risk.** See the [no-warranty disclaimer](#license--credits).

## Reported environments where this bug appears (and what is *not* the cause)

Players hitting this bug often have one or more of: **multiple monitors**, a **KVM switch**, or **Logitech G Hub** installed. These are **correlations, not causes** — the bug was reproduced and ruled independent of all of them (it happens on a single monitor, with no KVM, and with G Hub closed). **This tool works regardless of whether you have them.** Don't waste time uninstalling G Hub or unplugging monitors expecting a fix.

---

## License & credits

This project is licensed under the **[MIT License](LICENSE)**.

**THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.** You install and run it at your own risk.

Built on the excellent work of others (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)):

- **[ViGEmBus](https://github.com/nefarius/ViGEmBus)** — the signed virtual-gamepad kernel driver by **Nefarius Software Solutions e.U.** (BSD-3-Clause). This tool would not exist without it.
- **[vgamepad](https://github.com/yannbouteiller/vgamepad)** — Python bindings for ViGEm by **Yann Bouteiller** (MIT).

Related community work on the GDK cursor/mouse bugs:

- **[SwimMouseCursor](https://github.com/Swedeachu/SwimMouseCursor)** by Swedeachu — cursor confinement for the escaping-cursor variant.
- **[Igneous](https://github.com/Aetopia/Igneous)** by Aetopia — workarounds for various Bedrock GDK bugs.

*Not affiliated with Mojang or Microsoft. Minecraft is a trademark of Mojang Synergies AB.*
