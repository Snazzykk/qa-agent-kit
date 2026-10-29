---
name: mobile-case-runner
description: Run an agent-mode QA case against a real iOS Simulator or Android emulator — decide the platform from the case, check the device is actually bootable, drive the app one shell block per step (AXe on iOS, adb on Android), read the screen as text with `magnum qa ui`, and attach screenshots to the run report. Activate when a case is for a mobile app, when the case's layer or tags say ios/android/mobile, or when the user says "test on the simulator", "run this on Android", "мобильный кейс".
---

# Mobile case runner

You are executing a **written case** against a device, not writing a
test suite. Everything in the QA conduct still holds: one shell
command per step, no harness script, the case is the specification.
This skill is the mobile half of the instrument rule — where a web UI
step is `$PW cli`, a mobile UI step is `$AXE` on iOS (Magnum sets it
for the session) and `adb` on Android, with `xcrun simctl` to boot,
install and launch.

**Speed is text, not pictures.** Measured on a seven-step gesture case:
12 minutes and 67 model turns, spent opening screenshots to find where
to tap and starting maestro once per gesture (8.9 s to read a screen,
against AXe's 0.43 s). The wall clock is the model's turns. Read the
screen as text, aim by label, run a step's actions in one command, and
the same case is a few minutes.

Both are plain CLIs, which is what makes them right here: a command
per action, its output in the pane the operator is watching, and
nothing that has to be read back out of a model's context afterwards.

## 1. Decide the platform — never guess

In order, stop at the first that answers:

1. The case's front matter — `kind:` (the plan's layer, e.g. `ios`,
   `android`, `mobile`) or `tags:`.
2. The case body, if it names a platform in its scope.
3. The artefact under test: an `.app`/`.ipa` is iOS, an `.apk`/`.aab`
   is Android.

If the case says `mobile` and both platforms are ready, run the one
the project's plan names first and **say in the verdict which you
chose and why**. If nothing answers, that is an ambiguous case:
report it as such rather than picking. A case run on the wrong
platform is a green tick against a question nobody asked.

## 2. Check the device is really bootable

Do this before step 1 of the case. A missing device is not a failing
case — it is a blocked run, and the two must not look alike.

### iOS

```bash
xcode-select -p                                   # Xcode present?
xcrun simctl list devices available                # what can boot
xcrun simctl list devices booted                   # already up?
```

### Android

`adb` and `emulator` are usually **not on PATH** — the SDK ships them
under its own directories, and assuming the bare name is how this
fails on a fresh machine:

```bash
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"
adb version
emulator -list-avds
```

**A listed AVD is not a bootable AVD.** Measured on a real machine:
`emulator -list-avds` printed `Medium_Phone_API_36.1` and booting it
died with `Broken AVD system path` — the AVD's config pointed at
`system-images/android-36.1/google_apis_playstore/arm64-v8a/` and the
SDK had no `system-images` directory at all. Verify before you boot:

```bash
grep image.sysdir.1 "$HOME/.android/avd/<NAME>.avd/config.ini"
ls "$ANDROID_SDK_ROOT/<that path>" >/dev/null && echo bootable
```

If the image is missing, the run is **blocked**, and the verdict says
so with the one command that fixes it:

```bash
sdkmanager "system-images;android-36.1;google_apis_playstore;arm64-v8a"
```

## 3. Boot

### iOS

```bash
xcrun simctl boot "iPhone 17"      # or the UDID
open -a Simulator                  # only if a human is watching
xcrun simctl bootstatus booted -b  # wait until it is actually up
```

### Android

```bash
emulator -avd <NAME> -no-window -no-audio -no-boot-anim &
adb wait-for-device
until [ "$(adb shell getprop sys.boot_completed | tr -d '\r')" = "1" ]; do sleep 2; done
```

`-no-window` unless the operator asked to watch: it boots faster and
a headless emulator still screenshots.

Shut down at the end **only what you booted**. A simulator that was
already running belongs to somebody.

## 4. Install and drive the app

### Android — adb drives, `magnum qa ui --android` reads

The same two verbs as on iOS, over adb (`--android`, or `ANDROID_SERIAL`
set, which also picks the device when several are attached). The screen
is `uiautomator dump` cut down to the same lines — type, "text or
description", #resource-id, the centre, the size, in the device's pixels
that `input tap` takes:

```bash
adb install -r app.apk
adb shell pm clear com.example.app          # a clean state, deliberately
adb shell am start -n com.example.app/.MainActivity
adb shell am start -a android.intent.action.VIEW -d "myapp://deep/link"

magnum qa ui --android                      # Button "Log in" #login @540,1175 600x150
magnum qa tap --android --label "Log in"    # by text or content-desc
magnum qa tap --android --id login          # by resource-id (with or without the package)
adb shell input text "qa%saccount"          # %s is a space
adb shell input swipe 540 1600 540 600 300
adb shell input keyevent KEYCODE_BACK
adb shell input tap 540 1200                # a point, when nothing names it

adb logcat -d -t 200 > logcat.txt           # what the app said
```

Aim by text, description or id; coordinates come off `magnum qa ui
--android`, never off a guess — a tap at coordinates nobody verified is
a step that passes on the wrong button. The step rules below (one shell
block per step, act and capture together, the screenshot is evidence)
hold on Android as they do on iOS.

**One automation client per device.** While maestro's or Appium's
instrumentation holds it, `uiautomator dump` fails — `magnum qa ui
--android` says so instead of an empty screen. Do not mix them.

### iOS — AXe drives, `magnum qa ui` reads

`simctl` boots, installs and launches; it cannot tap or type. **AXe**
does — the same binary the Studio's Device panel streams and taps
through, installed by Magnum and handed to you as `$AXE`. It works on
any app the simulator runs: SwiftUI, UIKit, Expo / React Native,
Flutter — it goes through the accessibility tree, as VoiceOver does.

```bash
UDID=$(magnum qa ui --udid-only)              # DEVICE_NAME's, else the booted one
xcrun simctl install "$UDID" /path/App.app
xcrun simctl launch "$UDID" com.example.app
xcrun simctl openurl "$UDID" "myapp://deep/link"   # a deep link enters most flows

magnum qa ui                                  # the screen, as text:
#   Button "Sign in" #loginButton @201,640 120x44
#   TextField "Email" ="" @201,420 340x44
magnum qa ui --grep sign                      # just the lines you need

magnum qa tap --label "Sign in"               # by what it says
magnum qa tap --id loginButton                # by accessibilityIdentifier
magnum qa tap --label Save --type Button      # two matches: narrow by type
magnum qa tap --label Done --wait 5           # wait for it to appear
magnum qa tap -x 201 -y 640                   # only what has no element
$AXE type 'qa@example.test' --udid "$UDID"
$AXE swipe --start-x 200 --start-y 600 --end-x 200 --end-y 200 --duration 0.2 --udid "$UDID"
$AXE gesture scroll-down --udid "$UDID"       # also swipe-from-left-edge (back) …
$AXE button home --udid "$UDID"               # home, lock, side-button, siri
```

**Press with `magnum qa tap`, never `$AXE tap`.** Measured on iOS 26.5:
`axe tap` prints «completed successfully» and nothing happens — a touch
with no time between down and up is dropped. `magnum qa tap` finds the
element in the tree and presses it with a 50 ms held touch, which
lands. Swipes, gestures, typing and hardware buttons go through `$AXE`
as they are.

**A case step is ONE shell block**: its actions, then the evidence, then
the screen for the next step:

```bash
magnum qa tap --label Email && $AXE type 'qa@example.test' --udid "$UDID" \
&& magnum qa tap --label "Sign in" \
&& $AXE screenshot --udid "$UDID" --output "$ARTIFACTS/03-signed-in.png" \
&& <the attach line, as the report section shows it> \
&& magnum qa ui
```

Several gestures at once, in one simulator session, go as a `batch` — a
tap in it is a held touch too:

```bash
$AXE batch --udid "$UDID" \
  --step "touch -x 201 -y 600 --down --up --delay 0.05" \
  --step "swipe --start-x 120 --start-y 600 --end-x 180 --end-y 600 --duration 0.15"
```

The rules that make it fast:

- **Decide from `magnum qa ui`, not from a screenshot.** It lists every
  element with a label, an id or a value — type, "label", #id, =value,
  the centre a tap aims at (`@x,y`) and its size — in half a second.
- **Aim by label or id.** Coordinates only for what has no element —
  a game board, a canvas, a map — taken from that area's centre and
  size in `magnum qa ui`, never guessed. Two matches: `--element-type
  Button` narrows it.
- **A screen that moves by itself** (a game, a timer, an animation)
  changes while you think. Act and capture in the SAME command; never
  act in one turn and look in the next — that is how a falling piece
  lands and the game ends between two steps.
- **Taking the screenshot is not reading it.** It is the report's
  evidence. Open it only when the step asserts what the tree cannot
  say: a colour, a layout, pixels on a canvas.

For a Swift app you own: an `accessibilityIdentifier` on what a case
touches makes `--id` targets that survive copy changes and translation.

**One driver per simulator.** After maestro's XCTest driver has run on
a simulator, every app there reads as an empty `Application 0x0` and
AXe cannot see it until the simulator reboots — `magnum qa ui` says so,
with the command. Do not mix the two on one device.

**When `$AXE` is empty**, in this order:

1. **iOS Simulator MCP tools**, when the session has them — tap,
   swipe, type, screenshot, headless (CONDUCT 3ad; never `attach`).
2. **`maestro`** — one flow for a WHOLE journey, never one per gesture:
   every `maestro test` starts a JVM and a driver, about 9 seconds.
3. **`idb`** — only when its pair is whole (CLI + idb_companion).

None of them? The case is **blocked**, with the fix in the line:

```
blocked — no tap driver on this machine. Install one:
  Testing ▸ Device ▸ Install AXe (no Homebrew, no password)
```

Do not install anything on your own. Do not fall back to the Playwright
MCP browser or any other browser tool: **a native app is not a web
page**, and a step that pretends otherwise reports on nothing.

## 5. Evidence: a screenshot per meaningful step

Put files in the run's artifact directory that the PROTOCOL block
gave you, reference them **by basename**, and emit the attach event —
that is what puts them on the case card in the Studio.

```bash
# iOS — 0.2 s (without AXe: xcrun simctl io "$UDID" screenshot <file>)
$AXE screenshot --udid "$UDID" --output "$ARTIFACTS/03-after-login.png"
# Android
adb exec-out screencap -p > "$ARTIFACTS/03-after-login.png"
```

It rides the same shell block as the step's actions (see §4): no model
turn between what you did and the picture of it.

```json
{"event":"attach","step":3,"name":"after login","file":"03-after-login.png","mime":"image/png"}
```

Number the files by step so the report reads in order. Screenshot
**every step that changes what is on screen**, and always the failing
one — on mobile the screenshot is usually the whole evidence, and a
failure without one is a bug report that gets sent back.

## 6. Verdict

Same contract as any case. Two things worth stating explicitly in
`summary` because a reader cannot infer them from the steps:

- which platform and which device (`iPhone 17, iOS 26.5` /
  `Medium_Phone_API_36.1, API 36`) — a green case says nothing until
  you know where it ran;
- whether the app was installed fresh or was already there.

`blocked`, not `failed`, when the device could not be brought up, the
system image is missing, or the case needs an interaction this
machine cannot perform. Those are facts about the lab and **not about
the product** — filing them as product failures is how a QA report
stops being trusted.
