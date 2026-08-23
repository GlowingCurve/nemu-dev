/***************************************************************************************
* Copyright (c) 2014-2024 Zihao Yu, Nanjing University
*
* NEMU is licensed under Mulan PSL v2.
* You can use this software according to the terms and conditions of the Mulan PSL v2.
* You may obtain a copy of Mulan PSL v2 at:
*          http://license.coscl.org.cn/MulanPSL2
*
* THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
* EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
* MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
*
* See the Mulan PSL v2 for more details.
***************************************************************************************/

#include <SDL2/SDL_audio.h>
#include <SDL2/SDL_platform.h>
#include <SDL2/SDL_stdinc.h>
#include <common.h>
#include <device/map.h>
#include <SDL2/SDL.h>

enum {
  reg_freq,
  reg_channels,
  reg_samples,
  reg_sbuf_size,
  reg_init,
  reg_count,
  nr_reg
};

static uint8_t *sbuf = NULL;
static uint32_t *audio_base = NULL;

static Uint8 ring_sbuf[CONFIG_SB_SIZE] = {};
static uint32_t head = 0;
static uint32_t tail = 0;
static uint32_t audio_len = 0;

SDL_AudioSpec s = {};

void audio_len_update () {
  audio_len = (head <= tail) ? tail - head : CONFIG_SB_SIZE - (head - tail);
  audio_base[reg_count] = audio_len;
}

void SDLCALL audio_callback(void  * userdata, Uint8 * stream, int len) {
  SDL_memset(stream, 0, len);

  if (audio_len == 0) {
    return;
  }  

  if ((Uint32)len > audio_len) {
    len = (int)audio_len;
  }

  for (int i = 0; i < len; i ++) {
    stream[i] = ring_sbuf[head];
    head = (head + 1) % CONFIG_SB_SIZE;
  }

  audio_len_update();
}

static void audio_io_handler(uint32_t offset, int len, bool is_write) {
  if (is_write) {
    if (offset == 4 * reg_init) {
      s.format = AUDIO_S16SYS;
      s.userdata = NULL;
      s.silence = 0;
      s.callback = audio_callback;
      return;
    }    

    if (offset == 4 * reg_freq) {
      s.freq = audio_base[reg_freq];
      return;
    }

    if (offset == 4 * reg_channels) {
      s.channels = audio_base[reg_channels];
      return ;
    }

    if (offset == 4 * reg_samples) {
      s.samples = audio_base[reg_samples];
      
      // Here we assume sample is the last parameter to initialize;
      SDL_InitSubSystem(SDL_INIT_AUDIO);
      SDL_OpenAudio(&s, NULL);
      SDL_PauseAudio(0);
      //It means we can't change the parameter of the audio once start!
     
      return;
    }
  }
}

static void audio_sbuf_handler(uint32_t offset, int len, bool is_write) {
  if (is_write) {
    if (len == 1) {
      ring_sbuf[tail] = sbuf[offset];
      tail = (tail + 1) % CONFIG_SB_SIZE;
      audio_len_update();
    } 
  } 
}

void init_audio() {
  uint32_t space_size = sizeof(uint32_t) * nr_reg;
  audio_base = (uint32_t *)new_space(space_size);
#ifdef CONFIG_HAS_PORT_IO
  add_pio_map ("audio", CONFIG_AUDIO_CTL_PORT, audio_base, space_size, audio_io_handler);
#else
  add_mmio_map("audio", CONFIG_AUDIO_CTL_MMIO, audio_base, space_size, audio_io_handler);
#endif
  
  audio_base[reg_sbuf_size] = CONFIG_SB_SIZE;
  audio_base[reg_count] = 0;
  sbuf = (uint8_t *)new_space(CONFIG_SB_SIZE);
  add_mmio_map("audio-sbuf", CONFIG_SB_ADDR, sbuf, CONFIG_SB_SIZE, audio_sbuf_handler);
}
