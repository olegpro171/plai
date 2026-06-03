# CONFIGURE_DEPENDS re-globs these directories on every build so newly added
# sources are compiled without a manual `idf.py reconfigure`. It is only valid in
# build mode: ESP-IDF also evaluates this file in CMake script mode (to extract
# component requirements), where CONFIGURE_DEPENDS is rejected, so gate on that.
if(CMAKE_SCRIPT_MODE_FILE)
    set(GLOB_CFG_DEPENDS "")
else()
    set(GLOB_CFG_DEPENDS CONFIGURE_DEPENDS)
endif()

file(GLOB_RECURSE APPS_SRCS ${GLOB_CFG_DEPENDS}
    apps/*.c
    apps/*.cpp
)

file(GLOB_RECURSE HAL_SRCS ${GLOB_CFG_DEPENDS}
    hal/*.c
    hal/*.cpp
)

file(GLOB_RECURSE SETTINGS_SRCS ${GLOB_CFG_DEPENDS}
    settings/*.c
    settings/*.cpp
)

file(GLOB_RECURSE PROTOS_SRCS ${GLOB_CFG_DEPENDS}
    meshtastic/*.c
    meshtastic/*.cpp
)

file(GLOB_RECURSE MESH_SRCS ${GLOB_CFG_DEPENDS}
    mesh/*.c
    mesh/*.cpp
)

idf_component_register(SRCS "main.cpp" ${APPS_SRCS} ${HAL_SRCS} ${SETTINGS_SRCS} ${PROTOS_SRCS} ${MESH_SRCS}
                    INCLUDE_DIRS "." "hal"
                    REQUIRES LovyanGFX mooncake Nanopb fatfs esp_adc driver mbedtls
                    WHOLE_ARCHIVE
                    EMBED_FILES sound/error.wav sound/boot_sound.wav image/boot_logo.png sound/knock.wav sound/morse.wav sound/seagull.wav sound/pum_pam.wav sound/tum_tum.wav sound/eight_bit.wav sound/gps.wav sound/eagle.wav sound/parrot.wav sound/trace.wav sound/duck.wav sound/chicken.wav sound/woodpecker.wav sound/cb_press.wav sound/cb_release.wav
                    )
                    
                    
nvs_create_partition_image(nvs ../nvs.csv FLASH_IN_PROJECT)