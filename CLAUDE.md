# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Plai** is firmware for a standalone Meshtastic communicator on the M5Stack CardPuter (ESP32-S3) — a phone-free LoRa mesh messaging terminal. The mesh stack is **built from scratch on ESP-IDF, not a fork of the Meshtastic firmware**, but is wire-compatible with Meshtastic v2.7+ by encoding packets with the official Meshtastic protobufs (via Nanopb). Licensed GPL v3.

## Build, Flash, Develop

ESP-IDF **v5.5.4** (target `esp32s3`) is required. There is no host test framework — this is embedded firmware verified by building and running on hardware.

```bash
# One-time prerequisite (see "Protobufs" below) — main/meshtastic/ is generated & gitignored
git submodule update --init          # fetch the meshtastic/protobufs submodule
# then generate the Nanopb sources into main/meshtastic/ (regen-protos.bat on Windows)

idf.py set-target esp32s3
idf.py build
idf.py -p <PORT> flash monitor       # e.g. -p /dev/cu.usbmodem* on macOS

idf.py menuconfig                     # → "HAL Configuration" to toggle peripherals
```

`menuconfig` → **HAL Configuration** toggles each peripheral (`HAL_USE_DISPLAY`, `HAL_USE_RADIO`, `HAL_USE_GPS`, etc.). These map `CONFIG_HAL_USE_*` (from `sdkconfig`) to the `HAL_USE_*` macros in [hal_config.h](main/hal/hal_config.h); all HAL code is wrapped in `#if HAL_USE_*` guards, so a disabled peripheral is compiled out entirely.

Build specifics: 2 MB flash, custom partition table ([partitions.csv](partitions.csv), app partition is named `plai`), no SPIRAM, **C++ exceptions disabled**. The NVS default image is baked from [nvs.csv](nvs.csv) at build time via `nvs_create_partition_image` — edit that file to change factory-default settings. Firmware version comes from [version.txt](version.txt) (injected as `BUILD_NUMBER`).

## Architecture

Three layers, wired together in [main/main.cpp](main/main.cpp): **HAL** (hardware) → **Mesh** (protocol) → **Apps** (UI on the mooncake framework). The HAL owns the `MeshService` and `NodeDB`; `main.cpp` constructs the `Settings`, `HalCardputer`, and `Mooncake` singletons and runs a single super-loop.

### Main loop (`main/main.cpp`)
Single-threaded cooperative super-loop, no RTOS task per app:
1. `hal.updateMesh()` — pump radio/protocol events every iteration.
2. If the display is asleep: drop into a low-power `xTaskNotifyWait`. Keyboard and radio ISRs call `setNotifyTask(main_task)` to wake it (interrupt-driven, not polled).
3. Otherwise: `mooncake.update()` runs the current app's lifecycle method.

### HAL (`main/hal/`)
`Hal` base class ([hal.h](main/hal/hal.h)) exposes every peripheral via a getter (`hal->radio()`, `hal->keyboard()`, `hal->canvas()`, …); `HalCardputer` ([hal_cardputer.cpp](main/hal/hal_cardputer.cpp)) is the concrete implementation and auto-detects board variant (`CARDPUTER` vs `CARDPUTER_ADV`, which differ in keyboard controller). Each peripheral lives in its own subdir: `display/` (LovyanGFX/ST7789), `keyboard/`, `radio/` (SX1262 LoRa), `sdcard/`, `gps/`, `speaker/`, `led/`, `bat/`, `i2c/`, `ioex/`, `button/`. Pin maps and LoRa/GPS defaults are in [board.h](main/hal/board.h).

### Mesh (`main/mesh/`)
The from-scratch Meshtastic protocol stack:
- **`MeshService`** ([mesh_service.h](main/mesh/mesh_service.h)) — core protocol: AES-CTR channel encryption + X25519 PKI, per-port packet handlers (text/position/nodeinfo/telemetry/traceroute/neighborinfo/admin), periodic broadcasts, ACK/NACK with retries (`_pending_acks`), airtime/duty-cycle tracking, and a Meshtastic-compatible CSMA/CA TX delay with CAD. Config lives in the `MeshConfig` struct, loaded from `Settings` via `loadConfigFromSettings()`.
- **`PacketRouter`** ([packet_router.h](main/mesh/packet_router.h)) — priority TX queue (ACK > Routing > Admin > Reliable > Default > Background) and RX queue; owns the 16-byte on-air `PacketHeader` layout.
- **`NodeDB`** ([node_db.h](main/mesh/node_db.h)) — up to 1000 nodes, **SD-backed with lazy loading** (a `manifest.idx` indexes per-node files; nodes are not all held in RAM). Exposes a change counter that apps poll instead of re-reading.
- **`MeshData`** ([mesh_data.h](main/mesh/mesh_data.h)) — message store, traceroute log, and quick-message templates, all file-backed on SD.

### Apps (`main/apps/`) and the mooncake framework
Apps run on **mooncake** ([components/mooncake/](components/mooncake/)), a tiny app-lifecycle framework. Each app is **two classes**:
- An **`APP_BASE`** subclass with an Android-Activity-like lifecycle FSM: `onCreate` / `onResume` / `onRunning` (called every frame) / `onRunningBG` / `onPause` / `onDestroy`. App state is typically held in one private `_data` struct.
- An **`APP_PACKER_BASE`** subclass holding static metadata (`getAppName`, `getAppDesc`, `getAppIcon`) and a `newApp`/`deleteApp` factory, so the launcher can create/destroy apps on demand to save RAM.

Apps are registered in `app_main` via `mooncake.installApp(new XxxApp_Packer)`. To **add an app**: create `app_xxx/app_xxx.{h,cpp}` defining both classes, add its header to [apps.h](main/apps/apps.h), and install it in [main/main.cpp](main/main.cpp). Source globs (`apps/*.cpp`, `hal/*.cpp`, etc. in [main/CMakeLists.txt](main/CMakeLists.txt)) pick up new files automatically.

Cross-app data is shared through mooncake's `SimpleKV` key-value `_database`, populated in `_data_base_setup_callback` with the `"HAL"` and `"SETTINGS"` pointers; inside an app, reach them via `mcAppGetDatabase()`.

**Rendering & input** (no retained-mode UI — apps draw imperatively each frame):
- Draw into the `LGFX_Sprite` framebuffer `hal->canvas()`, then present with `hal->canvas_update()`. The status bar is a separate sprite (`hal->canvas_system_bar()` / `canvas_system_bar_update()`).
- Poll input by calling `hal->keyboard()->updateKeyList()` + `updateKeysState()`, then `isKeyPressing(KEY_NUM_*)`, `keysState().ctrl`, `waitForRelease(...)`.
- Shared UI lives in `apps/utils/`: `ui/dialog` (modal dialogs/confirmations), `ui/settings_screen`, `ui/key_repeat`, `theme/` (efont Unicode fonts + SD-card emoji PNG rendering), `screenshot/` (CTRL+SPACE → save PNG to SD), `smooth_menu/` (launcher), `anim/` (scrolling/highlight text), `text/`, `icon/`.
- **On-screen keyboard layouts** for text entry are defined in [dialog.cpp](main/apps/utils/ui/dialog.cpp) as the `kbd_layouts[]` array — English (default), Ukrainian (ЙЦУКЕН), and Russian (ЙЦУКЕН). Each `KbdLayout` is two 47-entry arrays (`chars` / `chars_shift`) indexed positionally by the `key_nums[]` physical-key map, plus a mode label + color. `[OPT]` cycles layouts (`(kbd_layout + 1) % KBD_LAYOUT_COUNT`, auto-sized from the array) and the renderer overlays Latin→Cyrillic for any non-English layout — so **adding a layout is purely additive**: append one entry to `kbd_layouts[]` (UTF-8 strings; the `efont_unicode_*` fonts already cover Cyrillic glyphs).

Apps present: `launcher`, `app_settings`, `app_nodes`, `app_channels`, `app_monitor`, `app_stats`. `app_graphs` exists but is disabled (`#if 0`).

### Settings & persistence (`main/settings/`)
`Settings` ([settings.h](main/settings/settings.h)) wraps **NVS** with an in-RAM cache and a metadata-driven model (`SettingGroup` → `SettingItem` with type/default/min/max/callback). Values are namespaced (`system`, `lora`, `security`, `nodeinfo`, `position`, `devmetrics`, …) — see [nvs.csv](nvs.csv) for the full key list and defaults. Supports export/import to SD.

**Persistence split (important):** mesh keys and device config live in **NVS** and are wiped by a firmware reflash unless exported to SD first. The node database and chat history live on the **SD card** (`/sdcard/meshtastic/`) and survive firmware updates. SD layout includes `nodes/`, `messages/`, `traceroute/`, `neighbors/`, plus `prefs.pb`, `channels.pb`, `favorites.dat`, `ignorelist.dat`, `templates.txt`; emoji at `/sdcard/emoji/u<HEX>.png` and map tiles at `/sdcard/map/<style>/{z}/{x}/{y}.jpg`.

### Protobufs (`main/meshtastic/`) — generated, gitignored
The Nanopb-generated C sources in `main/meshtastic/` are **not checked in** (gitignored) and **must be generated before the first build**. They come from the `meshtastic/protobufs` git submodule. Regeneration is done by [regen-protos.bat](regen-protos.bat), which runs Nanopb's `protoc` over `protobufs/meshtastic/*.proto`. Note that script is Windows-only with a hardcoded toolchain path — on other platforms, run the equivalent `nanopb_generator` invocation. This generated layer is what provides Meshtastic wire compatibility.

## Conventions

- **Formatting** is enforced by [.clang-format](.clang-format): LLVM base, 4-space indent, 128-column limit, **Allman braces**, left-aligned pointers (`Type* x`), namespaces indented, `BinPackArguments/Parameters: false`, and **includes are not auto-sorted** (order is intentional).
- **No C++ exceptions** (disabled in `sdkconfig`) — use return codes / status enums (e.g. `meshtastic_Routing_Error`).
- **Naming**: namespaces are `HAL`, `Mesh`, `SETTINGS`, `MOONCAKE::APPS`, `UTILS`; private members are `_`-prefixed; protobuf types keep their generated `meshtastic_*` names.
- Use the `delay(ms)` / `millis()` macros from [common_define.h](main/common_define.h) rather than raw FreeRTOS calls.
