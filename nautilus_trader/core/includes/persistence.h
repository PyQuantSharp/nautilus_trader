/* Generated with cbindgen:0.24.3 */

/* Warning, this file is autogenerated by cbindgen. Don't modify this manually. */

#include <Python.h>

typedef struct Vec_QuoteTick {
    QuoteTick_t *ptr;
    uintptr_t len;
    uintptr_t cap;
} Vec_QuoteTick;

typedef struct Vec_Bar {
    Bar_t *ptr;
    uintptr_t len;
    uintptr_t cap;
} Vec_Bar;

const QuoteTick_t *index_quote_tick_vector(const struct Vec_QuoteTick *ptr, uintptr_t i);

struct Vec_QuoteTick read_parquet_ticks(PyObject *path, PyObject *filter_exprs);

const Bar_t *index_bar_vector(const struct Vec_Bar *ptr, uintptr_t i);

struct Vec_Bar read_parquet_bars(PyObject *path, PyObject *filter_exprs);
