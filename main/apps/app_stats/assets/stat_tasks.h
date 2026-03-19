
/*******************************************************************************
* Task list icon for stats app (12x12, RGB565)
* Simple list with horizontal lines representing tasks
*******************************************************************************/

#include <stdint.h>

#define BG 0x8631
#define FG 0x1faf
#define DT 0x5d2d
#define HL 0xdc04

static const uint16_t image_data_stat_tasks[144] = {
    // ∙∙∙∙∙∙∙∙∙∙∙∙
    // ∙░██████████░
    // ∙█▒▒▒▒▒▒▒▒▒█
    // ∙█░▒▒████▒▒█
    // ∙█▒▒▒▒▒▒▒▒▒█
    // ∙█░▒▒███████
    // ∙█▒▒▒▒▒▒▒▒▒█
    // ∙█░▒▒████▒▒█
    // ∙█▒▒▒▒▒▒▒▒▒█
    // ∙█░▒▒██▒▒▒▒█
    // ∙░██████████░
    // ∙∙∙∙∙∙∙∙∙∙∙∙
    BG, BG, BG, BG, BG, BG, BG, BG, BG, BG, BG, BG,
    BG, FG, FG, FG, FG, FG, FG, FG, FG, FG, FG, BG,
    FG, DT, DT, DT, DT, DT, DT, DT, DT, DT, DT, FG,
    FG, HL, DT, DT, FG, FG, FG, FG, DT, DT, DT, FG,
    FG, DT, DT, DT, DT, DT, DT, DT, DT, DT, DT, FG,
    FG, HL, DT, DT, FG, FG, FG, FG, FG, FG, DT, FG,
    FG, DT, DT, DT, DT, DT, DT, DT, DT, DT, DT, FG,
    FG, HL, DT, DT, FG, FG, FG, FG, DT, DT, DT, FG,
    FG, DT, DT, DT, DT, DT, DT, DT, DT, DT, DT, FG,
    FG, HL, DT, DT, FG, FG, DT, DT, DT, DT, DT, FG,
    BG, FG, FG, FG, FG, FG, FG, FG, FG, FG, FG, BG,
    BG, BG, BG, BG, BG, BG, BG, BG, BG, BG, BG, BG
};

#undef BG
#undef FG
#undef DT
#undef HL
