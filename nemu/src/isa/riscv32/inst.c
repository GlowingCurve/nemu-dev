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

struct InstInf {
  uint32_t pc;
  uint8_t rd;
  uint8_t rs1;
  uint8_t rs2;
  uint32_t imm;
};

typedef struct InstInf InstInf;

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

static inline vaddr_t lui(InstInf inst_inf) {
  R(inst_inf.rd) = inst_inf.imm;
  return inst_inf.pc + 4;
}

static inline vaddr_t auipc(InstInf inst_inf) {
  R(inst_inf.rd) = inst_inf.pc + inst_inf.imm;
  return inst_inf.pc + 4;
}

static inline vaddr_t lb(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = SEXT(BITS(Mr(src1 + inst_inf.imm, 1), 7, 0), 8);
  return inst_inf.pc + 4;
}

static inline vaddr_t lw(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = Mr(src1 + inst_inf.imm, 4);
  return inst_inf.pc + 4;
}

static inline vaddr_t lh(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = SEXT(BITS(Mr(src1 + inst_inf.imm, 2), 15, 0), 16);
  return inst_inf.pc + 4;
}

static inline vaddr_t lbu(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = Mr(src1 + inst_inf.imm, 1);
  return inst_inf.pc + 4;
}

static inline vaddr_t lhu(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = Mr(src1 + inst_inf.imm, 2);
  return inst_inf.pc + 4;
}

static inline vaddr_t sb(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  Mw(src1 + inst_inf.imm, 1, src2);
  return inst_inf.pc + 4;
}

static inline vaddr_t sh(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  Mw(src1 + inst_inf.imm, 2, src2);
  return inst_inf.pc + 4;
}

static inline vaddr_t sw(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  Mw(src1 + inst_inf.imm, 4, src2);
  return inst_inf.pc + 4;
}

static inline vaddr_t addi(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) + inst_inf.imm;
  return inst_inf.pc + 4;
}

static inline vaddr_t slti(InstInf inst_inf) {
  R(inst_inf.rd) = (sword_t)R(inst_inf.rs1) < (sword_t)inst_inf.imm ? 1 : 0;
  return inst_inf.pc + 4;
}

static inline vaddr_t sltiu(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) < (word_t)inst_inf.imm ? 1 : 0;
  return inst_inf.pc + 4;
}

static inline vaddr_t xori(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) ^ inst_inf.imm;
  return inst_inf.pc + 4;
}

static inline vaddr_t ori(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) | inst_inf.imm;
  return inst_inf.pc + 4;
}

static inline vaddr_t andi(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) & inst_inf.imm;
  return inst_inf.pc + 4;
}

static inline vaddr_t slli(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) << (inst_inf.imm & 0x1F);
  return inst_inf.pc + 4;
}

static inline vaddr_t srli(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) >> (inst_inf.imm & 0x1F);
  return inst_inf.pc + 4;
}

static inline vaddr_t srai(InstInf inst_inf) {
  R(inst_inf.rd) = (word_t)((sword_t)R(inst_inf.rs1) >> (inst_inf.imm & 0x1F));
  return inst_inf.pc + 4;
}

static inline vaddr_t add(InstInf inst_inf) {
  R(inst_inf.rd) = (word_t)(R(inst_inf.rs1) + R(inst_inf.rs2));
  return inst_inf.pc + 4;
}

static inline vaddr_t sub(InstInf inst_inf) {
  R(inst_inf.rd) = (word_t)(R(inst_inf.rs1) - R(inst_inf.rs2));
  return inst_inf.pc + 4;
}

static inline vaddr_t sll(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) << (R(inst_inf.rs2) & 0x1F);
  return inst_inf.pc + 4;
}

static inline vaddr_t slt(InstInf inst_inf) {
  R(inst_inf.rd) = (sword_t)R(inst_inf.rs1) < (sword_t)R(inst_inf.rs2) ? 1 : 0;
  return inst_inf.pc + 4;
}

static inline vaddr_t sltu(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) < R(inst_inf.rs2) ? 1 : 0;
  return inst_inf.pc + 4;
}

static inline vaddr_t xor(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) ^ R(inst_inf.rs2);
  return inst_inf.pc + 4;
}

static inline vaddr_t srl(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) >> (R(inst_inf.rs2) & 0x1F);
  return inst_inf.pc + 4;
}

static inline vaddr_t sra(InstInf inst_inf) {
  R(inst_inf.rd) =
      (word_t)((sword_t)R(inst_inf.rs1) >> (R(inst_inf.rs2) & 0x1F));
  return inst_inf.pc + 4;
}

static inline vaddr_t or(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) | R(inst_inf.rs2);
  return inst_inf.pc + 4;
}

static inline vaddr_t and(InstInf inst_inf) {
  R(inst_inf.rd) = R(inst_inf.rs1) & R(inst_inf.rs2);
  return inst_inf.pc + 4;
}

static inline vaddr_t mul(InstInf inst_inf) {
  R(inst_inf.rd) = (word_t)(R(inst_inf.rs1) * R(inst_inf.rs2));
  return inst_inf.pc + 4;
}

static inline vaddr_t mulh(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = (word_t)(BITS((SEXT(src1, 32)) * (SEXT(src2, 32)), 63, 32));
  return inst_inf.pc + 4;
}

static inline vaddr_t mulhsu(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = (word_t)(BITS((SEXT(src1, 32)) * (uint64_t)src2, 63, 32));
  return inst_inf.pc + 4;
}

static inline vaddr_t mulhu(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = (word_t)(BITS((uint64_t)src1 * (uint64_t)src2, 63, 32));
  return inst_inf.pc + 4;
}

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

static inline vaddr_t div_inst(InstInf inst_inf) {
  R(inst_inf.rd) = _div(R(inst_inf.rs1), R(inst_inf.rs2));
  return inst_inf.pc + 4;
}

static inline vaddr_t divu(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = src2 != 0 ? src1 / src2 : 0xFFFFFFFF;
  return inst_inf.pc + 4;
}

static inline vaddr_t rem(InstInf inst_inf) {
  R(inst_inf.rd) = _rem(R(inst_inf.rs1), R(inst_inf.rs2));
  return inst_inf.pc + 4;
}

static inline vaddr_t remu(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = src2 != 0 ? (word_t)(src1 % src2) : src1;
  return inst_inf.pc + 4;
}

static inline vaddr_t csrrw(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = (word_t)CSR(inst_inf.imm);
  CSR(inst_inf.imm) = src1;
  return inst_inf.pc + 4;
}

static inline vaddr_t csrrs(InstInf inst_inf) {
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = (word_t)CSR(inst_inf.imm);
  CSR(inst_inf.imm) = CSR(inst_inf.imm) | src1;
  return inst_inf.pc + 4;
}

static inline vaddr_t jal(InstInf inst_inf) {
  R(inst_inf.rd) = inst_inf.pc + 4;
  return inst_inf.pc + inst_inf.imm;
}

static inline vaddr_t jalr(InstInf inst_inf) {
  vaddr_t dnpc = (R(inst_inf.rs1) + inst_inf.imm) & (~1);
  R(inst_inf.rd) = inst_inf.pc + 4;
  return dnpc;
}

static inline vaddr_t beq(InstInf inst_inf) {
  return R(inst_inf.rs1) == R(inst_inf.rs2) ? inst_inf.pc + inst_inf.imm
                                            : inst_inf.pc + 4;
}

static inline vaddr_t bne(InstInf inst_inf) {
  return R(inst_inf.rs1) != R(inst_inf.rs2) ? inst_inf.pc + inst_inf.imm
                                            : inst_inf.pc + 4;
}

static inline vaddr_t blt(InstInf inst_inf) {
  return (sword_t)R(inst_inf.rs1) < (sword_t)R(inst_inf.rs2)
             ? inst_inf.pc + inst_inf.imm
             : inst_inf.pc + 4;
}

static inline vaddr_t bge(InstInf inst_inf) {
  return (sword_t)R(inst_inf.rs1) >= (sword_t)R(inst_inf.rs2)
             ? inst_inf.pc + inst_inf.imm
             : inst_inf.pc + 4;
}

static inline vaddr_t bltu(InstInf inst_inf) {
  return R(inst_inf.rs1) < R(inst_inf.rs2) ? inst_inf.pc + inst_inf.imm
                                           : inst_inf.pc + 4;
}

static inline vaddr_t bgeu(InstInf inst_inf) {
  return R(inst_inf.rs1) >= R(inst_inf.rs2) ? inst_inf.pc + inst_inf.imm
                                            : inst_inf.pc + 4;
}

static inline vaddr_t ecall(InstInf inst_inf) {
  isa_raise_intr(11, inst_inf.pc);
  return CSR(mtvec_addr);
}

static inline vaddr_t mret(InstInf inst_inf) { return CSR(mepc_addr); }

static inline vaddr_t ebreak(InstInf inst_inf) {
  NEMUTRAP(inst_inf.pc, R(10));
  return inst_inf.pc + 4;
}

static inline vaddr_t invalid(InstInf inst_inf) {
  INV(inst_inf.pc);
  return inst_inf.pc + 4; // shouldn't get here
}

static void decode_operand(Decode *s, vaddr_t pc, int *rd, word_t *src1,
                           word_t *src2, InstInf *inst_inf, word_t *imm,
                           int type) {
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
  inst_inf->rd = *rd;
  inst_inf->imm = *imm;
  inst_inf->rs1 = rs1;
  inst_inf->rs2 = rs2;
  inst_inf->pc = pc;
}

static vaddr_t decode_exec(vaddr_t pc) {
  Decode *s = malloc(sizeof(Decode));
  s->isa.inst = vaddr_ifetch(pc, 4);
  vaddr_t dnpc = pc + 4;

#define INSTPAT_INST(s) ((s)->isa.inst)
#define INSTPAT_MATCH(s, name, type, ... /* execute body */)                   \
  {                                                                            \
    int rd = 0;                                                                \
    word_t src1 = 0, src2 = 0, imm = 0;                                        \
    InstInf inst_inf = {};                                                     \
    decode_operand(s, pc, &rd, &src1, &src2, &inst_inf, &imm,                  \
                   concat(TYPE_, type));                                       \
    __VA_ARGS__;                                                               \
  }

  INSTPAT_START();
  INSTPAT("??????? ????? ????? ??? ????? 01101 11", lui, U,
          dnpc = lui(inst_inf));
  INSTPAT("??????? ????? ????? ??? ????? 00101 11", auipc, U,
          dnpc = auipc(inst_inf));
  INSTPAT("??????? ????? ????? ??? ????? 11011 11", jal, J,
          dnpc = jal(inst_inf));
  INSTPAT("??????? ????? ????? 000 ????? 11001 11", jalr, I,
          dnpc = jalr(inst_inf));
  INSTPAT("??????? ????? ????? 000 ????? 11000 11", beq, B,
          dnpc = beq(inst_inf));
  INSTPAT("??????? ????? ????? 001 ????? 11000 11", bne, B,
          dnpc = bne(inst_inf));
  INSTPAT("??????? ????? ????? 100 ????? 11000 11", blt, B,
          dnpc = blt(inst_inf));
  INSTPAT("??????? ????? ????? 101 ????? 11000 11", bge, B,
          dnpc = bge(inst_inf));
  INSTPAT("??????? ????? ????? 110 ????? 11000 11", bltu, B,
          dnpc = bltu(inst_inf));
  INSTPAT("??????? ????? ????? 111 ????? 11000 11", bgeu, B,
          dnpc = bgeu(inst_inf));
  INSTPAT("??????? ????? ????? 000 ????? 00000 11", lb, I, dnpc = lb(inst_inf));
  INSTPAT("??????? ????? ????? 010 ????? 00000 11", lw, I, dnpc = lw(inst_inf));
  INSTPAT("??????? ????? ????? 001 ????? 00000 11", lh, I, dnpc = lh(inst_inf));
  INSTPAT("??????? ????? ????? 100 ????? 00000 11", lbu, I,
          dnpc = lbu(inst_inf));
  INSTPAT("??????? ????? ????? 101 ????? 00000 11", lhu, I,
          dnpc = lhu(inst_inf));
  INSTPAT("??????? ????? ????? 000 ????? 01000 11", sb, S, dnpc = sb(inst_inf));
  INSTPAT("??????? ????? ????? 001 ????? 01000 11", sh, S, dnpc = sh(inst_inf));
  INSTPAT("??????? ????? ????? 010 ????? 01000 11", sw, S, dnpc = sw(inst_inf));
  INSTPAT("??????? ????? ????? 000 ????? 00100 11", addi, I,
          dnpc = addi(inst_inf));
  INSTPAT("??????? ????? ????? 010 ????? 00100 11", slti, I,
          dnpc = slti(inst_inf));
  INSTPAT("??????? ????? ????? 011 ????? 00100 11", sltiu, I,
          dnpc = sltiu(inst_inf));
  INSTPAT("??????? ????? ????? 100 ????? 00100 11", xori, I,
          dnpc = xori(inst_inf));
  INSTPAT("??????? ????? ????? 110 ????? 00100 11", ori, I,
          dnpc = ori(inst_inf));
  INSTPAT("??????? ????? ????? 111 ????? 00100 11", andi, I,
          dnpc = andi(inst_inf));
  INSTPAT("0000000 ????? ????? 001 ????? 00100 11", slli, I,
          dnpc = slli(inst_inf));
  INSTPAT("0000000 ????? ????? 101 ????? 00100 11", srli, I,
          dnpc = srli(inst_inf));
  INSTPAT("0100000 ????? ????? 101 ????? 00100 11", srai, I,
          dnpc = srai(inst_inf));
  INSTPAT("0000000 ????? ????? 000 ????? 01100 11", add, R,
          dnpc = add(inst_inf));
  INSTPAT("0100000 ????? ????? 000 ????? 01100 11", sub, R,
          dnpc = sub(inst_inf));
  INSTPAT("0000000 ????? ????? 001 ????? 01100 11", sll, R,
          dnpc = sll(inst_inf));
  INSTPAT("0000000 ????? ????? 010 ????? 01100 11", slt, R,
          dnpc = slt(inst_inf));
  INSTPAT("0000000 ????? ????? 011 ????? 01100 11", sltu, R,
          dnpc = sltu(inst_inf));
  INSTPAT("0000000 ????? ????? 100 ????? 01100 11", xor, R,
          dnpc = xor(inst_inf));
  INSTPAT("0000000 ????? ????? 101 ????? 01100 11", srl, R,
          dnpc = srl(inst_inf));
  INSTPAT("0100000 ????? ????? 101 ????? 01100 11", sra, R,
          dnpc = sra(inst_inf));
  INSTPAT("0000000 ????? ????? 110 ????? 01100 11", or, R, dnpc = or(inst_inf));
  INSTPAT("0000000 ????? ????? 111 ????? 01100 11", and, R,
          dnpc = and(inst_inf));
  INSTPAT("0000001 ????? ????? 000 ????? 01100 11", mul, R,
          dnpc = mul(inst_inf));
  INSTPAT("0000001 ????? ????? 001 ????? 01100 11", mulh, R,
          dnpc = mulh(inst_inf));
  INSTPAT("0000001 ????? ????? 010 ????? 01100 11", mulhsu, R,
          dnpc = mulhsu(inst_inf));
  INSTPAT("0000001 ????? ????? 011 ????? 01100 11", mulhu, R,
          dnpc = mulhu(inst_inf));
  INSTPAT("0000001 ????? ????? 100 ????? 01100 11", div, R,
          dnpc = div_inst(inst_inf));
  INSTPAT("0000001 ????? ????? 101 ????? 01100 11", divu, R,
          dnpc = divu(inst_inf));
  INSTPAT("0000001 ????? ????? 110 ????? 01100 11", rem, R,
          dnpc = rem(inst_inf));
  INSTPAT("0000001 ????? ????? 111 ????? 01100 11", remu, R,
          dnpc = remu(inst_inf));
  INSTPAT("0000000 00001 00000 000 00000 11100 11", ebreak, N,
          dnpc = ebreak(inst_inf)); // R(10) is $a0
  INSTPAT("??????? ????? ????? 001 ????? 11100 11", csrrw, I,
          dnpc = csrrw(inst_inf));
  INSTPAT("??????? ????? ????? 010 ????? 11100 11", csrrs, I,
          dnpc = csrrs(inst_inf));
  INSTPAT("0000000 00000 00000 000 00000 11100 11", ecall, I,
          dnpc = ecall(inst_inf));
  INSTPAT("0011000 00010 00000 000 00000 11100 11", mret, I,
          dnpc = mret(inst_inf));
  INSTPAT("??????? ????? ????? ??? ????? ????? ??", inv, N,
          dnpc = invalid(inst_inf));
  INSTPAT_END();

  R(0) = 0; // reset $zero to 0
  CSR(mstatus_addr) = 0x1800;
  return dnpc;
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

vaddr_t isa_exec_once(vaddr_t pc) {
#ifdef CONFIG_ITRACE
  inst_count++;
  snprintf(iringbuf[(inst_count - 1) % 16], 128, "PC:0x%08x 0x%08x", s->pc,
           s->isa.inst);
#endif
#ifdef CONFIG_FTRACE
  ftrace(s->isa.inst, s->pc);
#endif
  return decode_exec(pc);
}
