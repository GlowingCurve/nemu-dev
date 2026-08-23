#include "debug.h"
#include <common.h>
#include <elf.h>
#include <endian.h>
#include <isa.h>
#include <macro.h>
#include <stdint.h>
#include <stdio.h>

static inline int check_reg_idx(int idx) {
  IFDEF(CONFIG_RT_CHECK, assert(idx >= 0 && idx < MUXDEF(CONFIG_RVE, 16, 32)));
  return idx;
}

#define gpr(idx) (cpu.gpr[check_reg_idx(idx)])

#define NR_MAX 8192
#define CALL_STACK_MAX 512

SYM_FUNC sym_func[NR_MAX] = {};
int sym_func_count = 0;

word_t call_stack[CALL_STACK_MAX] = {};
int call_stack_tail = 0;

#define immJ(inst)                                                             \
  SEXT(((BITS(inst, 31, 31) << 20) + (BITS(inst, 19, 12) << 12) +              \
        (BITS(inst, 20, 20) << 11) + (BITS(inst, 30, 21) << 1)),               \
       21)

static word_t get_func_indx(word_t address) {
  for (int i = 0; i < sym_func_count; i++) {
    if (sym_func[i].addr <= address &&
        address < sym_func[i].addr + sym_func[i].size) {
      return i;
    }
  }
  Assert(0, "Invalid address:0x%08x to get!", address);
  return 0;
}

static word_t parse(word_t inst, word_t pc) {
  switch (inst & 0xFFF) {
  case 0xE7:
    return (SEXT(BITS(inst, 31, 20), 12) + gpr(BITS(inst, 19, 15))) &
           0xFFFFFFFE;

  case 0xEF:
    return pc + immJ(inst);

  default:
    Assert(0, "Invalid inst in ftrace");
  }
  return 0;
}

void print_syms() {
  for (int i = 0; i < sym_func_count; i++) {
    printf("[FTRACE]: %d %s %08x 0x%08x\n", i, sym_func[i].name,
           sym_func[i].size, sym_func[i].addr);
  }
}

void ftrace(word_t inst, word_t pc) {
  for (int i = 0; i < sym_func_count; i++) {
    if (sym_func[i].addr <= pc && pc < sym_func[i].addr + sym_func[i].size) {
      if ((inst & 0xFFF) == 0xE7 || (inst & 0xFFF) == 0xEF) {
        word_t address = parse(inst, pc);
        call_stack[call_stack_tail] = pc + 0x4u;
        for (int j = 0; j < 2 * call_stack_tail; j++)
          printf(" ");
        call_stack_tail++;
        printf("[FTRACE]: PC:0x%08x call: From %s To %s@0x%08x\n", pc,
               sym_func[i].name, sym_func[get_func_indx(address)].name,
               address);
        return;
      }
      if (inst == 0x00008067) {
        for (int j = 0; j < 2 * (call_stack_tail - 1); j++)
          printf(" ");
        printf("[FTRACE]: PC:0x%08x ret: From %s To %s\n", pc, sym_func[i].name,
               sym_func[get_func_indx(call_stack[call_stack_tail - 1])].name);
        call_stack_tail--;
        return;
      }
    }
  }
}

void init_ftrace(char *img) {
  size_t len = strlen(img);
  img[len - 1] = 'f';
  img[len - 2] = 'l';
  img[len - 3] = 'e';

  Assert(img != NULL, "need an elf!\n");

  FILE *fp = fopen(img, "rb");
  Assert(fp != NULL, "can't open elf\n");

  rewind(fp);
  Elf32_Ehdr ehdr;
  if (fread(&ehdr, 1, sizeof(ehdr), fp) != sizeof(ehdr)) {
    Assert(0, "failed to read elf header\n");
  }

  if (memcmp(ehdr.e_ident, ELFMAG, SELFMAG) != 0) {
    Assert(0, "not a elf file\n");
  }

  Elf32_Shdr *shdrs = (Elf32_Shdr *)malloc(ehdr.e_shentsize * ehdr.e_shnum);

  fseek(fp, ehdr.e_shoff, SEEK_SET);
  int ret = fread(shdrs, ehdr.e_shentsize, ehdr.e_shnum, fp);
  assert(ret != 0);

  for (int i = 0; i < ehdr.e_shnum; i++) {
    if (shdrs[i].sh_type == SHT_SYMTAB) {
      Elf32_Shdr t = shdrs[i];

      uint32_t sym_link = t.sh_link;
      char *strtab = (char *)malloc(shdrs[sym_link].sh_size);

      fseek(fp, shdrs[sym_link].sh_offset, SEEK_SET);
      assert(fread(strtab, 1, shdrs[sym_link].sh_size, fp) != 0);

      fseek(fp, t.sh_offset, SEEK_SET);
      Elf32_Sym *syms = (Elf32_Sym *)malloc(t.sh_size);
      assert(fread(syms, 1, t.sh_size, fp) != 0);

      for (int i = 0; i < (t.sh_size / 16); i++) {
        Elf32_Sym sym_t = syms[i];
        if (ELF32_ST_TYPE(sym_t.st_info) == STT_FUNC) {
          sym_func[sym_func_count].addr = sym_t.st_value;
          sym_func[sym_func_count].size = sym_t.st_size;
          strcpy(sym_func[sym_func_count].name, strtab + sym_t.st_name);

          sym_func_count++;
        }
      }
      free(syms);
      free(strtab);
    }
  }
  free(shdrs);
  fclose(fp);

  print_syms();
}
