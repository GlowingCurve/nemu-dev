#include <am.h>
#include <klib.h>
#include <nemu.h>
#define SYNC_ADDR (VGACTL_ADDR + 4)

void __am_gpu_init() {}

void __am_gpu_size() {}
void __am_gpu_config(AM_GPU_CONFIG_T *cfg) {
  *cfg = (AM_GPU_CONFIG_T){.present = true,
                           .has_accel = false,
                           .width = inw(VGACTL_ADDR + 0x2),
                           .height = inw(VGACTL_ADDR),
                           .vmemsz = 0};
}

void __am_gpu_fbdraw(AM_GPU_FBDRAW_T *ctl) {
  uint16_t width = inw(VGACTL_ADDR + 0x2);
  uint32_t width_s = ctl->x;
  uint32_t height_s = ctl->y;
  uint32_t width_e = width_s + ctl->w;
  uint32_t height_e = height_s + ctl->h;
  uint32_t count = 0;

  if (ctl->pixels != NULL) {
    uint32_t *_pixels = (uint32_t *)(ctl->pixels);
    for (uint32_t i = height_s; i < height_e; i++) {
      for (uint32_t j = width_s; j < width_e; j++) {
        outl(FB_ADDR + (i * width + j) * 4, _pixels[count]);
        count++;
      }
    }
  }
  if (ctl->sync)
    outl(SYNC_ADDR, 1);
}

void __am_gpu_status(AM_GPU_STATUS_T *status) {
  status->ready = (bool)inl(SYNC_ADDR);
}
