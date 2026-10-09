# Phone slide remote

Use an Android browser to control a PDF open on this Windows laptop. The [phone page](https://vjk7989.github.io/phone-slide-remote/) is hosted on GitHub Pages; the laptop helper sends the keys. No phone app is needed. Keep this checkout on `G:` on this laptop.

## One-time setup

In PowerShell, from this folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

This downloads `cloudflared.exe` and the small QR library into this folder. It does not install either system-wide.

## Each presentation

1. Connect the laptop and phone to their own internet connections.
2. Double-click **Start Slide Remote.cmd** in this folder, or run `powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1`. Keep its window open.
3. On the laptop setup page (`http://127.0.0.1:8766/`), scan **Hosted phone page** with the phone camera. Keep the private pairing link to yourself. The public Pages URL alone cannot control the laptop.
4. Open the PDF in Chrome or Edge, choose **Fit to page**, then click on the PDF so it has keyboard focus. Test Next and Previous while watching the screen.
5. Test Switch window and Next browser tab. Return to the PDF before presenting.

The link and token expire when you stop the launcher. A new tunnel produces a new QR code. The phone page reports disconnection. If a command's outcome is uncertain, look at the laptop before acknowledging and trying again.

## Bluetooth backup

Set this up and test it before the pitch, while the phone is in your hands:

1. Pair Android and Windows in Bluetooth settings. On Android, enable **Bluetooth tethering**. On Windows, connect to the phone's **Bluetooth Personal Area Network**.
2. Refresh the laptop setup page. Once Windows has a Bluetooth IP address, scan **Bluetooth backup**. Test Next and Previous with the internet disabled on both devices.
3. If the page does not open, run `bluetooth-firewall.ps1` from an **elevated PowerShell**. The rule allows port 8765 only on the Bluetooth network interface and local subnet. Scan the backup QR again.

If Android's Bluetooth tethering does not let its browser reach the laptop, use the internet link and keep the laptop keyboard as the backup. The Bluetooth adapter being present alone does not prove this path works.

## Buttons

| Button | Windows keypress |
| --- | --- |
| Next | Page Down |
| Previous | Page Up |
| Switch window | Alt+Tab |
| Next browser tab | Ctrl+Tab |

The keypress goes to the currently focused laptop app. Keep the PDF focused for slide navigation. Administrator windows and Windows secure prompts cannot be controlled by this ordinary helper.

To stop, press Ctrl+C in the launcher window. Cloudflare Quick Tunnels are temporary and have no uptime guarantee, so test the real phone and backup before the pitch.
