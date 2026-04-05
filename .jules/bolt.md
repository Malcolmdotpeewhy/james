## 2026-04-05 - [O(N) List Comprehension Optimization in web tools]
**Learning:** Re-evaluating an invariant string method like `filter.lower()` inside a list or dictionary comprehension causes unnecessary string allocations and significant O(N) overhead in hot paths.
**Action:** When iterating over dictionaries or lists with a static filter string, always compute the transformed string (`filter_lower = filter.lower()`) outside of the loop/comprehension to eliminate redundant O(N) function calls and memory allocations.
