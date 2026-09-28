# Rigenera dalla root del repo:
#   PATH="$HOME/.local/bin:$PATH" vhs docs/demo.tape
# Richiede vhs, ttyd, ffmpeg e un browser Chromium/Chrome.
# La demo e' offline: ispeziona.py gira in-process e legge solo resource statiche.

Output docs/demo.gif
Set FontSize 15
Set Width 960
Set Height 540
Set Theme "Catppuccin Latte"
Set TypingSpeed 35ms
Set Shell bash

Sleep 400ms
Type "uv run python client/ispeziona.py"
Enter
Sleep 10s
