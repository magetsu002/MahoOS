# Theme engine

Maho OS derives one palette from an image and passes that palette to desktop
components such as Hyprland and Kitty.

Color generation and theme application are separate. A new palette is checked
before it becomes active, and the previous working theme is kept for recovery.

Matugen currently handles image color extraction. Maho OS owns the palette and
how it is applied.
