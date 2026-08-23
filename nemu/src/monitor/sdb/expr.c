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
#include "memory/paddr.h"
#include <isa.h>

/* We use the POSIX regex functions to process regular expressions.
 * Type 'man regex' for more information about POSIX regex functions.
 */
#include <regex.h>
#include <stdint.h>
#include <string.h>

enum {
  TK_NOTYPE = 256,
  TK_NUM,
  TK_REG, // number, registers
  TK_LP,
  TK_RP, // LP means left parenthesis, RP means right parenthesis
  TK_MUL,
  TK_DIV, // mul, div
  TK_ADD,
  TK_SUB, // add, sub
  TK_NEQ,
  TK_EQ,
  TK_AND,
  /* TODO: Add more token types */

};

static struct rule {
  const char *regex;
  int token_type;
} rules[] = {

    /* TODO: Add more rules.
     * Pay attention to the precedence level of different rules.
     */

    {" +", TK_NOTYPE}, // spaces
    {"==", TK_EQ},     // equal
    {"(^[0-9]+)|(^0x[0-9a-fA-F]+)",
     TK_NUM},                    // number (support both dec and hex)
    {"[$][A-Za-z0-9]+", TK_REG}, // reg
    {"[+]", TK_ADD},             // plus
    {"[-]", TK_SUB},             // sub
    {"[*]", TK_MUL},             // mul
    {"[/]", TK_DIV},             // div
    {"[(]", TK_LP},              // left parenthesis
    {"[)]", TK_RP},              // right parenthesis
    {"!=", TK_NEQ},              // not equal
    {"&&", TK_AND},              // and
};

#define NR_REGEX ARRLEN(rules)

static regex_t re[NR_REGEX] = {};

/* Rules are used for many times.
 * Therefore we compile them only once before any usage.
 */
void init_regex() {
  int i;
  char error_msg[128];
  int ret;

  for (i = 0; i < NR_REGEX; i++) {
    ret = regcomp(&re[i], rules[i].regex, REG_EXTENDED);
    if (ret != 0) {
      regerror(ret, &re[i], error_msg, 128);
      panic("regex compilation failed: %s\n%s", error_msg, rules[i].regex);
    }
  }
}

#define str_max_length 64
#define max_tokens 65536
typedef struct token {
  int type;
  char str[str_max_length];
} Token;

static Token tokens[max_tokens] __attribute__((used)) = {};
static int nr_token __attribute__((used)) = 0;

#define warning_detected(s)                                                    \
  do {                                                                         \
    if (*s == 1) {                                                             \
      return 0;                                                                \
    }                                                                          \
  } while (0)

#define warning_set(s)                                                         \
  do {                                                                         \
    *s = 1;                                                                    \
    return 0;                                                                  \
  } while (0)

static bool make_token(char *e) {
  int position = 0;
  int i;
  regmatch_t pmatch;

  nr_token = 0;

  while (e[position] != '\0') {
    /* Try all rules one by one. */
    for (i = 0; i < NR_REGEX; i++) {
      if (regexec(&re[i], e + position, 1, &pmatch, 0) == 0 &&
          pmatch.rm_so == 0) {
        char *substr_start = e + position;
        int substr_len = pmatch.rm_eo;
        /*
                Log("match rules[%d] = \"%s\" at position %d with len %d: %.*s",
                    i, rules[i].regex, position, substr_len, substr_len,
           substr_start);
        */
        position += substr_len;

        /* TODO: Now a new token is recognized with rules[i]. Add codes
         * to record the token in the array `tokens'. For certain types
         * of tokens, some extra actions should be performed.
         */

        switch (rules[i].token_type) {
        case TK_REG:
          tokens[nr_token++].type = rules[i].token_type;
          strncpy(tokens[nr_token - 1].str, substr_start + 1, str_max_length);
          tokens[nr_token - 1].str[substr_len - 1] = '\0';
          break;
        case TK_ADD:
        case TK_SUB:
        case TK_MUL:
        case TK_DIV:
        case TK_LP:
        case TK_RP:
        case TK_EQ:
        case TK_NEQ:
        case TK_AND:
          tokens[nr_token++].type = rules[i].token_type;
          break;
        case TK_NUM:
          tokens[nr_token++].type = rules[i].token_type;
          if (substr_len >= str_max_length) {
            printf(
                "Too long number.The max length of the number is set to %d\n",
                str_max_length);
            return false;
          }
          memset(tokens[nr_token - 1].str, 0, str_max_length);
          strncpy(tokens[nr_token - 1].str, substr_start, substr_len);
          break;
        case TK_NOTYPE:
          break;
        default:
          break;
        }

        break;
      }
    }

    if (i == NR_REGEX) {
      printf("no match at position %d\n%s\n%*.s^\n", position, e, position, "");
      return false;
    }
  }

  return true;
}

void move_tokens(int left, int right, int *warning) {
  for (int i = left; i <= right - 1; i++) {
    memcpy(&tokens[i], &tokens[i + 1], sizeof(Token));
  }
  nr_token--;
}

void preprocessing(int left, int right, int *warning) {
  for (int i = left; i <= right - 1; i++) {
    if (i == left && tokens[i].type == TK_SUB && tokens[i + 1].type == TK_NUM) {
      tokens[i].type = TK_NUM;
      tokens[i].str[0] = '-';
      if (strlen(tokens[i + 1].str) <= str_max_length - 1) {
        strncpy(tokens[i].str + 1, tokens[i + 1].str, str_max_length - 1);
      } else {
        printf("Too long number ar token[%d]!Current limit is: %d\n", i + 1,
               str_max_length);
        *warning = 1;
        return;
      }
      move_tokens(i + 1, right, warning);
      right -= 1;
      continue;
    }
    if (tokens[i].type == TK_SUB && tokens[i + 1].type == TK_NUM &&
        !(tokens[i - 1].type == TK_NUM || tokens[i - 1].type == TK_RP)) {
      tokens[i].type = TK_NUM;
      tokens[i].str[0] = '-';
      if (strlen(tokens[i + 1].str) <= str_max_length - 1) {
        strncpy(tokens[i].str + 1, tokens[i + 1].str, str_max_length - 1);
      } else {
        printf("Too long number ar token[%d]!Current limit is: %d\n", i + 1,
               str_max_length);
        *warning = 1;
        return;
      }
      move_tokens(i + 1, right, warning);
      right -= 1;
      continue;
    }
  }
}

int get_op_position(int left, int right) {
  int op_position = -1;
  int op_type = -1;
  for (int i = left; i <= right; i++) {
    if (op_position == -1 && tokens[i].type >= TK_MUL &&
        tokens[i].type <= TK_AND) {
      op_position = i;
      op_type = tokens[i].type;
      continue;
    }
    if (tokens[i].type == TK_LP) {
      int balance = 1;
      int j = i + 1;
      for (; j <= right; j++) {
        if (tokens[j].type == TK_LP) {
          balance++;
        }
        if (tokens[j].type == TK_RP) {
          balance--;
        }
        if (balance == 0)
          break;
      }
      if (j > right) {
        printf("Get unmatched left parenthesis at token[%d]\n", i);
        return -1;
      }
      i = j;
      continue;
    }
    if (op_position != -1) {
      switch (tokens[i].type) {
      case TK_MUL:
      case TK_DIV:
        if (op_type >= TK_MUL && op_type <= TK_DIV) {
          op_type = tokens[i].type;
          op_position = i;
        }
        break;
      case TK_ADD:
      case TK_SUB:
        if (op_type >= TK_MUL && op_type <= TK_SUB) {
          op_type = tokens[i].type;
          op_position = i;
        }
        break;
      case TK_EQ:
      case TK_NEQ:
        if (op_type >= TK_MUL && op_type <= TK_EQ) {
          op_type = tokens[i].type;
          op_position = i;
        }
        break;
      case TK_AND:
        op_type = tokens[i].type;
        op_position = i;
        break;
      default:
        break;
      }
    }
  }
  return op_position;
}

int check_parenthesis(int left, int right, int *warning) {
  if (tokens[left].type != TK_LP || tokens[right].type != TK_RP)
    return 0;

  int balance = 0;
  int i = left;
  int early_closure = 0;
  for (; i <= right; i++) {
    if (tokens[i].type == TK_LP) {
      balance++;
    }
    if (tokens[i].type == TK_RP) {
      balance--;
    }
    if (balance < 0)
      break;
    if (balance == 0 && i != right) {
      early_closure = 1;
    }
  }

  if (balance != 0) {
    *warning = 1;
    printf("Invalid Format:From token[%d]:'('; to token[%d]:')'\n", left,
           right);
    return 0;
  }
  if (early_closure != 0) {
    return 0;
  }
  return 1;
}

uint32_t get_value(int type, int position) {
  if (type == TK_NUM) {
    return (uint32_t)strtol(tokens[position].str, NULL, 0);
  }
  if (type == TK_REG) {
    bool *success = false;
    uint32_t tmp = (uint32_t)isa_reg_str2val(tokens[position].str, success);
    return tmp;
  }
  /*
  if (type == TK_DEREF) {
    return (uint32_t)paddr_read((paddr_t)strtol(tokens[position].str, NULL, 0),
                                4);
  }
  */
  return 0;
}

uint32_t eval(int left, int right, int *warning) {
  if (left > right) {
    printf("Bad Expression\n");
    warning_set(warning);

  } else if (left == right) {
    return get_value(tokens[left].type, left);

  } else if (check_parenthesis(left, right, warning) == 1) {
    return eval(left + 1, right - 1, warning);

  } else {
    warning_detected(warning);

    int op_position = get_op_position(left, right);
    if (op_position == -1) {
      printf("Bad expression\n");
      warning_set(warning);
    }

    int op_type = tokens[op_position].type;
    uint32_t val1 = eval(left, op_position - 1, warning);
    warning_detected(warning);
    if (op_type == TK_AND && val1 == 0)
      return 0;

    uint32_t val2 = eval(op_position + 1, right, warning);
    warning_detected(warning);

    switch (op_type) {
    case TK_ADD:
      return val1 + val2;
    case TK_SUB:
      return val1 - val2;
    case TK_MUL:
      return val1 * val2;
    case TK_DIV:
      return val1 / val2;
    case TK_EQ:
      return val1 == val2;
    case TK_NEQ:
      return val1 != val2;
    case TK_AND:
      return val1 && val2;
    default:
      assert(0);
    }
  }
}

word_t expr(char *e, bool *success) {
  if (!make_token(e)) {
    printf("Lexical analysis failed.Exit\n");
    return 0;
  }

  /* TODO: Insert codes to evaluate the expression. */
  int warning = 0;
  preprocessing(0, nr_token - 1, &warning);
  uint32_t result = eval(0, nr_token - 1, &warning);

  if (warning == 1) {
    printf("Invalid Expression\n");
    return 0;
  }
  return result;
}
