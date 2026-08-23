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

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <assert.h>
#include <string.h>

#define BUF_LENGTH 65536
#define warning_line 20
// this should be enough

static char buf[BUF_LENGTH] = {};
static char buf_copy[BUF_LENGTH] = {};
static char code_buf[BUF_LENGTH + 128] = {}; // a little larger than `buf`
static char *code_format =
"#include <stdio.h>\n"
"int main() { "
"  unsigned result = %s; "
"  printf(\"%%u\", result); "
"  return 0; "
"}";

int buf_tail = 0;
int buf_copy_tail = 0;

#define Warning_Set(s) \
	do { \
		(*s = 1); \
		return ; \
	} while(0)

#define Warning_Detected(s) \
	do { \
		if (*s == 1) return ; \
	} while (0)
		
void gen(char c, int * warning) {
	buf[buf_tail++] = c;
	buf_copy[buf_copy_tail++] = c;
	if (BUF_LENGTH - buf_tail < warning_line) Warning_Set(warning);
	return ;
}

void gen_num(int * warning) {
	if (rand()%2 == 1) {
		gen('-',warning);
		Warning_Detected(warning);
	}
	if (rand()%2 == 0) {
		for (int i=0; i < 1 + rand()%5; i++) {
			gen('1'+rand()%9, warning); Warning_Detected(warning);
		}
	} else {
		gen('0',warning); gen('x',warning); Warning_Detected(warning);
		for (int i=0; i < 1 + rand()%5; i++) {
			int tmp = rand()%16;
			if (tmp<=9) {
				gen('0'+tmp,warning); Warning_Detected(warning);
			} else {
				gen('a'+tmp-10,warning); Warning_Detected(warning);
			}
		}	
	}
	buf[buf_tail++] = 'U';
	Warning_Detected(warning);
}

void gen_rand_op(int * warning) {
	switch(rand()%7) {
		case 0: gen('+', warning); break;
		case 1: gen('-', warning); break;
		case 2: gen('*', warning); break;
		case 3: gen('/', warning); break;
		case 4: gen('=', warning); gen('=', warning); break;
		case 5: gen('!', warning); gen('=', warning); break;
		default: gen('&',warning); gen('&', warning); break;
	}
	Warning_Detected(warning);
}
void gen_rand_space (int * warning) {
	int n = 1+rand()%5;
	for (int i=0;i<n;i++) {
		gen(' ', warning);
		Warning_Detected(warning);
	}
}
static void gen_rand_expr(int * warning) {
	switch(rand()%3) {
		case 0: 
			gen_rand_space(warning);
			gen_num(warning);
			break;
		case 1: 
			gen('(',warning);
			gen_rand_space(warning);
			gen_rand_expr(warning);
			Warning_Detected(warning);
			gen_rand_space(warning);
			gen(')',warning); 
			break;
		default: 
			gen_rand_expr(warning); 
			Warning_Detected(warning);
			gen_rand_space(warning);
			gen_rand_op(warning);
			gen_rand_space(warning);
			gen_rand_expr(warning); 
			Warning_Detected(warning);
			break;
	}	
}

int main(int argc, char *argv[]) {
  int seed = time(0);
  srand(seed);
  int loop = 1;
  if (argc > 1) {
    sscanf(argv[1], "%d", &loop);
  }
  int i;
  for (i = 0; i < loop; i ++) {
	memset(buf,0,BUF_LENGTH);
	memset(buf_copy,0,BUF_LENGTH);
	buf_tail = 0;
	buf_copy_tail = 0;
	int warning = 0;
    gen_rand_expr(&warning);
	
	if (warning==1) {
		i--;
		continue;
	}
    sprintf(code_buf, code_format, buf);

    FILE *fp = fopen("/tmp/.code.c", "w");
    assert(fp != NULL);
    fputs(code_buf, fp);
    fclose(fp);

    int ret = system("gcc -Werror /tmp/.code.c -o /tmp/.expr");
    if (ret != 0) { i -- ;continue; }

    fp = popen("/tmp/.expr", "r");
    assert(fp != NULL);

    int result;
    ret = fscanf(fp, "%d", &result);
    pclose(fp);

    printf("%u %s\n", result, buf_copy);
  }
  return 0;
}
