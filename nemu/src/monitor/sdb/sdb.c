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
#include <cpu/cpu.h>
#include <readline/readline.h>
#include <readline/history.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "sdb.h"
#include "common.h"
#include "memory/paddr.h"

static int is_batch_mode = false;

void init_regex();
void init_wp_pool();
void print_watchpoint();
int delete_watchpoint(int NO);
int set_wp(char * expression);
/* We use the `readline' library to provide more flexibility to read from stdin. */
static char* rl_gets() {
  static char *line_read = NULL;

  if (line_read) {
    free(line_read);
    line_read = NULL;
  }

  line_read = readline("(nemu) ");

  if (line_read && *line_read) {
    add_history(line_read);
  }

  return line_read;
}

static int cmd_c(char *args) {
  cpu_exec(-1);
  return 0;
}


static int cmd_q(char *args) {
  nemu_state.state = NEMU_QUIT;
  return -1;
}

static int cmd_si(char *args) {
	if (args == NULL) {
		cpu_exec(1);
	}else{
		long steps =  strtol(args,NULL,0);
		cpu_exec(steps);
	}
	return 0;
}

static int cmd_info(char *args) {
	if (args == NULL) {
		printf("Need Arguments r:print registers; w:print watchpoints \n");
		return 0;
	}
	if (strcmp(args,"r") == 0) {
		isa_reg_display();
	}
	if (strcmp(args,"w") == 0) {
		print_watchpoint();
	}
	return 0;
}

static int cmd_x(char * args) {
	if (args == NULL) {
		printf("Need Arguments\n");
		return 0;
	}

	char * temp = strtok(args, " ");
	long N = strtol(temp,NULL,0);
	if (N==0) {
		printf("Format :x N expr,N should be a number\n");
		return 0;
	}
	
	args = strtok(NULL," ");
	if (args == NULL ) {
		printf("Need More Arguments.\n");
		return 0;
	}
	
	bool * success = false;
	paddr_t address = expr(args,success);
	
	if (N > 0) {
		for (int i=0; i<N; i++) {
			word_t num = paddr_read(address+4*i,4);			
			printf("0x%x:0x%x\n",address+4*i,num);
		}
	}else {
		for (int i=0; i>N; i--) {
			word_t num = paddr_read(address+4*i,4);			
			printf("0x%x:0x%x\n",address+4*i,num);
		}
	}
	return 0;
}

static int cmd_p(char *args) {
	if (args == NULL) {
		printf("Need an expression\n");
		return 0;
	}

	bool * success = false;
	word_t result = expr(args,success);
	printf("0x%x\n",result);
	return 0;
}

static int cmd_w(char *args) {
	if (args == NULL) {
		printf("Need An Expression.\n");
		return 0;
	}
	
	if (set_wp(args) == 0) {
		printf("Succcess.\n");
	} else {
		printf("Failed.\n");
	}

	return 0;
}

static int cmd_d(char *args) {
	if (args == NULL) {
		printf("Need an number.\n");
		return 0;
	}

	int NO = (int)strtol(args,NULL,0); 	
	if (delete_watchpoint(NO) == 1) {
		printf("Success.\n");
	} else {
		printf("Delete failed.\n");
	}
	return 0;
}

static int cmd_t(char *args) {
       printf("==It is the test mode, designed by GlowingCurve.This command is used to test some thing.Something unexpected may happen.\n==");       
       FILE * fp = fopen(args,"r+");
       if (fp == NULL) {printf("Cann't open the file");return 0;}
       char * line = NULL;
       size_t n;
       int count=1;
       while (getline(&line,&n,fp) != -1) {
               for (int i=0;i<strlen(line);i++) {
                       if (line[i] == '\n') line[i] = '\0';
               }
               word_t REF_result;
               char * temp = strtok(line," ");
               REF_result = (uint32_t)strtol(temp, NULL, 0);
               bool * success = false;
               char * expression = line + strlen(temp)+1;
               word_t result = expr(expression, success); 
               if (result == REF_result) {
                       printf("%d passed\n",count);
                       count++;
               }else {
                       printf("%d failed:\n,REFERENCE result: %u,ACTAUL result: %u\n%s\n",count,REF_result,result,expression);
                       break;
               }
       }
       free(line);
       fclose(fp);
       return 0;
}

static int cmd_help(char *args);

 static struct {
  const char *name;
  const char *description;
  int (*handler) (char *);
} cmd_table [] = {
  { "help", "Display information about all supported commands", cmd_help },
  { "c", "Continue the execution of the program", cmd_c },
  { "q", "Exit NEMU", cmd_q },
  { "si", "Step [N], default one", cmd_si },
  { "info", "Show Information : r->print registers , w->print watchpoints", cmd_info },
  { "x", "examine the address", cmd_x},
  { "p", "evaluate the expression", cmd_p},
  { "d", "delete No.[N] watchpoint", cmd_d},
  { "w", "Set a watchpoint", cmd_w},
  { "t", "Test mode", cmd_t}
  /* TODO: Add more commands */

};

#define NR_CMD ARRLEN(cmd_table)

static int cmd_help(char *args) {
  /* extract the first argument */
  char *arg = strtok(NULL, " ");
  int i;

  if (arg == NULL) {
    /* no argument given */
    for (i = 0; i < NR_CMD; i ++) {
      printf("%s - %s\n", cmd_table[i].name, cmd_table[i].description);
    }
  }
  else {
    for (i = 0; i < NR_CMD; i ++) {
      if (strcmp(arg, cmd_table[i].name) == 0) {
        printf("%s - %s\n", cmd_table[i].name, cmd_table[i].description);
        return 0;
      }
    }
    printf("Unknown command '%s'\n", arg);
  }
  return 0;
}

void sdb_set_batch_mode() {
  is_batch_mode = true;
}

void sdb_mainloop() {
  if (is_batch_mode) {
    cmd_c(NULL);
    return;
  }

  for (char *str; (str = rl_gets()) != NULL; ) {
    char *str_end = str + strlen(str);

    /* extract the first token as the command */
    char *cmd = strtok(str, " ");
    if (cmd == NULL) { continue; }

    /* treat the remaining string as the arguments,
     * which may need further parsing
     */
    char *args = cmd + strlen(cmd) + 1;
    if (args >= str_end) {
      args = NULL;
    }

#ifdef CONFIG_DEVICE
    extern void sdl_clear_event_queue();
    sdl_clear_event_queue();
#endif

    int i;
    for (i = 0; i < NR_CMD; i ++) {
      if (strcmp(cmd, cmd_table[i].name) == 0) {
        if (cmd_table[i].handler(args) < 0) { return; }
        break;
      }
    }

    if (i == NR_CMD) { printf("Unknown command '%s'\n", cmd); }
  }
}

void init_sdb() {
  /* Compile the regular expressions. */
  init_regex();

  /* Initialize the watchpoint pool. */
  init_wp_pool();
}
