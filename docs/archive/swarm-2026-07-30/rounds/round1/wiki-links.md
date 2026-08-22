# Claims about `wiki-links.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] unlinked_mentions regex uses word boundaries but does not handle underscores/hyphens inside words; e.g., title 'agent' would match 'agentive' because \b matches before 'agent' and after 'ive'? Actually \b before 'agent' and after 'ive'? No, \b after 'agent' would not match because 'i' is word char; so false positive unlikely for that case. But title 'a_b' would match 'a_b_c' because \b after 'b'? Actually 'a_b' is a single word; regex would match 'a_b' inside 'a_b_c' because \b after 'b' fails? Let's check: 'a_b_c' has word chars; \b after 'b' is between 'b' and '_' which is not a word boundary because both are word chars; so no match. So false positives are limited to cases where title appears as a separate word, which is correct. However, common words like 'the' (3 chars) are skipped by length check; but words like 'and' (3 chars) also skipped. So false positives from common words are mitigated by length check.
2. [risk] local_graph can loop forever on a cycle if depth is large and max_nodes is not reached, because it only checks seen nodes, not visited edges; a cycle of unseen nodes would keep adding to frontier indefinitely.
3. [risk] local_graph truncates at MAX_LOCAL_NODES and sets truncated flag, but the note says 'stopped at the node bound; the neighbourhood is larger' which is clear.
4. [risk] unlinked_mentions truncates at MAX_MENTIONS_PER_PAGE without indicating how many were omitted; caller must check limit.
5. [risk] build_index silently drops links beyond MAX_LINKS_PER_PAGE per page; this could lose data without warning.
6. [todo] Consider returning a count of total matches in unlinked_mentions so caller knows truncation occurred.
7. [todo] Add visited edge set in local_graph to prevent infinite loops on cycles.
8. [todo] Test local_graph with a cycle and depth > 1 to confirm infinite loop.
9. [todo] Consider warning or logging when MAX_LINKS_PER_PAGE is exceeded.