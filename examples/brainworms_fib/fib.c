// fib — recursive Fibonacci. Two recursive calls means values must survive
// across calls, which forces a stack frame and callee-saved registers.
long fib(long n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}
