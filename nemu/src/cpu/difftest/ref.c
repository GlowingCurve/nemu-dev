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

#include "common.h"
#include <cpu/cpu.h>
#include <difftest-def.h>
#include <isa.h>
#include <memory/paddr.h>
#include <string.h>

void diff_memcpy(paddr_t addr, void *buf, size_t n) {
  memcpy(guest_to_host(addr), buf, n);
  /*uint32_t * p = (uint32_t *)guest_to_host(addr);
  for (int i = 0; i < 32; i++) {
      printf("0x%08x\n",*p);
      p++;
  }*/
}

void diff_set_reg(void *dut) {
  CPU_state *dut_cpu = (CPU_state *)dut;
  for (int i = 0; i < 16; i++) {
    cpu.gpr[i] = dut_cpu->gpr[i];
  }
  cpu.pc = dut_cpu->pc;
  cpu.csr[10] = dut_cpu->csr_t[0];
  cpu.csr[15] = dut_cpu->csr_t[1];
  printf("Difftest set REF regs\n");
  for (int i = 0; i < 16; i++) {
    printf("$%d REF: 0x%08x\n", i, cpu.gpr[i]);
  }
  printf("REF PC: 0x%08x\n", cpu.pc);
}

void diff_get_reg(void *ref) {
  CPU_state *ref_cpu = (CPU_state *)ref;
  for (int i = 0; i < 16; i++) {
    ref_cpu->gpr[i] = cpu.gpr[i];
  }
  ref_cpu->pc = cpu.pc;
  ref_cpu->csr_t[0] = cpu.csr[10]; // mtvec
  ref_cpu->csr_t[1] = cpu.csr[15]; // mepc
}

__EXPORT void difftest_memcpy(paddr_t addr, void *buf, size_t n,
                              bool direction) {
  if (direction == DIFFTEST_TO_REF) {
    diff_memcpy(addr, buf, n);
  } else {
    assert(0);
  }
}

__EXPORT void difftest_regcpy(void *dut, bool direction) {
  if (direction == DIFFTEST_TO_REF) {
    diff_set_reg(dut);
  } else {
    diff_get_reg(dut);
  }
}

__EXPORT void difftest_exec(uint64_t n) { cpu_exec(n); }

__EXPORT void difftest_raise_intr(word_t NO) { assert(0); }

__EXPORT void difftest_init(int port) {
  void init_mem();
  init_mem();
  /* Perform ISA dependent initialization. */
  init_isa();
}
