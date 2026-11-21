// Pebbo body on an ESP32-S3-BOX-3. Based on main/boards/espressif/esp32-s3-box-3 (MIT).
#ifndef _BOARD_CONFIG_H_
#define _BOARD_CONFIG_H_

#include <driver/gpio.h>

#define AUDIO_INPUT_SAMPLE_RATE  24000
#define AUDIO_OUTPUT_SAMPLE_RATE 24000

#define AUDIO_INPUT_REFERENCE    true

#define AUDIO_I2S_GPIO_MCLK GPIO_NUM_2
#define AUDIO_I2S_GPIO_WS GPIO_NUM_45
#define AUDIO_I2S_GPIO_BCLK GPIO_NUM_17
#define AUDIO_I2S_GPIO_DIN  GPIO_NUM_16
#define AUDIO_I2S_GPIO_DOUT GPIO_NUM_15

#define AUDIO_CODEC_PA_PIN       GPIO_NUM_46
#define AUDIO_CODEC_I2C_SDA_PIN  GPIO_NUM_8
#define AUDIO_CODEC_I2C_SCL_PIN  GPIO_NUM_18
#define AUDIO_CODEC_ES8311_ADDR  ES8311_CODEC_DEFAULT_ADDR
#define AUDIO_CODEC_ES7210_ADDR  ES7210_CODEC_DEFAULT_ADDR

#define BUILTIN_LED_GPIO        GPIO_NUM_NC
// Pebbo's lights: one WS2812B chain on the BRACKET's PMOD header. 24 in the ring in the
// base, then one in each wing and one under the cap.
#define PEBBO_LED_GPIO          GPIO_NUM_39
#define PEBBO_LED_COUNT         27
#define BOOT_BUTTON_GPIO        GPIO_NUM_0
#define VOLUME_UP_BUTTON_GPIO   GPIO_NUM_NC
#define VOLUME_DOWN_BUTTON_GPIO GPIO_NUM_NC

#define DISPLAY_WIDTH   320
#define DISPLAY_HEIGHT  240
#define DISPLAY_MIRROR_X true
#define DISPLAY_MIRROR_Y true
#define DISPLAY_SWAP_XY false

#define DISPLAY_OFFSET_X  0
#define DISPLAY_OFFSET_Y  0

#define DISPLAY_BACKLIGHT_PIN GPIO_NUM_47
#define DISPLAY_BACKLIGHT_OUTPUT_INVERT false


#endif // _BOARD_CONFIG_H_
