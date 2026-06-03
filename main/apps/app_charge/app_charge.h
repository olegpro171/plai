/**
 * @file app_charge.h
 * @brief Low-power charging mode.
 *
 * Quiesces every major consumer so the cap's limited charge current actually
 * reaches the battery: stops the mesh service (radio -> SLEEP), puts the GPS in
 * PCAS standby, turns off the LED, dims the backlight and drops the CPU to
 * 80 MHz.  Intentionally **one-way**: the only way out is a device restart, so
 * there is no restore-on-exit logic and the aggressive CPU/peripheral changes
 * are always followed by a clean fresh boot.
 */
#pragma once

#include "../apps.h"
#include <string>
#include <cstdint>

#include "apps/utils/theme/theme_define.h"
#include "apps/utils/icon/icon_define.h"

#include "assets/app_charge.h"

namespace MOONCAKE::APPS
{

    class AppCharge : public APP_BASE
    {
    private:
        struct
        {
            HAL::Hal* hal;
            bool committed;          // low-power mode engaged
            bool aborted;            // user cancelled at the confirm prompt
            uint32_t last_update_ms; // throttles the status redraw
        } _data;

        void _enter_low_power();
        void _render();

    public:
        void onCreate() override;
        void onResume() override;
        void onRunning() override;
        void onDestroy() override;
    };

    class AppCharge_Packer : public APP_PACKER_BASE
    {
        std::string getAppName() override { return "CHARGE"; }
        std::string getAppDesc() override { return "Low-power charging mode"; }
        void* getAppIcon() override { return (void*)(new AppIcon_t(image_data_app_charge, nullptr)); }
        void* newApp() override { return new AppCharge; }
        void deleteApp(void* app) override { delete (AppCharge*)app; }
    };

} // namespace MOONCAKE::APPS
