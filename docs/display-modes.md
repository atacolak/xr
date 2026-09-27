# Display modes

Observed on the Fold + VITURE Luma Ultra during UxSpace bring-up.
See `devices/fold5-luma-ultra.md` for the table.

Facts:

- The Luma enumerates as an Android **presentation-category** display
  (name `VITURE` in UxSpace logs).
- UxSpace showed a `Presentation` on that display so the phone could
  keep its own screen.
- Android advertised 1920x1080@{60,90} and 1920x1200@{60,90,120}.
- The mode actually current in those logs was 1920x1080@60.
- Whether we should request 1920x1200@120, and whether it sticks from a
  Presentation, is **experimental / not yet investigated**.

Uncertainties:

- Phone screencap defaults to a display and can miss the glasses
  Presentation (and can prefix warnings that corrupt a PNG).
- Virtual displays created by an app can also be presentation-category;
  picking one of those as "the glasses" is a known UxSpace defect class.
- DeX desktop is a different display policy than the glasses Presentation.
  HERDR-in-DeX and glasses-as-display are not the same path.

Do not document ephemeral display IDs as durable (`id=35` in one boot
is not a contract).
