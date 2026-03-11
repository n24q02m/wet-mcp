## 2026-03-11 - Fast URL intersection filtering without regular expressions

**Learning:** When repeatedly splitting simple URL paths based on punctuation inside an inner loop, `re.split` is slower than chained string `replace` calls combined with the default `split()`. Also, `str.split()` automatically removes empty elements which avoids them ending up in the resulting `set`, slightly reducing memory allocation and improving performance. Using chained replaces + split on strings improves execution time by about 20% compared to Regex.

**Action:** Prefer `str.replace` chaining with `.split()` over `re.split` when splitting on a small fixed set of punctuation characters in performance critical sections, especially when we want to ignore consecutive delimiters or empty elements in string tokenization.
