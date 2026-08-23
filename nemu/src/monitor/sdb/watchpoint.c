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

#include "sdb.h"
#include <stdint.h>

#define NR_WP 32

typedef struct watchpoint {
  int NO;
  struct watchpoint *next;
  char * expr;
  uint32_t old_value;
  /* TODO: Add more members if necessary */

} WP;

static WP wp_pool[NR_WP] = {};
static WP *head = NULL, *free_ = NULL;

void init_wp_pool() {
  int i;
  for (i = 0; i < NR_WP; i ++) {
    wp_pool[i].NO = i;
    wp_pool[i].next = (i == NR_WP - 1 ? NULL : &wp_pool[i + 1]);
  }

  head = NULL;
  free_ = wp_pool;
}

/* TODO: Implement the functionality of watchpoint */

WP * new_wp() {
	if (free_ == NULL) {
		printf("No More Free Watchpoints.\n");
		return NULL;
	}

	WP * temp = free_;
	free_ = free_->next;
	temp->next = head;
	head = temp;
	return temp;
}

void free_wp(WP * wp) {
	wp->next = free_;
	free_ = wp;
}

int set_wp(char * expression) {
	WP * tmp = new_wp();
	if (tmp == NULL) {
		return -1;
	}

	size_t n = strlen(expression)+1;
	tmp->expr = (char *)calloc(n,sizeof(char));
	strncpy(tmp->expr,expression,n);

	bool * success = false;
	tmp->old_value = expr(expression,success);
	printf("Watchpoint Set: No:%d,Value:%u\n",tmp->NO,tmp->old_value);

	return 0;
}

int WP_checking() {
	int signal = 0;
	WP * tmp = head;
	while (tmp != NULL) {
		bool * success = false;
		uint32_t new_value = expr(tmp->expr, success);
		if (new_value != tmp->old_value) {
			printf("Watchpoint Hit.NO:%d,new_value:0x%x, old_value:0x%x\n",tmp->NO,new_value,tmp->old_value);	
			tmp->old_value = new_value;
			signal = 1;
		}
		tmp = tmp->next;
	}
	return signal;
}

void print_watchpoint() {
	WP * tmp = head;	
	while (tmp != NULL) {
		printf("NO:%u EXPR:%s Value:%d\n",tmp->NO,tmp->expr,tmp->old_value);
		tmp = tmp->next;
	}
}

int delete_watchpoint(int NO) {
	int signal = 0;
	
	WP * tmp = head;
	if (head->NO == NO) {
		head = head->next;
		free_wp(tmp);
		signal = 1;
		return signal;
	}

	while (tmp->next!=NULL) {
		if (tmp->next->NO == NO) {
			signal = 1;
			WP * t = tmp->next->next;
			free_wp(tmp->next);
			tmp->next = t;
			break;
		}
		tmp = tmp->next;
	}

	return signal;
}
