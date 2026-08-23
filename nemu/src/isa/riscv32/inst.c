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
#include "isa-def.h"
#include "isa.h"
#include "local-include/reg.h"
#include "macro.h"
#include <cpu/cpu.h>
#include <cpu/decode.h>
#include <cpu/ifetch.h>
#include <stdint.h>

#define R(i) gpr(i)
#define CSR(i) csr(i)
#define Mr vaddr_read
#define Mw vaddr_write

static unsigned long inst_count = 0;
static char iringbuf[16][128] = {};

void ftrace(word_t inst, word_t pc);

enum {
  TYPE_I,
  TYPE_U,
  TYPE_S,
  TYPE_N,
  TYPE_J,
  TYPE_R,
  TYPE_B, // none
};

#define src1R()                                                                \
  do {                                                                         \
    *src1 = R(rs1);                                                            \
  } while (0)
#define src2R()                                                                \
  do {                                                                         \
    *src2 = R(rs2);                                                            \
  } while (0)
#define immI()                                                                 \
  do {                                                                         \
    *imm = SEXT(BITS(i, 31, 20), 12);                                          \
  } while (0)
#define immU()                                                                 \
  do {                                                                         \
    *imm = SEXT(BITS(i, 31, 12), 20) << 12;                                    \
  } while (0)
#define immS()                                                                 \
  do {                                                                         \
    *imm = (SEXT(BITS(i, 31, 25), 7) << 5) | BITS(i, 11, 7);                   \
  } while (0)
#define immJ()                                                                 \
  do {                                                                         \
    *imm = SEXT(((BITS(i, 31, 31) << 20) + (BITS(i, 19, 12) << 12) +           \
                 (BITS(i, 20, 20) << 11) + (BITS(i, 30, 21) << 1)),            \
                21);                                                           \
  } while (0)
#define immB()                                                                 \
  do {                                                                         \
    *imm = SEXT(((BITS(i, 31, 31) << 12) + (BITS(i, 30, 25) << 5) +            \
                 (BITS(i, 11, 8) << 1) + (BITS(i, 7, 7) << 11)),               \
                13);                                                           \
  } while (0)
#define csrR()                                                                 \
  do {                                                                         \
    csr_t = CSR(imm);                                                          \
  } while (0)

static word_t _div(word_t src1, word_t src2) {
  if (src1 == 0x80000000 && src2 == 0xFFFFFFFF)
    return 0x80000000;
  if (src2 == 0)
    return 0xFFFFFFFF;
  else
    return ((sword_t)src1) / ((sword_t)src2);
}

static word_t _rem(word_t src1, word_t src2) {
  if (src1 == 0x80000000 && src2 == 0xFFFFFFFF)
    return 0;
  if (src2 == 0)
    return src1;
  else
    return ((sword_t)src1) % ((sword_t)src2);
}

static void decode_operand(Decode *s, int *rd, word_t *src1, word_t *src2,
                           word_t *imm, int type) {
  uint32_t i = s->isa.inst;
  int rs1 = BITS(i, 19, 15);
  int rs2 = BITS(i, 24, 20);
  *rd = BITS(i, 11, 7);
  switch (type) {
  case TYPE_I:
    src1R();
    immI();
    break;
  case TYPE_U:
    immU();
    break;
  case TYPE_S:
    src1R();
    src2R();
    immS();
    break;
  case TYPE_N:
    break;
  case TYPE_J:
    immJ();
    break;
  case TYPE_R:
    src1R();
    src2R();
    break;
  case TYPE_B:
    src1R();
    src2R();
    immB();
    break;
  default:
    panic("unsupported type = %d", type);
  }
}

static int decode_exec(Decode *s) {
  s->dnpc = s->snpc;

#define INSTPAT_INST(s) ((s)->isa.inst)
#define INSTPAT_MATCH(s, name, type, ... /* execute body */)                   \
  {                                                                            \
    int rd = 0;                                                                \
    word_t src1 = 0, src2 = 0, imm = 0;                                        \
    decode_operand(s, &rd, &src1, &src2, &imm, concat(TYPE_, type));           \
    __VA_ARGS__;                                                               \
  }

  INSTPAT_START();
  INSTPAT("??????? ????? ????? ??? ????? 01101 11", lui, U, R(rd) = imm);
  INSTPAT("??????? ????? ????? ??? ????? 00101 11", auipc, U,
          R(rd) = s->pc + imm);
  INSTPAT("??????? ????? ????? ??? ????? 11011 11", jal, J, R(rd) = s->pc + 4,
          s->dnpc = s->pc + imm);
  INSTPAT("??????? ????? ????? 000 ????? 11001 11", jalr, I, R(rd) = s->pc + 4,
          s->dnpc = (src1 + imm) & (~1));
  INSTPAT("??????? ????? ????? 000 ????? 11000 11", beq, B,
          s->dnpc = (src1 == src2) ? s->pc + imm : s->dnpc);
  INSTPAT("??????? ????? ????? 001 ????? 11000 11", bne, B,
          s->dnpc = (src1 != src2) ? s->pc + imm : s->dnpc);
  INSTPAT("??????? ????? ????? 100 ????? 11000 11", blt, B,
          s->dnpc = ((sword_t)src1 < (sword_t)src2) ? s->pc + imm : s->dnpc);
  INSTPAT("??????? ????? ????? 101 ????? 11000 11", bge, B,
          s->dnpc = ((sword_t)src1 >= (sword_t)src2) ? s->pc + imm : s->dnpc);
  INSTPAT("??????? ????? ????? 110 ????? 11000 11", bltu, B,
          s->dnpc = (src1 < src2) ? s->pc + imm : s->dnpc);
  INSTPAT("??????? ????? ????? 111 ????? 11000 11", bgeu, B,
          s->dnpc = (src1 >= src2) ? s->pc + imm : s->dnpc);
  INSTPAT("??????? ????? ????? 000 ????? 00000 11", lb, I,
          R(rd) = SEXT(BITS(Mr(src1 + imm, 1), 7, 0), 8));
  INSTPAT("??????? ????? ????? 010 ????? 00000 11", lw, I,
          R(rd) = Mr(src1 + imm, 4));
  INSTPAT("??????? ????? ????? 001 ????? 00000 11", lh, I,
          R(rd) = SEXT(BITS(Mr(src1 + imm, 2), 15, 0), 16));
  INSTPAT("??????? ????? ????? 100 ????? 00000 11", lbu, I,
          R(rd) = Mr(src1 + imm, 1));
  INSTPAT("??????? ????? ????? 101 ????? 00000 11", lhu, I,
          R(rd) = Mr(src1 + imm, 2));
  INSTPAT("??????? ????? ????? 000 ????? 01000 11", sb, S,
          Mw(src1 + imm, 1, src2));
  INSTPAT("??????? ????? ????? 001 ????? 01000 11", sh, S,
          Mw(src1 + imm, 2, src2));
  INSTPAT("??????? ????? ????? 010 ????? 01000 11", sw, S,
          Mw(src1 + imm, 4, src2));
  INSTPAT("??????? ????? ????? 000 ????? 00100 11", addi, I,
          R(rd) = src1 + imm);
  INSTPAT("??????? ????? ????? 010 ????? 00100 11", slti, I,
          R(rd) = ((sword_t)src1) < ((sword_t)imm) ? 1 : 0);
  INSTPAT("??????? ????? ????? 011 ????? 00100 11", sltiu, I,
          R(rd) = (src1 < ((word_t)imm)) ? 1 : 0);
  INSTPAT("??????? ????? ????? 100 ????? 00100 11", xori, I,
          R(rd) = src1 ^ imm);
  INSTPAT("??????? ????? ????? 110 ????? 00100 11", ori, I, R(rd) = src1 | imm);
  INSTPAT("??????? ????? ????? 111 ????? 00100 11", andi, I,
          R(rd) = src1 & imm);
  INSTPAT("0000000 ????? ????? 001 ????? 00100 11", slli, I,
          R(rd) = src1 << ((word_t)(imm & 0x1F)));
  INSTPAT("0000000 ????? ????? 101 ????? 00100 11", srli, I,
          R(rd) = src1 >> ((word_t)(imm & 0x1F)));
  INSTPAT("0100000 ????? ????? 101 ????? 00100 11", srai, I,
          R(rd) = (word_t)(((sword_t)src1) >> (imm & 0x1F)));
  INSTPAT("0000000 ????? ????? 000 ????? 01100 11", add, R,
          R(rd) = (word_t)(src1 + src2));
  INSTPAT("0100000 ????? ????? 000 ????? 01100 11", sub, R,
          R(rd) = (word_t)(src1 - src2));
  INSTPAT("0000000 ????? ????? 001 ????? 01100 11", sll, R,
          R(rd) = src1 << (src2 & 0x1F));
  INSTPAT("0000000 ????? ????? 010 ????? 01100 11", slt, R,
          R(rd) = ((sword_t)src1) < ((sword_t)src2) ? 1 : 0);
  INSTPAT("0000000 ????? ????? 011 ????? 01100 11", sltu, R,
          R(rd) = (src1 < src2) ? 1 : 0);
  INSTPAT("0000000 ????? ????? 100 ????? 01100 11", xor, R,
          R(rd) = src1 ^ src2);
  INSTPAT("0000000 ????? ????? 101 ????? 01100 11", srl, R,
          R(rd) = src1 >> (src2 & 0x1F));
  INSTPAT("0100000 ????? ????? 101 ????? 01100 11", sra, R,
          R(rd) = (word_t)(((sword_t)src1) >> (src2 & 0x1F)));
  INSTPAT("0000000 ????? ????? 110 ????? 01100 11", or, R, R(rd) = src1 | src2);
  INSTPAT("0000000 ????? ????? 111 ????? 01100 11", and, R,
          R(rd) = src1 & src2);
  INSTPAT("0000001 ????? ????? 000 ????? 01100 11", mul, R,
          R(rd) = (word_t)(src1 * src2));
  INSTPAT("0000001 ????? ????? 001 ????? 01100 11", mulh, R,
          R(rd) = (word_t)(BITS((SEXT(src1, 32)) * (SEXT(src2, 32)), 63, 32)));
  INSTPAT("0000001 ????? ????? 010 ????? 01100 11", mulhsu, R,
          R(rd) = (word_t)(BITS((SEXT(src1, 32)) * (uint64_t)src2, 63, 32)));
  INSTPAT("0000001 ????? ????? 011 ????? 01100 11", mulhu, R,
          R(rd) = (word_t)(BITS((uint64_t)src1 * (uint64_t)src2, 63, 32)));
  INSTPAT("0000001 ????? ????? 100 ????? 01100 11", div, R,
          R(rd) = _div(src1, src2));
  INSTPAT("0000001 ????? ????? 101 ????? 01100 11", divu, R,
          R(rd) = (src2 != 0) ? src1 / src2 : 0xFFFFFFFF);
  INSTPAT("0000001 ????? ????? 110 ????? 01100 11", rem, R,
          R(rd) = _rem(src1, src2));
  INSTPAT("0000001 ????? ????? 111 ????? 01100 11", remu, R,
          R(rd) = (src2 != 0) ? (word_t)(src1 % src2) : src1);
  INSTPAT("0000000 00001 00000 000 00000 11100 11", ebreak, N,
          NEMUTRAP(s->pc, R(10))); // R(10) is $a0
  INSTPAT("??????? ????? ????? 001 ????? 11100 11", csrrw, I,
          R(rd) = (word_t)CSR(imm), CSR(imm) = src1);
  INSTPAT("??????? ????? ????? 010 ????? 11100 11", csrrs, I,
          R(rd) = (word_t)CSR(imm), CSR(imm) = CSR(imm) | src1);
  INSTPAT("0000000 00000 00000 000 00000 11100 11", ecall, I,
          isa_raise_intr(11, s->pc), s->dnpc = CSR(mtvec_addr));
  INSTPAT("0011000 00010 00000 000 00000 11100 11", mret, I,
          s->dnpc = CSR(mepc_addr));
  INSTPAT("??????? ????? ????? ??? ????? ????? ??", inv, N, INV(s->pc));
  INSTPAT_END();

  R(0) = 0; // reset $zero to 0
  CSR(mstatus_addr) = 0x1800;
  return 0;
}

void print_iringbuf() {
  printf("--- IRINGBUF BEGIN ---\n");

  for (int i = 0; i < 16; i++) {
    if (iringbuf[i][0] == 0)
      continue;
    if (i == (inst_count - 1) % 16) {
      printf("   -->");
    } else {
      printf("      ");
    }
    printf("%s\n", iringbuf[i]);
  }

  printf("--- IRINGBUF END ---\n");
}

int isa_exec_once(Decode *s) {
  s->isa.inst = inst_fetch(&s->snpc, 4);
#ifdef CONFIG_ITRACE
  inst_count++;
  snprintf(iringbuf[(inst_count - 1) % 16], 128, "PC:0x%08x 0x%08x", s->pc,
           s->isa.inst);
#endif
#ifdef CONFIG_FTRACE
  ftrace(s->isa.inst, s->pc);
#endif
  return decode_exec(s);
}
