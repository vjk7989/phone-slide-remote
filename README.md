# Phone slide remote

Use the [GitHub Pages phone site](https://vjk7989.github.io/phone-slide-remote/) to send presentation keys to this Windows laptop over one persistent WebSocket. The laptop must run the Python helper; the public site alone cannot press keys. Keep this checkout on `G:` on this laptop.

## One-time setup

In PowerShell, from this folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

This downloads `cloudflared.exe` and installs the QR and WebSocket libraries inside this folder. It does not install them system-wide.

## Each presentation

1. Connect the laptop and Android phone to the internet. They may use different networks, including laptop Wi‑Fi and phone mobile data.
2. Double-click **Start Slide Remote.cmd** in this folder, or run `powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1`. Keep its window open.
3. Open the **Hosted QR page** link printed in the helper window, or use the local setup page it opens. Scan the **Hosted phone page** QR code with the phone camera. Keep both links private.
4. On the phone page, tap **Start** and wait for **Connected**. The connection remains open while the page is open and reconnects after a brief network interruption.
5. Open your PDF in Chrome or Edge, choose **Fit to page**, and click the PDF so it has keyboard focus. Test Next and Previous, then the switch buttons, while watching the laptop screen.

Both hosted links change when the helper restarts. If the control tunnel reconnects with a new address, reopen the hosted QR page and scan its new code. If a command becomes uncertain, check the laptop screen before acknowledging and pressing again. Stop disconnects the phone; Ctrl+C in the laptop window stops the helper.

## Buttons

| Button | Windows keypress |
| --- | --- |
| Next | Page Down |
| Previous | Page Up |
| Switch window | Alt+Tab |
| Next browser tab | Ctrl+Tab |
| Previous browser tab | Ctrl+Shift+Tab |
| Literal chord | Alt+Ctrl+Shift+Tab |
| Select | Enter |

The keypress goes to the currently focused laptop app. The literal four-key chord's effect depends on that app. Administrator windows and Windows secure prompts cannot be controlled by this ordinary helper.

Cloudflare Quick Tunnels are temporary and have no uptime guarantee. Keep the laptop keyboard available as a backup for the pitch.
