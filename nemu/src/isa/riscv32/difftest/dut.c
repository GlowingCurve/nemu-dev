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

#include <isa.h>
#include <cpu/difftest.h>
#include "../local-include/reg.h"
#include "isa-def.h"

bool isa_difftest_checkregs(CPU_state *ref_r, vaddr_t pc) {
  for (int i = 0; i < 32; i ++) {
    if (ref_r->gpr[i] != gpr(i)) {
      printf("Oops!PC:0x%x GPR[%d] should be 0x%08x , but be 0x%08x\n",pc,i,ref_r->gpr[i], gpr(i));
      return false;
    }
  }
  if (ref_r->pc != pc) {
    printf("Oops! REF: pc 0x%08x DUT:pc 0x%08x\n", ref_r->pc, pc); 
    return false;
  }
  if (ref_r->csr_t[0] != csr(mtvec_addr)) {
    printf("Oops! REF: mtvec 0x%08x DUT: pc 0x%08x\n", ref_r->csr_t[0], csr(mtvec_addr));
    return false;
  }
  if (ref_r->csr_t[1] != csr(mepc_addr)) {
    printf("Oops! REF: mepc 0x%08x DUT: mepc 0x%08x\n", ref_r->csr_t[1], csr(mepc_addr));
    return false;
  }
  return true;
}

void isa_difftest_attach() {
}
