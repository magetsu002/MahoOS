# Maho Lock SDDM visual QA

**Source visual truth**

- User-selected preview: `/tmp/codex-clipboard-3c68f42f-ae2d-453d-8a5f-1ab26b280e2f.png`
- Normalized copy: `/tmp/maho-sddm-visual.hiyOce/reference-preview.png`
- Source pixels: 2560 × 1600 at 1× capture density.

**Implementation evidence**

- Native SDDM Qt 6 test-mode render: `/tmp/maho-sddm-visual.hiyOce/final-compat-only.png`
- Final side-by-side comparison: `/tmp/maho-sddm-visual.hiyOce/comparison-final.png`
- Focused vector-eye render: `/tmp/maho-sddm-icon-eye.png`
- Implementation pixels: 2560 × 1600 at 1× capture density.
- Viewport: the machine's native 2560 × 1600 display composition.
- State: default pre-authentication greeter with the selected wallpaper, selected avatar, default user, selected Hyprland session, and password input focused.
- Density normalization: none. Source and implementation are equal-size physical-pixel captures.

**Findings**

- No actionable P0, P1, or P2 fidelity issue remains in the source implementation.
- Fonts and typography: both paths use the bundled Nunito variable font. Clock, date, greeting, input, action, and status hierarchy now occupy the same physical scale as the reference. The actual greeter intentionally says “Welcome to MahoOS”, “Log in”, and “Press Enter to log in” because it is a login surface rather than an already-authenticated lock preview.
- Spacing and layout rhythm: the centered 1600 × 1000 composition now scales to 1.6 on this 2560 × 1600 SDDM screen. Clock, greeting, avatar, password shell, primary action, and bottom controls align with the reference proportions. The prior 1.18 cap no longer shrinks the real greeter.
- Colors and visual tokens: the translucent blue surfaces, white borders, foreground hierarchy, and wallpaper treatment remain consistent with the reference.
- Image quality and asset fidelity: the selected wallpaper is staged without recompression. The selected avatar is center-cropped once to a 1024 × 1024 alpha-masked PNG and renders sharply without a greeter-time shader. Controls use staged SVG assets with oversampled decoding instead of hand-painted canvas paths.
- Copy and content: authentication-specific copy and the session/restart actions are intentional SDDM differences. The preview-only Wallpaper action is not exposed before authentication because it would imply unsafe user-profile mutation from the greeter. The center control is instead a functional session selector. Wi-Fi and battery indicators remain owned by the authenticated lock surface; the SDDM greeter exposes only the keyboard layout it can safely read and change.
- Interaction evidence: the native Qt test covers default, hover, pressed/click, and disabled states for the shared bottom action component. The session badge now invokes session selection rather than remaining static. Keyboard layout and password visibility controls have real pointer targets and animated feedback.
- Capture note: the large white dot over the eye slot in the VNC full-screen render is the virtual display pointer. The focused 64 × 64 native render shows the underlying eye SVG is sharp and correctly shaped.

**Comparison history**

1. Baseline evidence: `/tmp/maho-sddm-visual.hiyOce/comparison-before.png`.
   - P1: the real greeter was materially smaller because `uiScale` stopped at 1.18 while the preview was physically rendered at 1.6.
   - P2: SDDM icons used low-density Canvas paths and the center session badge had no pointer action or feedback.
   - P2: the selected avatar depended on a renderer-specific shader mask and disappeared in the native software-rendered test host.
2. First revision evidence: `/tmp/maho-sddm-visual.hiyOce/revised-sddm-vnc.png`.
   - Removed the 1.18 scale ceiling, introduced SVG icons, and added shared hover/press behavior and a live session selector.
   - The overall geometry matched, but the avatar still fell back to the user initial; QA remained blocked.
3. Final revision evidence: `/tmp/maho-sddm-visual.hiyOce/comparison-final.png`.
   - Replaced greeter-time avatar masking with a managed, high-resolution circular PNG generated during theme staging.
   - Added explicit runtime dependencies and regression coverage for scale, staging, vector assets, interaction, and packaging.
   - Post-fix comparison shows no actionable P0/P1/P2 differences after accounting for deliberate secure-greeter semantics.

**Focused region comparison**

- The center authentication region was inspected at native pixels in the final full render: avatar edges, input border, lock glyph, password-visibility slot, button border, type weight, and vertical spacing are legible and consistent.
- The eye icon was also rendered independently through the same Qt image component to distinguish the SVG from the VNC pointer overlay.

**Implementation Checklist**

- [x] Match SDDM physical scale to the accepted preview composition.
- [x] Replace low-density icon drawing with staged vector assets.
- [x] Make bottom actions and session selection visibly interactive.
- [x] Preserve the selected avatar through a renderer-independent high-resolution circular asset.
- [x] Cover source, packaging, staging, and native Qt interaction contracts.
- [x] Render and compare the actual SDDM Qt 6 theme at 2560 × 1600.
- [ ] Install the verified source on the live system only after user approval.
- [ ] Complete the final acceptance gate with a user-approved reboot and direct visual inspection of the real greeter.

**Follow-up Polish**

- P3: after the controlled reboot, judge font antialiasing and pointer theme under the actual SDDM Xorg/GPU path; those host-level details cannot be proven by the VNC renderer.

final result: passed
