#include <klib.h>
#include <klib-macros.h>
#include <stddef.h>
#include <stdint.h>

#if !defined(__ISA_NATIVE__) || defined(__NATIVE_USE_KLIB__)

size_t strlen(const char *s) {
	size_t i = 0;
	while (s[i] != '\0') {
		i++;
	}
	return i;
}

char *strcpy(char *dst, const char *src) {
	size_t i = 0;
	while (src[i] != '\0') {
		dst[i] = src[i];
		i++;
	}
  dst[i] = '\0';
	return dst;
}

char *strncpy(char *dst, const char *src, size_t n) {
	size_t i = 0;
  size_t len = strlen(src);
	for (;i < len && i < n;i++) {
		dst[i] = src[i];
	}

	for (;i < n; i++) {
		dst[i] = '\0';
	}
	return dst;
}


char *strcat(char *dst, const char *src) {
	strcpy(dst + strlen(dst), src);
	return dst;
}

int strcmp(const char *s1, const char *s2) {
	unsigned char * s1_u = (unsigned char *)s1;
	unsigned char * s2_u = (unsigned char *)s2;
	size_t i = 0;
	while (s1_u[i] != '\0' && s2_u[i] != '\0') {
		if (s1_u[i] > s2_u[i]) return 1;
		if (s1_u[i] < s2_u[i]) return -1;
		i++;
	}

	if (s1_u[i] > s2_u[i]) return 1;
	if (s1_u[i] < s2_u[i]) return -1;
	return 0;
}

int strncmp(const char *s1, const char *s2, size_t n) {
	if (n == 0) return 0;

	unsigned char * s1_u = (unsigned char *)s1;
	unsigned char * s2_u = (unsigned char *)s2;
	size_t i = 0;
	while (s1_u[i] != '\0' && s2_u[i] != '\0' && i < n-1) {
		if (s1_u[i] > s2_u[i]) return 1;
		if (s1_u[i] < s2_u[i]) return -1;
		i++;
	}

	if (s1_u[i] > s2_u[i]) return 1;
	if (s1_u[i] < s2_u[i]) return -1;
	return 0;

}

void *memset(void *s, int c, size_t n) {
	uint32_t * align_s = (uint32_t *)((uintptr_t)(s + 3) & ~(uintptr_t)3);
  uint8_t * align_e = (uint8_t *)((uintptr_t)(s + n) & ~(uintptr_t)3);
  
  if ((void *)align_s > (void *)align_e) {
    uint8_t * s_t= (uint8_t *)s;
    for (int i = 0; i < n; i ++) {
      s_t[i] = (unsigned char)c;
    }
    return s;
  } 
  
  uint8_t * s_t = (uint8_t *)s;

  for (size_t i = 0; i < (void *)align_s - s; i ++) {
    s_t[i] = (unsigned char)c;
  }

  for (size_t i = 0;i < ((void *)align_e - (void *)align_s) / 4; i ++) {
    align_s[i] = (c << 24) | (c << 16) | (c << 8) | c;
  } 

  for (size_t i = (uintptr_t)((void *)align_e - s); i < n; i ++) {
    s_t[i] = (unsigned char)c;
  }
	return s;
}

void *memmove(void *dst, const void *src, size_t n) {
  unsigned char * dst_t = (unsigned char *)dst;
  unsigned char * src_t = (unsigned char *)src;

  if (dst > src ) {
    for (int i = n - 1; i >= 0; i --) {
      dst_t[i] = src_t[i];
    }
    return dst;
  }
  if (dst < src) {
    memcpy(dst, src, n);
    return dst;
  }
	return dst;
}

void *memcpy(void *out, const void *in, size_t n) {

  uint32_t * align_s = (uint32_t *)((uintptr_t)(out + 3) & ~(uintptr_t)3);
  uint8_t * align_e = (uint8_t *)((uintptr_t)(out + n) & ~(uintptr_t)3);
  
  if ((void *)align_s > (void *)align_e) {
    uint8_t * out_t = (uint8_t *)out;
    uint8_t * in_t = (uint8_t *)in; 
    for (int i = 0; i < n; i ++) {
      out_t[i] = in_t[i];
    }
    return out;
  }

  uint8_t * out_t = (uint8_t *)out;
  uint8_t * in_t  = (uint8_t *)in;

  for (size_t i = 0; i < (void *)align_s - out; i ++) {
    out_t[i] = in_t[i];
  }

  uint32_t * in_align = (uint32_t *)(in_t + ((void *)align_s - out));
  for (size_t i = 0;i < ((void *)align_e - (void *)align_s) / 4; i ++) {
    align_s[i] = in_align[i];
  } 

  for (size_t i = (uintptr_t)((void *)align_e - out); i < n; i ++) {
    out_t[i] = in_t[i];
  }
	return out;
} 

/*void * memcpy(void * out ,const void * in ,size_t n) {
  char * out_t = (char *)out;
  char * in_t = (char *)in;

  for (size_t i = 0; i < n; i ++) {
    out_t[i] = in_t[i];
  }

  return out;
}*/

int memcmp(const void *s1, const void *s2, size_t n) {
	if (n == 0) return 0;

	unsigned char * s1_u = (unsigned char *)s1;
	unsigned char * s2_u = (unsigned char *)s2;

	int i=0;
	while ( i < n - 1) {
		if (s1_u[i] > s2_u[i]) return 1;
		if (s1_u[i] < s2_u[i]) return -1;
		i++;
	}

	if (s1_u[i] > s2_u[i]) return 1;
	if (s1_u[i] < s2_u[i]) return -1;
	return 0;
}

#endif
