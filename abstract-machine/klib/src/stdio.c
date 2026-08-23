#include <am.h>
#include <klib.h>
#include <klib-macros.h>
#include <stdarg.h>
#include <stdint.h>

#if !defined(__ISA_NATIVE__) || defined(__NATIVE_USE_KLIB__)

int sprintf(char *out, const char *fmt,...);
int vsprintf(char *str, const char *format,va_list ap);

int printf(const char *fmt, ...) {
  
  char buf[256]={};
  va_list ap;
  
  va_start(ap, fmt);
  int n = vsprintf(buf, fmt, ap);
  va_end(ap);

  putstr(buf);
  
  return n;
}

int vsprintf(char *out, const char *fmt, va_list ap) {

  char * s ;
	int d;
	signed char temp[128];
	int tail = 0;
	char * out_t = out;

	int i=0;
	while(fmt[i] != '\0' ) {
		if (fmt[i] == '%') {
			switch (fmt[i+1]) {
				case 's':
					s = va_arg(ap,char *);
					strcpy(out_t,s);	
					out_t += strlen(s);
					i+=2;
					break;
				case 'd':
					d = va_arg(ap,int);
					i+=2;
					if (d == 0)	{
						*out_t = '0';
						out_t++;
					}
          if (d < 0) {
            *out_t = '-';
            out_t++;
          }
					while (d != 0) {
						temp[tail++] = d%10;
						d /= 10;
					}
					for (int i = tail - 1; i >= 0; i--) {
            if (temp[i] < 0) {temp[i] = -(temp[i]);}
						*out_t =  temp[i] + '0';
						out_t++;
					}
					tail = 0;
					break;
        case 'u':
          d = va_arg(ap,uint64_t);
          i += 2;
          if (d == 0) {
            *out_t = '0';
            out_t ++;
          }
          while (d != 0) {
            temp[tail++] = d%10;
            d /= 10;
          }
          for (int i = tail - 1; i >= 0; i --) {
            *out_t = temp[i] + '0';
            out_t++;
          }
          tail = 0;
          break;
				default:
					*out_t = fmt[i];
					out_t++;
					i++;
					break;
			}
		} else {
			*out_t = fmt[i];
			out_t++;
			i++;
		}
	}
	*out_t = 0;
  
  return out_t + 1 - out;
}

int sprintf(char *out, const char *fmt, ...) {
	va_list ap;
	va_start(ap, fmt);

  int n = vsprintf(out, fmt, ap);

  va_end(ap);
	return n;
}

int snprintf(char *out, size_t n, const char *fmt, ...) {
  panic("Not implemented");
}

int vsnprintf(char *out, size_t n, const char *fmt, va_list ap) {
  panic("Not implemented");
}

#endif
