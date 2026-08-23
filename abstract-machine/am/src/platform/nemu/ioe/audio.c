#include <am.h>
#include <nemu.h>
#include <klib.h>

#define AUDIO_FREQ_ADDR      (AUDIO_ADDR + 0x00)
#define AUDIO_CHANNELS_ADDR  (AUDIO_ADDR + 0x04)
#define AUDIO_SAMPLES_ADDR   (AUDIO_ADDR + 0x08)
#define AUDIO_SBUF_SIZE_ADDR (AUDIO_ADDR + 0x0c)
#define AUDIO_INIT_ADDR      (AUDIO_ADDR + 0x10)
#define AUDIO_COUNT_ADDR     (AUDIO_ADDR + 0x14)
#define AUDIO_SB_ADDR        0xa1200000

void __am_audio_init() {
}

void __am_audio_config(AM_AUDIO_CONFIG_T *cfg) {
  cfg->present = (bool)1;
  cfg->bufsize = (int)inl(AUDIO_SBUF_SIZE_ADDR);
}

void __am_audio_ctrl(AM_AUDIO_CTRL_T *ctrl) {
  outl(AUDIO_FREQ_ADDR, (uint32_t)(ctrl->freq));
  outl(AUDIO_CHANNELS_ADDR, (uint32_t)(ctrl->channels));
  outl(AUDIO_SAMPLES_ADDR, (uint32_t)(ctrl->samples));
}

void __am_audio_status(AM_AUDIO_STATUS_T *stat) {
  stat->count = (int)inl(AUDIO_COUNT_ADDR);
}

void __am_audio_play(AM_AUDIO_PLAY_T *ctl) {
  
  uint8_t * buf = ctl->buf.start;
  uint32_t len = (ctl->buf.end) - (ctl->buf.start);
  uint32_t buf_length = inl(AUDIO_SBUF_SIZE_ADDR);
  
  if (len > (int)(buf_length - inl(AUDIO_COUNT_ADDR))) {
    while (len > (int)(buf_length - inl(AUDIO_COUNT_ADDR)));
  }
  
  for (int i = 0; i < len; i ++) {
    outb(AUDIO_SB_ADDR + i, buf[i]);
  }
}
