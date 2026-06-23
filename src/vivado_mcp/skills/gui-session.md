# Skill: GUI Session

Use this when the user wants AI to open Vivado and keep the GUI visible while AI operates the same session.

## Normal Flow

1. Call `vivado_check_installation`.
2. Call `vivado_start_session` with `open_gui=true`.
3. Confirm the returned `gui.visible` is `true`; if it is not, report `gui.detail` instead of claiming the GUI is visible.
4. Call `vivado_focus_gui` only if the user asks to bring Vivado forward.
5. Use workflow tools or `vivado_run_tcl`.
6. Call `vivado_stop_session` when finished.

## Notes For AI

- Do not use GUI click automation.
- Treat the GUI as a visible state viewer and occasional human interaction surface.
- Refresh session state before mutating commands because the user may have changed state in the GUI.
- `open_gui=true` means the GUI was requested; `gui.visible=true` means a desktop window was actually found.
- Confirming `gui.visible` does not require bringing Vivado to the foreground.
