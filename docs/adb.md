# Wireless Debugging model

This is development / power-user XR infrastructure on our own stock Fold.
It is not a claim that production apps should embed ADB.

## Why this exists

A normal Android app UID is heavily restricted. It cannot grant itself
`WRITE_SECURE_SETTINGS`, cannot freely drive `adbd`, and cannot act as
Android's `shell` user.

ADB's `shell` UID *can* do things that matter for XR bring-up:

- `pm grant ... WRITE_SECURE_SETTINGS`
- inspect dumpsys / logcat
- install iterative APKs
- start a privileged helper as shell (UxSpace's embedded-ADB prior art)

Wireless Debugging (`adbd` on TLS, advertised over mDNS as
`_adb-tls-connect._tcp`) lets a **device-local** ADB client connect back
to the same phone's `adbd` without USB and without root.

That is the whole point of the Fold topology:

    remote agent
        -> stable SSH to Termux
            -> Fold-local adb
                -> 127.0.0.1:<current wireless port>
                    -> adbd (shell UID)

The rotating connection port is a local device concern. Discovery belongs
beside Android. Remote agents must not chase that port across NetBird or
LAN.

## Pairing vs connection

These are different.

| | pairing | connection |
|---|---|---|
| When | once per ADB identity | every time Wireless Debugging is on |
| Port | pairing port (dialog) | connection port (rotates) |
| What it creates | durable trust between this `adbkey` and Android | a live TCP/TLS session to `adbd` |
| Human | required the first time, and if identity is lost | not required if pairing is intact |

If a process deletes Termux's ADB keys or the phone's pairing records,
the human gets dragged back into pairing-code UI. That is a bug in the
development process, not a normal step.

Bootstrap:

    PAIR ONCE
      -> PRESERVE IDENTITY
        -> ENABLE WIRELESS DEBUGGING WHEN NEEDED
          -> DISCOVER THE CURRENT ENDPOINT (on device)
            -> RECONNECT

## WRITE_SECURE_SETTINGS

After a one-time `adb shell pm grant <pkg> android.permission.WRITE_SECURE_SETTINGS`,
a deliberately privileged development app may flip
`Settings.Global.adb_wifi_enabled`.

UxSpace and `sh.colak.fold.wadb` both do this. New network trust
confirmations remain an Android security boundary ("Allow wireless
debugging on this network?"). Auto-enable is not a spare-key to skip
that dialog forever on unseen networks.

## Discovery rules

- Prefer persisted last-good endpoint, then mDNS
  (`_adb-tls-connect._tcp`), then bounded sequential fallback.
- Never recreate the high-process-count localhost scanner that got the
  Termux UID killed.
- `xrctl adb ensure` is the agent entry. It SSHes to Termux and lets
  Fold-local `adb-wifi` do local discovery.

## UxSpace embedded-ADB (prior art)

UxSpace's privileged helper:

1. Optionally enables `adb_wifi_enabled` if granted
2. Discovers `_adb-tls-connect._tcp` on device
3. Connects with the app's ADB identity
4. Starts a shell-UID helper and hands a Binder back

Useful on this development Fold. Not a product requirement for every
XR app. Keep the idea (device-local reconnect, preserved identity,
shell bootstrap) even if UxSpace is not the long-term surface.

## What `xrctl` should know

Transport today is SSH host `fold`. Tomorrow it may be a native XR
control API. Commands should stay:

    xrctl adb ensure
    xrctl adb shell ...
    xrctl deploy <apk> --package <pkg>

and not "please nmap the NetBird address for a five-digit port".
