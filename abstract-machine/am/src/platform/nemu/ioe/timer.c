#include <am.h>
#include <nemu.h>
#include <stdio.h>

uint64_t boot_time = 0;
uint64_t cur_time = 0;

void __am_timer_init() {
  boot_time = (uint64_t)inl(RTC_ADDR) + (((uint64_t)inl(RTC_ADDR + 0x4)) << 32);
}

void __am_timer_uptime(AM_TIMER_UPTIME_T *uptime) {
  cur_time = (uint64_t)inl(RTC_ADDR) + (((uint64_t)inl(RTC_ADDR + 0x4)) << 32); 
  //printf("%u\n",cur_time);
  uptime->us = cur_time - boot_time;
}

void __am_timer_rtc(AM_TIMER_RTC_T *rtc) {
  rtc->second = 0;
  rtc->minute = 0;
  rtc->hour   = 0;
  rtc->day    = 0;
  rtc->month  = 0;
  rtc->year   = 1900;
}
