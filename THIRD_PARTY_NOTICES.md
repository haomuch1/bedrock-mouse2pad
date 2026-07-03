# Third-Party Notices

This project does not bundle or redistribute any third-party source code. It
depends on the following components at install/run time, each under its own
license. All are used unmodified via their official distribution channels.

## ViGEmBus (Virtual Gamepad Emulation Bus Driver)
- Author: Nefarius Software Solutions e.U.
- License: BSD-3-Clause
- Repo: https://github.com/nefarius/ViGEmBus
- Site: https://vigembusdriver.com/
- Role: the signed Windows kernel-mode driver that provides the virtual Xbox 360
  controller. Installed via the `vgamepad` package's bundled installer.

BSD-3-Clause requires that redistributions retain the copyright notice and
disclaimer. We do not redistribute ViGEmBus binaries or source; it is installed
from its official installer. This notice is provided as attribution.

## vgamepad
- Author: Yann Bouteiller
- License: MIT
- Repo: https://github.com/yannbouteiller/vgamepad
- PyPI: https://pypi.org/project/vgamepad/
- Role: Python bindings/high-level interface over the ViGEm client library.
  Installed via `pip install vgamepad`.

## Related community work (not dependencies)
- SwimMouseCursor - Swedeachu - https://github.com/Swedeachu/SwimMouseCursor
  Confines the cursor to the Minecraft window for the GDK cursor-escaping bug.
- Igneous - Aetopia - https://github.com/Aetopia/Igneous
  Workarounds for various Minecraft Bedrock GDK bugs.
