# Sanae on a Galaxy Watch

The watch app (`android/wear`) is tap to talk. It has no network code and no pairing of its own:
the watch sends everything to the Sanae phone app over Wear OS's own Bluetooth/Wi-Fi link, and the
phone forwards it to the laptop. So the phone has to be nearby, paired with the laptop, and on a
build that has the watch relay.

What it does:

- **Tap her face and talk.** It stops by itself when you stop talking, or tap again to stop.
- **The reply** comes back as text with her face in the matching mood. If "Her voice" is on, it
  also plays on the watch speaker (or your earbuds).
- If she asks you something back, it **listens again** by itself.
- **Approvals** ("Send the email?") appear on the watch with ✓ / ✗ buttons. The phone's approval
  notification also reaches the watch.
- **Next up:** your next reminders, events, classes and due items. It also works with the laptop
  off, because it uses the phone's copies.
- **A tile** (Today + a Talk button) and **a complication** that opens her already listening.

## Install (once)

The phone and watch apps share one app id (`com.manaskhare.max`) and must be signed with the same
key. `build.ps1` builds both on this laptop, so they are.

1. **Update the phone app** to a build with the watch relay: Sanae → Settings → App update (after
   running `.\android\build.ps1 -NoInstall`), or plug the phone in.
2. **Turn on developer options on the watch.** Go to Settings → About watch → Software
   information, then tap "Software version" 5 times.
3. **Turn on debugging.** Go to Settings → Developer options and turn on **ADB debugging**, then
   **Wireless debugging**. The watch and the laptop must be on the same Wi-Fi.
4. **Pair the laptop with the watch.** In Wireless debugging, tap **Pair new device**, then run
   these on the laptop:
   ```
   C:\max-android\sdk\platform-tools\adb pair <ip>:<pair port> <code>
   C:\max-android\sdk\platform-tools\adb connect <ip>:<port shown on the Wireless debugging screen>
   ```
5. **Install:** run `.\android\build.ps1`. It installs the watch build on the watch, and the phone
   build too if the phone is plugged in.
6. **Set it up on the watch.**
   - Open **Sanae** and allow the microphone.
   - **Tile:** swipe left to the end → **+** → Sanae.
   - **Complication:** long-press the watch face → Customise → a slot → Sanae, "Talk to Sanae".
7. **Turn Wireless debugging off again.** It costs battery.

## When something's off

- **"Can't reach your phone"**: the watch can't see the phone app. Check that the Galaxy Wearable
  app shows the watch as connected, and that the phone app is the new build.
- **"Can't reach your laptop"**: the phone got your words but not the laptop. Check that Sanae and
  Tailscale are running.
- **No voice:** turn "Her voice" on at the bottom of the watch screen. The watch volume is the
  media volume.

Her faces come from the 3D avatar. Run `scripts/watch_faces.py` again after changing her look.
