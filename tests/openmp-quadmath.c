#include <omp.h>
#include <quadmath.h>
#include <stdio.h>
int main(void) {
    int total = 0;
    #pragma omp parallel for reduction(+:total)
    for (int i = 1; i <= 100; ++i) total += i;
    char text[128];
    __float128 x = sqrtq(2.0Q);
    quadmath_snprintf(text, sizeof text, "%.30Qg", x);
    printf("C/OpenMP/Quadmath OK: %d %s\n", total, text);
    return total != 5050;
}

