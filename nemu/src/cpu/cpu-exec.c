/***************************************************************************************
 * Copyright (c) 2014-2024 Zihao Yu, Nanjing University
 *
 * NEMU is licensed under Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan
 * PSL v2. You may obtain a copy of Mulan PSL v2 at:
 *          http://license.coscl.org.cn/MulanPSL2
 *
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY
 * KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
 * NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
 *
 * See the Mulan PSL v2 for more details.
 ***************************************************************************************/

#include "utils.h"
#include <cpu/cpu.h>
#include <cpu/decode.h>
#include <cpu/difftest.h>
#include <locale.h>

/* The assembly code of instructions executed is only output to the screen
 * when the number of instructions executed is less than this value.
 * This is useful when you use the `si' command.
 * You can modify this value as you want.
 */
CPU_state cpu = {};
uint64_t g_nr_guest_inst = 0;
static uint64_t g_timer = 0; // unit: us

void device_update();
int WP_checking();
void print_iringbuf();

/*static void trace_and_difftest(Decode *_this, vaddr_t dnpc) {
#ifdef CONFIG_ITRACE
  log_write("[ITRACE]: %s\n", _this->logbuf);
  IFDEF(CONFIG_ITRACE, puts("[ITRACE]:"));
  IFDEF(CONFIG_ITRACE, puts(_this->logbuf));
#endif
  IFDEF(CONFIG_DIFFTEST, difftest_step(_this->pc, dnpc));
#ifdef CONFIG_WATCHPOINT
  if (WP_checking() == 1 && nemu_state.state == NEMU_RUNNING) {
    nemu_state.state = NEMU_STOP;
  }
#endif
}*/

static void exec_once() {
  cpu.pc = isa_exec_once(cpu.pc);
  // printf("PC:0x%08x 0x%08x 0x%08x\n", pc, cpu.gpr[15], cpu.gpr[8]);
#ifdef CONFIG_ITRACE
  char *p = s->logbuf;
  p += snprintf(p, sizeof(s->logbuf), FMT_WORD ":", s->pc);
  int ilen = s->snpc - s->pc;
  int i;
  uint8_t *inst = (uint8_t *)&s->isa.inst;
#ifdef CONFIG_ISA_x86
  for (i = 0; i < ilen; i++) {
#else
  for (i = ilen - 1; i >= 0; i--) {
#endif
    p += snprintf(p, 4, " %02x", inst[i]);
  }
  int ilen_max = MUXDEF(CONFIG_ISA_x86, 8, 4);
  int space_len = ilen_max - ilen;
  if (space_len < 0)
    space_len = 0;
  space_len = space_len * 3 + 1;
  memset(p, ' ', space_len);
  p += space_len;

  void disassemble(char *str, int size, uint64_t pc, uint8_t *code, int nbyte);
  disassemble(p, s->logbuf + sizeof(s->logbuf) - p,
              MUXDEF(CONFIG_ISA_x86, s->snpc, s->pc), (uint8_t *)&s->isa.inst,
              ilen);
#endif
}

static void execute(uint64_t n) {
  uint64_t n_orignal = n;
  for (; n > 0; n--) {
    exec_once();
    // g_nr_guest_inst++;
    // trace_and_difftest(&s, cpu.pc);
    if (nemu_state.state != NEMU_RUNNING)
      break;
    // IFDEF(CONFIG_DEVICE, device_update());
  }
  g_nr_guest_inst += n_orignal - n;
}

static void statistic() {
  IFNDEF(CONFIG_TARGET_AM, setlocale(LC_NUMERIC, ""));
#define NUMBERIC_FMT MUXDEF(CONFIG_TARGET_AM, "%", "%'") PRIu64
#ifdef CONFIG_PRINT_LOG
  Log("host time spent = " NUMBERIC_FMT " us", g_timer);
  Log("total guest instructions = " NUMBERIC_FMT, g_nr_guest_inst);
  if (g_timer > 0)
    Log("simulation frequency = " NUMBERIC_FMT " inst/s",
        g_nr_guest_inst * 1000000 / g_timer);
  else
    Log("Finish running in less than 1 us and can not calculate the simulation "
        "frequency");
#endif
}

void assert_fail_msg() {
  isa_reg_display();
  print_iringbuf();
  statistic();
}

/* Simulate how the CPU works. */
void cpu_exec(uint64_t n) {

  cpu.csr[5] = 0x00001800; // set mstatus 0xa0001800

  switch (nemu_state.state) {
  case NEMU_END:
  case NEMU_ABORT:
  case NEMU_QUIT:
    printf("Program execution has ended. To restart the program, exit NEMU and "
           "run again.\n");
    return;
  default:
    nemu_state.state = NEMU_RUNNING;
  }

  uint64_t timer_start = get_time();

  execute(n);

  /*for (int i = 0; i < 32; i ++) {
    printf("x%d: 0x%08x\n", i, cpu.gpr[i]);
  }
  printf("PC: 0x%08x\n", cpu.pc);*/
  uint64_t timer_end = get_time();
  g_timer += timer_end - timer_start;

  switch (nemu_state.state) {
  case NEMU_RUNNING:
    nemu_state.state = NEMU_STOP;
    break;

  case NEMU_END:
  case NEMU_ABORT:
#ifdef CONFIG_PRINT_LOG
    Log("nemu: %s at pc = " FMT_WORD,
        (nemu_state.state == NEMU_ABORT
             ? ANSI_FMT("ABORT", ANSI_FG_RED)
             : (nemu_state.halt_ret == 0
                    ? ANSI_FMT("HIT GOOD TRAP", ANSI_FG_GREEN)
                    : ANSI_FMT("HIT BAD TRAP", ANSI_FG_RED))),
        nemu_state.halt_pc);
#endif
    // fall through
  case NEMU_QUIT:
    statistic();
  }
}
