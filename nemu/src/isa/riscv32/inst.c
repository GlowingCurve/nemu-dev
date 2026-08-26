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

enum {
  OP_INVALID,
  OP_LUI,
  OP_AUIPC,
  OP_JAL,
  OP_JALR,
  OP_BEQ,
  OP_BNE,
  OP_BLT,
  OP_BGE,
  OP_BLTU,
  OP_BGEU,
  OP_LB,
  OP_LW,
  OP_LH,
  OP_LBU,
  OP_LHU,
  OP_SB,
  OP_SH,
  OP_SW,
  OP_ADDI,
  OP_SLTI,
  OP_SLTIU,
  OP_XORI,
  OP_ORI,
  OP_ANDI,
  OP_SLLI,
  OP_SRLI,
  OP_SRAI,
  OP_ADD,
  OP_SUB,
  OP_SLL,
  OP_SLT,
  OP_SLTU,
  OP_XOR,
  OP_SRL,
  OP_SRA,
  OP_OR,
  OP_AND,
  OP_MUL,
  OP_MULH,
  OP_MULHSU,
  OP_MULHU,
  OP_DIV,
  OP_DIVU,
  OP_REM,
  OP_REMU,
  OP_EBREAK,
  OP_CSRRW,
  OP_CSRRS,
  OP_ECALL,
  OP_MRET,
};

struct InstInf {
  uint32_t pc;
  uint8_t rd;
  uint8_t rs1;
  uint8_t rs2;
  uint32_t imm;
};

typedef struct InstInf InstInf;

struct Inst {
  InstInf inst_inf;
  uint8_t opcode;
};

typedef struct Inst Inst;

Inst inst_cache[1024] = {};

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

static Inst decode(vaddr_t pc) {
  Decode *s = malloc(sizeof(Decode));
  s->isa.inst = vaddr_ifetch(pc, 4);

  Inst inst;
  InstInf inst_inf = {};
  uint8_t opcode = OP_INVALID;

#define INSTPAT_INST(s) ((s)->isa.inst)
#define INSTPAT_MATCH(s, name, type, ... /* execute body */)                   \
  {                                                                            \
    int rd = 0;                                                                \
    word_t src1 = 0, src2 = 0, imm = 0;                                        \
    decode_operand(s, pc, &rd, &src1, &src2, &inst_inf, &imm,                  \
                   concat(TYPE_, type));                                       \
    __VA_ARGS__;                                                               \
  }

  INSTPAT_START();
  INSTPAT("??????? ????? ????? ??? ????? 01101 11", lui, U, opcode = OP_LUI);
  INSTPAT("??????? ????? ????? ??? ????? 00101 11", auipc, U,
          opcode = OP_AUIPC);
  INSTPAT("??????? ????? ????? ??? ????? 11011 11", jal, J, opcode = OP_JAL);
  INSTPAT("??????? ????? ????? 000 ????? 11001 11", jalr, I, opcode = OP_JALR);
  INSTPAT("??????? ????? ????? 000 ????? 11000 11", beq, B, opcode = OP_BEQ);
  INSTPAT("??????? ????? ????? 001 ????? 11000 11", bne, B, opcode = OP_BNE);
  INSTPAT("??????? ????? ????? 100 ????? 11000 11", blt, B, opcode = OP_BLT);
  INSTPAT("??????? ????? ????? 101 ????? 11000 11", bge, B, opcode = OP_BGE);
  INSTPAT("??????? ????? ????? 110 ????? 11000 11", bltu, B, opcode = OP_BLTU);
  INSTPAT("??????? ????? ????? 111 ????? 11000 11", bgeu, B, opcode = OP_BGEU);
  INSTPAT("??????? ????? ????? 000 ????? 00000 11", lb, I, opcode = OP_LB);
  INSTPAT("??????? ????? ????? 010 ????? 00000 11", lw, I, opcode = OP_LW);
  INSTPAT("??????? ????? ????? 001 ????? 00000 11", lh, I, opcode = OP_LH);
  INSTPAT("??????? ????? ????? 100 ????? 00000 11", lbu, I, opcode = OP_LBU);
  INSTPAT("??????? ????? ????? 101 ????? 00000 11", lhu, I, opcode = OP_LHU);
  INSTPAT("??????? ????? ????? 000 ????? 01000 11", sb, S, opcode = OP_SB);
  INSTPAT("??????? ????? ????? 001 ????? 01000 11", sh, S, opcode = OP_SH);
  INSTPAT("??????? ????? ????? 010 ????? 01000 11", sw, S, opcode = OP_SW);
  INSTPAT("??????? ????? ????? 000 ????? 00100 11", addi, I, opcode = OP_ADDI);
  INSTPAT("??????? ????? ????? 010 ????? 00100 11", slti, I, opcode = OP_SLTI);
  INSTPAT("??????? ????? ????? 011 ????? 00100 11", sltiu, I,
          opcode = OP_SLTIU);
  INSTPAT("??????? ????? ????? 100 ????? 00100 11", xori, I, opcode = OP_XORI);
  INSTPAT("??????? ????? ????? 110 ????? 00100 11", ori, I, opcode = OP_ORI);
  INSTPAT("??????? ????? ????? 111 ????? 00100 11", andi, I, opcode = OP_ANDI);
  INSTPAT("0000000 ????? ????? 001 ????? 00100 11", slli, I, opcode = OP_SLLI);
  INSTPAT("0000000 ????? ????? 101 ????? 00100 11", srli, I, opcode = OP_SRLI);
  INSTPAT("0100000 ????? ????? 101 ????? 00100 11", srai, I, opcode = OP_SRAI);
  INSTPAT("0000000 ????? ????? 000 ????? 01100 11", add, R, opcode = OP_ADD);
  INSTPAT("0100000 ????? ????? 000 ????? 01100 11", sub, R, opcode = OP_SUB);
  INSTPAT("0000000 ????? ????? 001 ????? 01100 11", sll, R, opcode = OP_SLL);
  INSTPAT("0000000 ????? ????? 010 ????? 01100 11", slt, R, opcode = OP_SLT);
  INSTPAT("0000000 ????? ????? 011 ????? 01100 11", sltu, R, opcode = OP_SLTU);
  INSTPAT("0000000 ????? ????? 100 ????? 01100 11", xor, R, opcode = OP_XOR);
  INSTPAT("0000000 ????? ????? 101 ????? 01100 11", srl, R, opcode = OP_SRL);
  INSTPAT("0100000 ????? ????? 101 ????? 01100 11", sra, R, opcode = OP_SRA);
  INSTPAT("0000000 ????? ????? 110 ????? 01100 11", or, R, opcode = OP_OR);
  INSTPAT("0000000 ????? ????? 111 ????? 01100 11", and, R, opcode = OP_AND);
  INSTPAT("0000001 ????? ????? 000 ????? 01100 11", mul, R, opcode = OP_MUL);
  INSTPAT("0000001 ????? ????? 001 ????? 01100 11", mulh, R, opcode = OP_MULH);
  INSTPAT("0000001 ????? ????? 010 ????? 01100 11", mulhsu, R,
          opcode = OP_MULHSU);
  INSTPAT("0000001 ????? ????? 011 ????? 01100 11", mulhu, R,
          opcode = OP_MULHU);
  INSTPAT("0000001 ????? ????? 100 ????? 01100 11", div, R, opcode = OP_DIV);
  INSTPAT("0000001 ????? ????? 101 ????? 01100 11", divu, R, opcode = OP_DIVU);
  INSTPAT("0000001 ????? ????? 110 ????? 01100 11", rem, R, opcode = OP_REM);
  INSTPAT("0000001 ????? ????? 111 ????? 01100 11", remu, R, opcode = OP_REMU);
  INSTPAT("0000000 00001 00000 000 00000 11100 11", ebreak, N,
          opcode = OP_EBREAK); // R(10) is $a0
  INSTPAT("??????? ????? ????? 001 ????? 11100 11", csrrw, I,
          opcode = OP_CSRRW);
  INSTPAT("??????? ????? ????? 010 ????? 11100 11", csrrs, I,
          opcode = OP_CSRRS);
  INSTPAT("0000000 00000 00000 000 00000 11100 11", ecall, I,
          opcode = OP_ECALL);
  INSTPAT("0011000 00010 00000 000 00000 11100 11", mret, I, opcode = OP_MRET);
  INSTPAT("??????? ????? ????? ??? ????? ????? ??", inv, N,
          opcode = OP_INVALID);
  INSTPAT_END();

  inst.inst_inf = inst_inf;
  inst.opcode = opcode;
  free(s);

  return inst;
}

static vaddr_t switch_execution(Inst *inst) {
  switch (inst->opcode) {
  case OP_LUI:
    return lui(inst->inst_inf);
  case OP_AUIPC:
    return auipc(inst->inst_inf);
  case OP_JAL:
    return jal(inst->inst_inf);
  case OP_JALR:
    return jalr(inst->inst_inf);
  case OP_BEQ:
    return beq(inst->inst_inf);
  case OP_BNE:
    return bne(inst->inst_inf);
  case OP_BLT:
    return blt(inst->inst_inf);
  case OP_BGE:
    return bge(inst->inst_inf);
  case OP_BLTU:
    return bltu(inst->inst_inf);
  case OP_BGEU:
    return bgeu(inst->inst_inf);
  case OP_LB:
    return lb(inst->inst_inf);
  case OP_LW:
    return lw(inst->inst_inf);
  case OP_LH:
    return lh(inst->inst_inf);
  case OP_LBU:
    return lbu(inst->inst_inf);
  case OP_LHU:
    return lhu(inst->inst_inf);
  case OP_SB:
    return sb(inst->inst_inf);
  case OP_SH:
    return sh(inst->inst_inf);
  case OP_SW:
    return sw(inst->inst_inf);
  case OP_ADDI:
    return addi(inst->inst_inf);
  case OP_SLTI:
    return slti(inst->inst_inf);
  case OP_SLTIU:
    return sltiu(inst->inst_inf);
  case OP_XORI:
    return xori(inst->inst_inf);
  case OP_ORI:
    return ori(inst->inst_inf);
  case OP_ANDI:
    return andi(inst->inst_inf);
  case OP_SLLI:
    return slli(inst->inst_inf);
  case OP_SRLI:
    return srli(inst->inst_inf);
  case OP_SRAI:
    return srai(inst->inst_inf);
  case OP_ADD:
    return add(inst->inst_inf);
  case OP_SUB:
    return sub(inst->inst_inf);
  case OP_SLL:
    return sll(inst->inst_inf);
  case OP_SLT:
    return slt(inst->inst_inf);
  case OP_SLTU:
    return sltu(inst->inst_inf);
  case OP_XOR:
    return xor(inst->inst_inf);
  case OP_SRL:
    return srl(inst->inst_inf);
  case OP_SRA:
    return sra(inst->inst_inf);
  case OP_OR:
    return or(inst->inst_inf);
  case OP_AND:
    return and(inst->inst_inf);
  case OP_MUL:
    return mul(inst->inst_inf);
  case OP_MULH:
    return mulh(inst->inst_inf);
  case OP_MULHSU:
    return mulhsu(inst->inst_inf);
  case OP_MULHU:
    return mulhu(inst->inst_inf);
  case OP_DIV:
    return div_inst(inst->inst_inf);
  case OP_DIVU:
    return divu(inst->inst_inf);
  case OP_REM:
    return rem(inst->inst_inf);
  case OP_REMU:
    return remu(inst->inst_inf);
  case OP_EBREAK:
    return ebreak(inst->inst_inf);
  case OP_CSRRW:
    return csrrw(inst->inst_inf);
  case OP_CSRRS:
    return csrrs(inst->inst_inf);
  case OP_ECALL:
    return ecall(inst->inst_inf);
  case OP_MRET:
    return mret(inst->inst_inf);
  case OP_INVALID:
  default:
    return invalid(inst->inst_inf);
  }
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

bool is_hitcache(vaddr_t pc) {
  if ((inst_cache[(pc & 0xFFF) >> 2].inst_inf.pc) == pc) {
    return true;
  }
  return false;
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
  Inst *inst = &inst_cache[(pc & 0xFFF) >> 2];

  if (!is_hitcache(pc)) {
    *inst = decode(pc);
  }
  vaddr_t dnpc = switch_execution(inst);
  R(0) = 0;
  return dnpc;
}
