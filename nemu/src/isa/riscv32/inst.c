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
  OP_END,
  NUM_OPS,
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
  void *code;
};

typedef struct Inst Inst;

#define MAX_INST_LENGTH 32

struct BasicBlock {
  uint32_t pc;
  uint32_t count;
  void *entry;
  struct BasicBlock *taken;
  struct BasicBlock *fallthrough;
  Inst insts[MAX_INST_LENGTH + 1];
};

typedef struct BasicBlock BasicBlock;

BasicBlock basicblock_cache[1024] = {};

static void *op_table[NUM_OPS] = {};
static bool op_table_initialized = false;

extern uint64_t g_nr_guest_inst;

void basicblock_cache_refill(vaddr_t pc);

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
    imm = SEXT(BITS(i, 31, 20), 12);                                           \
  } while (0)
#define immU()                                                                 \
  do {                                                                         \
    imm = SEXT(BITS(i, 31, 12), 20) << 12;                                     \
  } while (0)
#define immS()                                                                 \
  do {                                                                         \
    imm = (SEXT(BITS(i, 31, 25), 7) << 5) | BITS(i, 11, 7);                    \
  } while (0)
#define immJ()                                                                 \
  do {                                                                         \
    imm = SEXT(((BITS(i, 31, 31) << 20) + (BITS(i, 19, 12) << 12) +            \
                (BITS(i, 20, 20) << 11) + (BITS(i, 30, 21) << 1)),             \
               21);                                                            \
  } while (0)
#define immB()                                                                 \
  do {                                                                         \
    imm = SEXT(((BITS(i, 31, 31) << 12) + (BITS(i, 30, 25) << 5) +             \
                (BITS(i, 11, 8) << 1) + (BITS(i, 7, 7) << 11)),                \
               13);                                                            \
  } while (0)
#define csrR()                                                                 \
  do {                                                                         \
    csr_t = CSR(imm);                                                          \
  } while (0)

static inline __attribute__((always_inline)) word_t _div(word_t src1,
                                                         word_t src2) {
  if (src1 == 0x80000000 && src2 == 0xFFFFFFFF)
    return 0x80000000;
  if (src2 == 0)
    return 0xFFFFFFFF;
  else
    return ((sword_t)src1) / ((sword_t)src2);
}

static inline __attribute__((always_inline)) word_t _rem(word_t src1,
                                                         word_t src2) {
  if (src1 == 0x80000000 && src2 == 0xFFFFFFFF)
    return 0;
  if (src2 == 0)
    return src1;
  else
    return ((sword_t)src1) % ((sword_t)src2);
}

static void decode_operand(Decode *s, vaddr_t pc, InstInf *inst_inf, int type) {
  uint32_t i = s->isa.inst;
  inst_inf->rs1 = BITS(i, 19, 15);
  inst_inf->rs2 = BITS(i, 24, 20);
  uint8_t rd = BITS(i, 11, 7);
  if (rd == 0) {
    rd = 32;
  }
  inst_inf->rd = rd;
  inst_inf->pc = pc;
  uint32_t imm = 0;
  switch (type) {
  case TYPE_I:
    immI();
    break;
  case TYPE_U:
    immU();
    break;
  case TYPE_S:
    immS();
    break;
  case TYPE_N:
    break;
  case TYPE_J:
    immJ();
    break;
  case TYPE_R:
    break;
  case TYPE_B:
    immB();
    break;
  default:
    panic("unsupported type = %d", type);
  }
  inst_inf->imm = imm;
}

static Inst decode(vaddr_t pc) {
  Decode root = {};
  Decode *s = &root;
  s->isa.inst = vaddr_ifetch(pc, 4);

  Inst inst;
  InstInf inst_inf = {};
  uint8_t opcode = OP_INVALID;

#define INSTPAT_INST(s) ((s)->isa.inst)
#define INSTPAT_MATCH(s, name, type, ... /* execute body */)                   \
  {                                                                            \
    decode_operand(s, pc, &inst_inf, concat(TYPE_, type));                     \
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
  inst.code = op_table[opcode];

  return inst;
}

static __attribute__((noinline, cold)) BasicBlock *
basicblock_cache_resolve(BasicBlock *source, BasicBlock **successor,
                         vaddr_t pc) {
  vaddr_t source_pc = source->pc;
  uint32_t index = (pc & 0xFFF) >> 2;
  BasicBlock *target = &basicblock_cache[index];

  if (unlikely(target->pc != pc)) {
    basicblock_cache_refill(pc);
  }

  // A same-index refill overwrites source and its successor fields in place.
  if (likely(source->pc == source_pc)) {
    *successor = target;
  }
  return target;
}

#if defined(__GNUC__) && !defined(__clang__)
#define THREADED_EXEC_ATTR                                                     \
  __attribute__((noinline, noclone,                                             \
                 optimize("no-crossjumping", "no-gcse",                       \
                          "no-tree-tail-merge")))
#elif defined(__clang__)
#define THREADED_EXEC_ATTR __attribute__((noinline))
#else
#define THREADED_EXEC_ATTR
#endif

THREADED_EXEC_ATTR
vaddr_t basicblock_cache_execute(BasicBlock *basicblock) {
  if (unlikely(basicblock == NULL)) {
    op_table[OP_INVALID] = &&op_invalid;
    op_table[OP_LUI] = &&op_lui;
    op_table[OP_AUIPC] = &&op_auipc;
    op_table[OP_JAL] = &&op_jal;
    op_table[OP_JALR] = &&op_jalr;
    op_table[OP_BEQ] = &&op_beq;
    op_table[OP_BNE] = &&op_bne;
    op_table[OP_BLT] = &&op_blt;
    op_table[OP_BGE] = &&op_bge;
    op_table[OP_BLTU] = &&op_bltu;
    op_table[OP_BGEU] = &&op_bgeu;
    op_table[OP_LB] = &&op_lb;
    op_table[OP_LW] = &&op_lw;
    op_table[OP_LH] = &&op_lh;
    op_table[OP_LBU] = &&op_lbu;
    op_table[OP_LHU] = &&op_lhu;
    op_table[OP_SB] = &&op_sb;
    op_table[OP_SH] = &&op_sh;
    op_table[OP_SW] = &&op_sw;
    op_table[OP_ADDI] = &&op_addi;
    op_table[OP_SLTI] = &&op_slti;
    op_table[OP_SLTIU] = &&op_sltiu;
    op_table[OP_XORI] = &&op_xori;
    op_table[OP_ORI] = &&op_ori;
    op_table[OP_ANDI] = &&op_andi;
    op_table[OP_SLLI] = &&op_slli;
    op_table[OP_SRLI] = &&op_srli;
    op_table[OP_SRAI] = &&op_srai;
    op_table[OP_ADD] = &&op_add;
    op_table[OP_SUB] = &&op_sub;
    op_table[OP_SLL] = &&op_sll;
    op_table[OP_SLT] = &&op_slt;
    op_table[OP_SLTU] = &&op_sltu;
    op_table[OP_XOR] = &&op_xor;
    op_table[OP_SRL] = &&op_srl;
    op_table[OP_SRA] = &&op_sra;
    op_table[OP_OR] = &&op_or;
    op_table[OP_AND] = &&op_and;
    op_table[OP_MUL] = &&op_mul;
    op_table[OP_MULH] = &&op_mulh;
    op_table[OP_MULHSU] = &&op_mulhsu;
    op_table[OP_MULHU] = &&op_mulhu;
    op_table[OP_DIV] = &&op_div;
    op_table[OP_DIVU] = &&op_divu;
    op_table[OP_REM] = &&op_rem;
    op_table[OP_REMU] = &&op_remu;
    op_table[OP_EBREAK] = &&op_ebreak;
    op_table[OP_CSRRW] = &&op_csrrw;
    op_table[OP_CSRRS] = &&op_csrrs;
    op_table[OP_ECALL] = &&op_ecall;
    op_table[OP_MRET] = &&op_mret;
    op_table[OP_END] = &&op_end;
    op_table_initialized = true;
    return 0;
  }

  Inst *p;
  vaddr_t next_pc;
  BasicBlock **successor;

#define DISPATCH()                                                             \
  do {                                                                         \
    p++;                                                                       \
    goto *p->code;                                                             \
  } while (0)

  goto block_entry;

op_lui: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = inst_inf.imm;
  DISPATCH();
}

op_auipc: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = inst_inf.pc + inst_inf.imm;
  DISPATCH();
}

op_jal: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = inst_inf.pc + 4;
  next_pc = inst_inf.pc + inst_inf.imm;
  successor = &basicblock->taken;
  goto block_dispatch;
}

op_jalr: {
  InstInf inst_inf = p->inst_inf;
  vaddr_t dnpc = (R(inst_inf.rs1) + inst_inf.imm) & (~1);
  R(inst_inf.rd) = inst_inf.pc + 4;
  next_pc = dnpc;
  successor = &basicblock->taken;
  goto block_dispatch;
}

op_beq: {
  InstInf inst_inf = p->inst_inf;
  if (R(inst_inf.rs1) == R(inst_inf.rs2)) {
    next_pc = inst_inf.pc + inst_inf.imm;
    successor = &basicblock->taken;
  } else {
    next_pc = inst_inf.pc + 4;
    successor = &basicblock->fallthrough;
  }
  goto block_dispatch;
}

op_bne: {
  InstInf inst_inf = p->inst_inf;
  if (R(inst_inf.rs1) != R(inst_inf.rs2)) {
    next_pc = inst_inf.pc + inst_inf.imm;
    successor = &basicblock->taken;
  } else {
    next_pc = inst_inf.pc + 4;
    successor = &basicblock->fallthrough;
  }
  goto block_dispatch;
}

op_blt: {
  InstInf inst_inf = p->inst_inf;
  if ((sword_t)R(inst_inf.rs1) < (sword_t)R(inst_inf.rs2)) {
    next_pc = inst_inf.pc + inst_inf.imm;
    successor = &basicblock->taken;
  } else {
    next_pc = inst_inf.pc + 4;
    successor = &basicblock->fallthrough;
  }
  goto block_dispatch;
}

op_bge: {
  InstInf inst_inf = p->inst_inf;
  if ((sword_t)R(inst_inf.rs1) >= (sword_t)R(inst_inf.rs2)) {
    next_pc = inst_inf.pc + inst_inf.imm;
    successor = &basicblock->taken;
  } else {
    next_pc = inst_inf.pc + 4;
    successor = &basicblock->fallthrough;
  }
  goto block_dispatch;
}

op_bltu: {
  InstInf inst_inf = p->inst_inf;
  if (R(inst_inf.rs1) < R(inst_inf.rs2)) {
    next_pc = inst_inf.pc + inst_inf.imm;
    successor = &basicblock->taken;
  } else {
    next_pc = inst_inf.pc + 4;
    successor = &basicblock->fallthrough;
  }
  goto block_dispatch;
}

op_bgeu: {
  InstInf inst_inf = p->inst_inf;
  if (R(inst_inf.rs1) >= R(inst_inf.rs2)) {
    next_pc = inst_inf.pc + inst_inf.imm;
    successor = &basicblock->taken;
  } else {
    next_pc = inst_inf.pc + 4;
    successor = &basicblock->fallthrough;
  }
  goto block_dispatch;
}

op_lb: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = SEXT(BITS(Mr(src1 + inst_inf.imm, 1), 7, 0), 8);
  DISPATCH();
}

op_lw: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = Mr(src1 + inst_inf.imm, 4);
  DISPATCH();
}

op_lh: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = SEXT(BITS(Mr(src1 + inst_inf.imm, 2), 15, 0), 16);
  DISPATCH();
}

op_lbu: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = Mr(src1 + inst_inf.imm, 1);
  DISPATCH();
}

op_lhu: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = Mr(src1 + inst_inf.imm, 2);
  DISPATCH();
}

op_sb: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  Mw(src1 + inst_inf.imm, 1, src2);
  DISPATCH();
}

op_sh: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  Mw(src1 + inst_inf.imm, 2, src2);
  DISPATCH();
}

op_sw: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  Mw(src1 + inst_inf.imm, 4, src2);
  DISPATCH();
}

op_addi: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) + inst_inf.imm;
  DISPATCH();
}

op_slti: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = (sword_t)R(inst_inf.rs1) < (sword_t)inst_inf.imm ? 1 : 0;
  DISPATCH();
}

op_sltiu: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) < (word_t)inst_inf.imm ? 1 : 0;
  DISPATCH();
}

op_xori: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) ^ inst_inf.imm;
  DISPATCH();
}

op_ori: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) | inst_inf.imm;
  DISPATCH();
}

op_andi: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) & inst_inf.imm;
  DISPATCH();
}

op_slli: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) << (inst_inf.imm & 0x1F);
  DISPATCH();
}

op_srli: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) >> (inst_inf.imm & 0x1F);
  DISPATCH();
}

op_srai: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = (word_t)((sword_t)R(inst_inf.rs1) >> (inst_inf.imm & 0x1F));
  DISPATCH();
}

op_add: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = (word_t)(R(inst_inf.rs1) + R(inst_inf.rs2));
  DISPATCH();
}

op_sub: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = (word_t)(R(inst_inf.rs1) - R(inst_inf.rs2));
  DISPATCH();
}

op_sll: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) << (R(inst_inf.rs2) & 0x1F);
  DISPATCH();
}

op_slt: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = (sword_t)R(inst_inf.rs1) < (sword_t)R(inst_inf.rs2) ? 1 : 0;
  DISPATCH();
}

op_sltu: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) < R(inst_inf.rs2) ? 1 : 0;
  DISPATCH();
}

op_xor: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) ^ R(inst_inf.rs2);
  DISPATCH();
}

op_srl: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) >> (R(inst_inf.rs2) & 0x1F);
  DISPATCH();
}

op_sra: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) =
      (word_t)((sword_t)R(inst_inf.rs1) >> (R(inst_inf.rs2) & 0x1F));
  DISPATCH();
}

op_or: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) | R(inst_inf.rs2);
  DISPATCH();
}

op_and: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = R(inst_inf.rs1) & R(inst_inf.rs2);
  DISPATCH();
}

op_mul: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = (word_t)(R(inst_inf.rs1) * R(inst_inf.rs2));
  DISPATCH();
}

op_mulh: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = (word_t)(BITS((SEXT(src1, 32)) * (SEXT(src2, 32)), 63, 32));
  DISPATCH();
}

op_mulhsu: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = (word_t)(BITS((SEXT(src1, 32)) * (uint64_t)src2, 63, 32));
  DISPATCH();
}

op_mulhu: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = (word_t)(BITS((uint64_t)src1 * (uint64_t)src2, 63, 32));
  DISPATCH();
}

op_div: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = _div(R(inst_inf.rs1), R(inst_inf.rs2));
  DISPATCH();
}

op_divu: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = src2 != 0 ? src1 / src2 : 0xFFFFFFFF;
  DISPATCH();
}

op_rem: {
  InstInf inst_inf = p->inst_inf;
  R(inst_inf.rd) = _rem(R(inst_inf.rs1), R(inst_inf.rs2));
  DISPATCH();
}

op_remu: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  word_t src2 = R(inst_inf.rs2);
  R(inst_inf.rd) = src2 != 0 ? (word_t)(src1 % src2) : src1;
  DISPATCH();
}

op_ebreak: {
  InstInf inst_inf = p->inst_inf;
  NEMUTRAP(inst_inf.pc, R(10));
  next_pc = inst_inf.pc + 4;
  successor = &basicblock->taken;
  goto block_dispatch;
}

op_csrrw: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = (word_t)CSR(inst_inf.imm);
  CSR(inst_inf.imm) = src1;
  DISPATCH();
}

op_csrrs: {
  InstInf inst_inf = p->inst_inf;
  word_t src1 = R(inst_inf.rs1);
  R(inst_inf.rd) = (word_t)CSR(inst_inf.imm);
  CSR(inst_inf.imm) = CSR(inst_inf.imm) | src1;
  DISPATCH();
}

op_ecall: {
  InstInf inst_inf = p->inst_inf;
  isa_raise_intr(11, inst_inf.pc);
  next_pc = CSR(mtvec_addr);
  successor = &basicblock->taken;
  goto block_dispatch;
}

op_mret:
  next_pc = CSR(mepc_addr);
  successor = &basicblock->taken;
  goto block_dispatch;

op_invalid: {
  InstInf inst_inf = p->inst_inf;
  INV(inst_inf.pc);
  DISPATCH();
}

op_end:
  next_pc = p->inst_inf.pc;
  successor = &basicblock->fallthrough;
  goto block_dispatch;

block_dispatch: {
  cpu.pc = next_pc;
  if (unlikely(nemu_state.state != NEMU_RUNNING)) {
    return next_pc;
  }

  BasicBlock *cached = *successor;
  if (unlikely(cached->pc != next_pc)) {
    goto successor_miss;
  }
  basicblock = cached;
  g_nr_guest_inst += cached->count;
  p = cached->insts;
  goto *cached->entry;

block_entry:
  g_nr_guest_inst += basicblock->count;
  p = basicblock->insts;
  goto *basicblock->entry;

successor_miss:
  basicblock = basicblock_cache_resolve(basicblock, successor, next_pc);
  goto block_entry;
}

#undef DISPATCH
}

#undef THREADED_EXEC_ATTR

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
  if ((basicblock_cache[(pc & 0xFFF) >> 2].pc) == pc) {
    return true;
  }
  return false;
}

bool is_terminate(Inst inst) {
  switch (inst.opcode) {
  case OP_JAL:
  case OP_JALR:
  case OP_BEQ:
  case OP_BNE:
  case OP_BLT:
  case OP_BGE:
  case OP_BLTU:
  case OP_BGEU:
  case OP_ECALL:
  case OP_EBREAK:
  case OP_MRET:
    return true;
  default:
    return false;
  }
}

void basicblock_cache_refill(vaddr_t pc) {
  unsigned int index = (pc & 0xFFF) >> 2;
  unsigned int count = 0;

  if (!op_table_initialized) {
    basicblock_cache_execute(NULL);
  }

  basicblock_cache[index].pc = pc;
  // Cache entries never move, so self is a safe non-NULL cold sentinel.
  basicblock_cache[index].taken = &basicblock_cache[index];
  basicblock_cache[index].fallthrough = &basicblock_cache[index];
  basicblock_cache[index].insts[count] = decode(pc);
  basicblock_cache[index].entry = basicblock_cache[index].insts[0].code;

  while ((count < MAX_INST_LENGTH - 1) &&
         (!is_terminate(basicblock_cache[index].insts[count]))) {
    count++;
    pc += 4;
    basicblock_cache[index].insts[count] = decode(pc);
  }

  if ((count == MAX_INST_LENGTH - 1) &&
      (!is_terminate(basicblock_cache[index].insts[count]))) {
    Inst *end = &basicblock_cache[index].insts[MAX_INST_LENGTH];
    *end = (Inst){};
    end->inst_inf.pc = pc + 4;
    end->opcode = OP_END;
    end->code = op_table[OP_END];
  }

  basicblock_cache[index].count = count + 1;
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

  uint32_t index = (pc & 0xFFF) >> 2;

  if (!is_hitcache(pc)) {
    basicblock_cache_refill(pc);
  }
  vaddr_t dnpc = basicblock_cache_execute(&basicblock_cache[index]);
  return dnpc;
}
