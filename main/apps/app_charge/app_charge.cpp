/**
 * @file app_charge.cpp
 * @brief Low-power charging mode implementation. One-way: exit = device restart.
 */
#include "app_charge.h"
#include "common_define.h" // delay() / millis()
#include <format>

#include "apps/utils/ui/dialog.h"
#include "apps/utils/screenshot/screenshot_tools.h"
#include "mesh/mesh_service.h"

// Low-level CPU clock control (no CONFIG_PM_ENABLE in this build, so we drive
// rtc_clk directly). Safe here because charge mode is one-way: we never restore
// the frequency, the radio/GPS are quiesced, and exit is always a fresh reboot.
#include "soc/rtc.h"
#include "esp_rom_sys.h"

using namespace MOONCAKE::APPS;

// Tunables --------------------------------------------------------------------
#define UPDATE_INTERVAL_MS 3000 // status redraw cadence
#define CHARGE_BRIGHTNESS 20    // dim backlight (0-255)
#define CHARGE_CPU_MHZ 80       // throttled CPU frequency

// ATGM336H (CASIC) standby command. PCAS12 puts the receiver into standby; the
// exact parameter semantics are sparsely documented, so this MUST be validated
// on hardware (measure current + confirm the GPS recovers after the reboot, see
// GPS::init() wake handling). Falls back gracefully if the module ignores it.
static const char* GPS_STANDBY_CMD = "PCAS12,0";

static void set_cpu_freq_mhz(uint32_t mhz)
{
    rtc_cpu_freq_config_t cfg;
    if (rtc_clk_cpu_freq_mhz_to_config(mhz, &cfg))
    {
        rtc_clk_cpu_freq_set_config_fast(&cfg);
        esp_rom_set_cpu_ticks_per_us(mhz); // keep ROM us-delays correct
    }
}

void AppCharge::onCreate()
{
    _data.hal = mcAppGetDatabase()->Get("HAL")->value<HAL::Hal*>();
    _data.committed = false;
    _data.aborted = false;
    _data.last_update_ms = 0;
}

void AppCharge::onResume()
{
    if (_data.committed || _data.aborted)
        return;

    // One-way commit: confirm before we tear the system down.
    bool ok = UTILS::UI::show_confirmation_dialog(_data.hal,
                                                  "Charge Mode",
                                                  "Restart device to exit.",
                                                  "Start",
                                                  "Cancel");
    if (!ok)
    {
        _data.aborted = true; // destroyApp() is issued from onRunning()
        return;
    }

    _enter_low_power();
    _data.committed = true;
    _data.last_update_ms = millis();
    _render();
}

void AppCharge::onRunning()
{
    if (_data.aborted)
    {
        destroyApp();
        return;
    }
    if (!_data.committed)
        return;

    // Input: any of ESC / ENTER / home button restarts the device (the only exit).
    auto* kb = _data.hal->keyboard();
    kb->updateKeyList();
    kb->updateKeysState();
    if (kb->isPressed())
    {
        if (kb->isKeyPressing(KEY_NUM_ESC) || kb->isKeyPressing(KEY_NUM_ENTER)
#if HAL_USE_BUTTON
            || _data.hal->home_button()->is_pressed()
#endif
        )
        {
            _data.hal->reboot();
            return;
        }
    }

    // CTRL+SPACE screenshot stays available.
    UTILS::SCREENSHOT_TOOLS::check_and_handle_screenshot(_data.hal, nullptr);

    uint32_t now = millis();
    if (now - _data.last_update_ms > UPDATE_INTERVAL_MS)
    {
        _render();
        _data.last_update_ms = now;
    }

    delay(80); // keep the throttled CPU mostly idle
}

void AppCharge::onDestroy()
{
    // Nothing to restore: the only commit path exits via reboot. This runs only
    // on the cancel path, where no system state was changed.
}

void AppCharge::_enter_low_power()
{
    auto* hal = _data.hal;

    // 1) Stop the mesh service: radio -> SLEEP (~uA, TCXO auto-off) and
    //    MeshService::update() becomes a no-op, so the main loop's unconditional
    //    updateMesh() will not wake the radio back up.
    if (hal->mesh())
        hal->mesh()->stop();

    // 2) GPS into PCAS standby (the ~25 mA residual; no hardware power-enable
    //    exists on the cap). Best-effort; recovered on next boot in GPS::init().
#if HAL_USE_GPS
    if (hal->gps())
        hal->gps()->sendCommand(GPS_STANDBY_CMD);
#endif

    // 3) LED off.
#if HAL_USE_LED
    if (hal->led())
        hal->led()->off();
#endif

    // 4) Dim the backlight (do NOT displaySleep(): that makes main.cpp skip
    //    mooncake.update() and this app would stop being ticked).
    hal->display()->setBrightness(CHARGE_BRIGHTNESS);

    // 5) Drop the CPU. Never restored (exit = reboot).
    set_cpu_freq_mhz(CHARGE_CPU_MHZ);
}

void AppCharge::_render()
{
    auto* hal = _data.hal;
    auto* canvas = hal->canvas();

    float voltage = hal->getBatVoltage();
    uint8_t level = hal->getBatLevel(voltage);

    const int cx = canvas->width() / 2;
    const int cy = canvas->height() / 2;

    canvas->fillScreen(THEME_COLOR_BG);

    // Title
    canvas->setTextSize(1);
    canvas->setFont(FONT_12);
    canvas->setTextColor(THEME_COLOR_BATTERY_PWR);
    canvas->drawCenterString("CHARGING", cx, 8);

    // Big battery percentage
    canvas->setFont(FONT_16);
    canvas->setTextSize(2);
    canvas->setTextColor(level <= 20 ? THEME_COLOR_BATTERY_LOW : THEME_COLOR_BATTERY_PWR);
    canvas->drawCenterString(std::format("{}%", level).c_str(), cx, cy - 22);

    // Voltage
    canvas->setFont(FONT_12);
    canvas->setTextSize(1);
    canvas->setTextColor(TFT_WHITE);
    canvas->drawCenterString(std::format("{:.2f}V", voltage).c_str(), cx, cy + 14);

    // Exit hint
    canvas->setFont(FONT_10);
    canvas->setTextColor(THEME_COLOR_SIGNAL_TEXT);
    canvas->drawCenterString("Restart device to exit", cx, canvas->height() - 16);

    hal->canvas_update();
}
