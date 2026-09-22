# Architecture Decision Log
One entry per non-obvious decision: what, why, alternatives rejected. Newest at top.

## ADR-22: Intent gate shipped, clarifying follow-up built but off (2026-09-22)
Context: Two additions to the chat graph, each behind its own flag and gated first. (A) Social
and off-topic messages reached retrieval and a paid gpt-4o call before refusing; nothing
remembered a user's name. (B) A plain-language system description that retrieves nothing
usable ends in a bare abstention when one question about the system's function would
often resolve it.
Decision: (A) INTENT_GATE, the first graph node (app/generation/intent.py): gpt-4o-mini
classifies the message as social, offtopic or on_topic and does nothing else. Social
(greeting, name, thanks, capability) is answered from deterministic templates that name
no provision and state nothing about the law; an introduced name is extracted (model,
checked by regex) and persisted on chat_session.display_name (migration e5f6a7b8c9d0), and
rehydrated into the graph state each turn so later greetings use it. Offtopic returns the
existing grounded refusal with no retrieval. On_topic continues unchanged. Any mention of
an AI system, model, tool, the Act, risk, compliance or an obligation is on_topic by
deterministic override, so "hey, is my hiring tool ok?" is never social; a model failure
is on_topic so an outage cannot refuse everything. Tags |intent=social:<kind>,
|intent=offtopic, |intent=on_topic. ask.py's free scope short-circuit for bare greetings
still runs before the graph. (B) CLARIFY_FOLLOWUP (app/generation/clarify.py): when the
grader abstains on a question understood as a system description, one gpt-4o-mini
question about the system's function (what decision, about whom, on what data, with
neutral examples) is asked instead of abstaining; it must name no Article, Annex or legal
category and pass the verdict-leak detector or it is dropped and the turn routes. The
original question is kept on chat_session.pending_clarification; the reply turn is
retrieved as question plus reply through the unchanged path, skips the intent gate, and
cannot ask again. Tags |clarify=asked, |clarify=dropped:<reason>, |clarify=round.
Evidence: Intent set, 21 messages in 19 sequences, graph called directly: routing 3/3
greeting, 4/4 name (both names persisted, both recalled on the later turn), 2/2 thanks,
2/2 capability, 5/5 offtopic factual (0 answered), 5/5 disguised legal (0 misrouted);
social and offtopic lanes retrieved 0 times; social replies with legal content 0; verdict
leaks 0. The 47-item on-topic set with both flags on: recall, citation accuracy and
abstention identical item by item to the ADR-21 run, six off-topic items now refused at
the gate without retrieval. Clarify set, 5 sequences: the trigger never fired. On all
three underspecified descriptions the grader PROCEEDED (it finds some passage relevant to
any vague AI question) and the generator abstained; the property-valuation and pizza
items behaved as before. Grounding on the second pass 0/3 because no question was asked;
0 provisions asserted, 0 leaks.
Consequences: INTENT_GATE is on inside AGENTIC_RAG (off in production). CLARIFY_FOLLOWUP
stays off: its specified trigger (grader abstention) is not where "no supporting
provision" shows up in this pipeline; the generator's explain-mode abstention is. Widening
the trigger to that signal is a design decision to take before re-gating; the node, the
guards, the marker and the eval are in place. Two migrations' worth of columns are
nullable and additive.
Status: Accepted (A); Deferred (B).

## ADR-21: Plain-language system questions: explain the type, route the verdict, never certify (2026-09-22)
Context: Live, "I want to build a property valuation model for bridge lending, how risky is
it?" refused. The class of query is a user describing their OWN AI system in lay words and
asking whether it is regulated or how risky it is. Two problems meet here. Retrieval: the
phrasing has not reached the Act's vocabulary; measured in Part 0, dense retrieval ranked
Annex III point 5(b) second at a similarity of 0.24 that lost every fusion slot to BM25
matches on the lay words (and the 0.3 floor had emptied the dense leg altogether: fixed
first, ADR-20 follow-up). Safety: the honest answer to "how risky is MY system" is a
classification, and the classification belongs to the deterministic assessment, not to a
generated answer. The line for this build: chat MAY state what the Act says about a TYPE
of system, grounded and cited ("AI that evaluates the creditworthiness of natural persons
is listed in Annex III point 5(b)"); chat MUST NOT certify the user's specific system
("your system is high-risk").
Decision: (Part 1, app/generation/understand.py) one gpt-4o-mini structured call that
says whether the question describes a concrete AI system or use in plain words and, if
so, returns 2 to 6 Act-vocabulary SEARCH TERMS. The schema has no field for a
classification, a risk level or advice; terms that repeat the question's own words are
dropped; a question already in the Act's terms (providers, deployers, Articles, Annexes,
obligations, "high-risk AI systems") is not applicable without a model call; the check
runs on the user's typed words, not on a follow-up's rewrite; model trouble means not
applicable. The terms are FUSED with the question for retrieval (the Stage 1b dual
pattern, actor prior on the question) so the lay signal is kept. Not applicable means the
normal path, which scopes or refuses: nothing forces an Act reading onto "how risky is my
pizza oven?". (Part 2, graph.py and answer.py) for a detected question the generator is
shown the user's words but asked the question the chat may answer: what the retrieved
provisions say about systems of this kind and what determines whether a given system
falls within them; the appended instruction forbids any conclusion about the user's own
system. A deterministic verdict-leak check (understand.verdict_leaks: "your system is
high-risk", "you are a provider", with hedged forms allowed) runs after generation
regardless of the verifier flag: a leaking draft is regenerated once with the leak named,
a second leak abstains. The response carries system_description=True; the UI renders a
deterministic note and the route to the assessment. Tags: |understand=applied or
|understand=n/a, |leak=regenerated or |leak=abstained. Flag QUERY_UNDERSTANDING, inside
AGENTIC_RAG. Bounded: one understanding call, one regeneration, no web.
Evidence: New bucket plain_language, 8 authored items (gold flagged for review: the spam
filter maps to Article 4 by judgement; shop facial recognition to Annex III 1(a); the
property valuation item to 5(b) by the design's premise). Full pipeline, label-aware
judge, understanding off vs on, same day: plain_language context recall 0.429 to 0.714,
context precision 0.250 to 0.479, citation accuracy 0.286 to 0.429, answered 2 to 3 of 7,
routed 6 of 7, understood 6 of 8 (the chatbot item was judged not a system description;
the pizza oven correctly not). Verdict leaks: 0 on all 47 items, both runs; 0 leak
regenerations needed. Existing buckets: single_hop, unanswerable and reference identical
on every deterministic metric; multi_hop and multi_turn identical on recall, citation
accuracy and F1_ans; the one-point moves on one single-hop precision and one multi-turn
faithfulness item are grader reorder and judge variance on identical chunk sets
(understanding did not fire on them). The flagship: with understanding on, Annex III
5(b) is at rank 1 of the served context, the route flag is set, and gpt-4o still replies
with the abstention sentence, across three instruction variants (plain, softened
abstention condition, the explain question asked in place of the user's). CV screening,
emotion recognition at work and payment fraud detection explain and route correctly with
faithfulness 5. Three multi-turn follow-ups were first "understood" through their
rewrites (Act phrasing inserted by the rewriter); understanding now judges the typed
words, those three are not applicable, and one other terse follow-up ("And for
profiling?") is still judged a system question by gpt-4o-mini, with its
recall, citation accuracy and faithfulness unchanged and only the route note added: the
detector's remaining false positive, recorded.
Consequences: Part 1 works: the right provision reaches the context for lay phrasing.
Part 2 works where the Act names the use (recruitment, emotion recognition, credit
scoring with its fraud exception). Where the Act does not name the use, the strong model
declines to stretch the closest provision to it, and the property-valuation case is that
case: valuing property for bridge loans is not evaluating a natural person's
creditworthiness, and the model's refusal is defensible law. The value gate named that
item, so QUERY_UNDERSTANDING stays OFF by default; the eight-item bucket, the leak gate
and the runs are in place to re-gate after either a design decision (how far chat may
present a "closest provision" for a use the Act does not name) or prompt tuning of the
explain step. The hard safety line held everywhere it was measured.
Correction (2026-09-22, later the same day): the flagship's gold was a flawed premise.
Annex III 5(b) covers evaluating the creditworthiness of natural persons, not valuing
property or collateral, so the model's refusal to assert it was correct. Policy set: chat
MUST NOT stretch to a "closest provision" for a use the Act does not clearly name; it
explains only what the Act names for the system type, otherwise it routes and asserts no
provision. ag_pl_01 now has no gold provision and is satisfied by an abstention or by a
provision-free explanation, routed either way (route_or_abstain in the set; such items sit
outside recall and F1 and are checked for "stretched to a provision", gate 0). Detector
fixes: "the AI Act" and "regulation" no longer count as legal vocabulary (the chatbot item
was wrongly not applicable), and a question under four words is not applicable ("And for
profiling?"). Re-gate, same day, full pipeline, label-aware judge, corrected gold,
understanding off vs on: plain_language context recall 0.500 to 0.833, context precision
0.292 to 0.444, citation accuracy 0.333 to 0.667, F1_ans 0.500 to 0.800; of the five
Act-named types, CV screening, workplace emotion recognition, payment fraud detection and
shop facial recognition explain the provision and route (faithfulness 5 each), the shop
chatbot is understood with Article 50(1) at rank 2 of its context and still abstains, the
spam filter abstains with Article 4 not retrieved; the property-valuation question abstains
and routes asserting no provision, stretched 0; the pizza oven is not applicable and
refuses; understood 7 of 8, routed 7 of 7; verdict leaks 0 on 47 items; single_hop,
multi_turn, unanswerable and reference identical on every deterministic metric, multi_hop
identical on recall, citation accuracy and F1_ans; understanding fired on no item outside
the bucket. Hard and value gates pass; QUERY_UNDERSTANDING is on by default inside
AGENTIC_RAG. Known limits: the chatbot and spam-filter items still abstain; the detector
is gpt-4o-mini with two deterministic guards and a four-word minimum.
Status: Accepted; on inside AGENTIC_RAG (which stays off in production).

## ADR-20: Agentic RAG as a flag-gated LangGraph pipeline, one measured node at a time (2026-09-22)
Context: The grounded-answer path was a fixed sequence (retrieve, generate, abstain) that
served single questions well and had three measured weaknesses: follow-ups lost their
referent, compositional questions lost the half of their context that fusion crowded out,
and nothing checked an answer's citations after generation. The research plan called for
staged agentic retrieval (query rewriting, retrieval grading, citation verification,
bounded decomposition), each gated against the simple baseline, with no web tools and no
unbounded loops. The deterministic classification engine is not on this path and stays
out of it.
Decision: (1) Stage 0: app/generation/graph.py wraps the SAME three step functions the
plain path calls (retrieve_step, generate_step, decide_step in answer.py) as LangGraph
nodes, behind AGENTIC_RAG (config.agentic_rag_enabled, default off in every environment).
Flag off is the untouched plain path; flag on reproduced it on every deterministic
metric of every trace and on the easy golden set end to end. An eval harness
(evals/run_agentic_eval.py, metrics.py, gate.py) reports per trace context recall,
context precision (average precision over the 15-chunk slice), citation accuracy,
inline mention, abstention F1_ans and F1_ref, and judged faithfulness and relevance, over
a 35-item four-bucket set (evals/agentic_set.json: 12 single-hop, 8 multi-turn, 8
multi-hop authored and reviewed, 7 unanswerable) with a NON-COMPENSATORY gate: a node
ships only if faithfulness, context recall and abstention F1 improve or hold at ceiling
AND citation accuracy does not regress, per bucket. (2) Five nodes, each behind its own
flag effective only inside the graph, each on by default there after a passing run:
rewrite (AGENTIC_REWRITE, ADR-19's module reused: gpt-4o-mini, turn 2+ only, idempotent,
entity drift guard, actor-conflict abstention, and since Stage 1b DUAL retrieval: the raw
follow-up and the rewrite each retrieve and their RRF lists are summed before the actor
prior, because replacing the query lost Article 99(4) to "CE marking" saturating BM25);
grade (AGENTIC_GRADE: one gpt-4o-mini relevance grade over the slice, proceed with
relevant passages first and nothing dropped, ONE in-corpus widen at breadth 50 and slice
30, then abstain before any gpt-4o call); verify (AGENTIC_VERIFY: every provision the
answer names must resolve to a context passage or a passage's own cross-reference,
deterministic, and every cited claim must be entailed by its passage per a gpt-4o-mini
structured check with a deterministic backstop; misgrounded means ONE regeneration under
a grounding instruction appended to the user message, then abstain; both drafts' spend
stays on the trace); decompose (AGENTIC_DECOMPOSE: deterministic detection of a second
ask, a gpt-4o-mini planner capped at 3 standalone sub-questions screened by the entity
guard with a deterministic split as fallback, per-part retrieval and grading in parallel
form with one widen per part, a part left with nothing relevant abstains the turn, and
ONE strong-model compose call whose prompt groups the passages by part). No node adds
content or an outside source; the graph has no edge back to retrieval; every outcome is
tagged on query_trace.retrieval_config (path, rewrite, grade, verify, decompose). (3) The
faithfulness judge (evals/judge.py) now sees each context chunk with its citation label,
because without labels it scored correct references such as "Article 6, paragraph 6"
as unsupported; criteria unchanged, validity up. Every run file is re-baselined under it
(evals/runs/*_j2.json).
Evidence: Quality, Stage 0 baseline to the full pipeline, same set, label-aware judge:
pooled context recall 0.964 to 1.000, citation accuracy 0.893 to 1.000, abstention F1
0.883 to 1.000, faithfulness 0.992 to 1.000, context precision 0.717 to 0.794; multi-turn
F1_ans 0.933 to 1.000 with the coreference follow-up now citing Article 99(4)(a);
multi-hop recall 0.875 to 1.000 and citation accuracy 0.750 to 1.000 with both
definition-half refusals answered; single-hop identical throughout; unanswerable 7/7
refused at every stage, six of them now stopped at the grader with no gpt-4o call.
Verifier probe set (24 authored probes): gpt-4o 12/12 true positives, 0 false positives;
gpt-4o-mini 11/12 and 0. Per stage the gate and its verdict are in the run files.
Latency and cost (evals/profile_pipeline.py, 35 items, no judge, tokens as returned by
the API, dollars at list prices gpt-4o 2.50/10.00, gpt-4o-mini 0.15/0.60, embeddings
0.13 per 1M): p50 turn latency 2.3 s to 7.4 s pooled, p95 3.3 s to 14.3 s; single-hop
2.0 to 5.6 s (grader +2.0 s, verifier +1.8 s); multi-turn 2.7 to 10.3 s (rewrite +1.2 s,
grader +2.4 s, verifier +3.4 s); off-topic 1.3 to 6.5 s (the grader's widen before
abstaining, +5.3 s) but 3.1 to 1.1 tenths of a cent, the gpt-4o call saved; compositional
2.7 to 13.3 s (planner +1.1 s, two or three grades +4.4 s, verifier +4.5 s). Cost per turn
0.42 to 0.50 cents pooled (+19%), 0.48 to 0.78 cents on compositional turns.
Consequences: Correctness moved on every weakness the plan named, at a latency cost that
is real: an agentic turn is three times slower at the median and four times at p95, most
of it the grader and the verifier, which are serial gpt-4o-mini calls around the gpt-4o
call. The pipeline is one flag from production and off until the UI shows progress for
slow turns. Open, honestly: with gpt-4o as verifier a faithful paraphrase of Article
66(h) was rejected twice and a correct answer withheld (the reason gpt-4o-mini is the
default; VERIFY_MODEL selects the stricter one); the grader's widen fires on every
off-topic question before abstaining and could be skipped on a low top similarity, an
unswept constant; the reorder inside the grader moved multi-turn faithfulness by one judge
point until the judge fix showed it was the judge; DSPy or any prompt tuning of the
sub-steps has not been done, every prompt is hand-written and measured once; the
compositional bucket's gold is authored by the same person as the prompts and two items
are flagged for confirmation in PROJECT_BRIEF.md; verifier and grader tokens are not yet
columns on query_trace, only the trace tags are.
Status: Accepted; AGENTIC_RAG off in production pending the progress affordance.

## ADR-19: Chat scope handling: greeting short-circuit shipped, follow-up rewrite built but off (2026-09-22)
Context: Two chat behaviours were measured this week. (1) Greetings and off-topic input
("hey", "thanks", "???") hit the generic retrieval refusal after a paid call. (2) Follow-ups
("and for deployers?") lose their context because each turn retrieves on the raw message.
Decision: (1) app/generation/scope.py: is_trivial_input() detects empty, letterless or
greeting-only input deterministically; /ask answers it with a fixed scope message
(scope_notice=true, session_id null) BEFORE the quota check, embedding or model call, so it
creates no session, no message and no trace. The genuine retrieval refusal is unchanged; the
UI renders the same purposeful copy for both (what the copilot is for, three example
questions, the route to an assessment, "not legal advice"). (2) app/generation/rewrite.py:
a gpt-4o-mini structured rewrite of turn 2+ into a standalone question, behind the existing
StructuredExtractor interface, with a deterministic entity guard (any actor, body, system
type, article or number absent from the conversation discards the rewrite), idempotence,
and fail-open to the original question. Wired into /ask but gated OFF by default
(config.followup_rewrite_enabled, FOLLOWUP_REWRITE=1 to enable). query_trace gained
rewritten_query, rewrite_prompt_tokens, rewrite_completion_tokens (migration c9e1f2a3b4d5,
additive, nullable).
Evidence: Scope: unit and API tests; greeting returns the notice with no quota consulted and
no session write. Rewrite eval (evals/followup_set.json, 44 sequences, retrieval-only,
gpt-4o-mini + embeddings, ~$0.008): hard gates held (single-turn golden set 56/56 pass-through
with recall unchanged; 0 hallucinated-entity rewrites; off-topic follow-ups left untouched 3/3;
idempotence 5/5). Value gate missed: correct citation in the 15-chunk context pooled over 36
follow-ups 69% -> 81% (+12 points against a required +30); on the 18 context-dependent
follow-ups 44% -> 67%. The first 18 follow-ups as written carried the target's own nouns, so
the baseline already retrieved 17/18; the terse block was added rather than substituted.
Consequences: The scope notice is live and free. The rewrite stays in the code path but makes
no call until the flag is set after a passing run; the eval and gate are re-runnable as is.
The refusal contract (ABSTENTION_TEXT, generation unchanged) was not touched by either.
Status: Accepted (scope notice); Deferred (rewrite, flag off).

## ADR-18: Delete a chat; query_trace attributed by user_id so the quota survives (2026-09-22)
Context: Users need to delete chats. Recon found every FK on chat_session, message and
query_trace is NO ACTION and query_trace.chat_session_id was NOT NULL, so a hard delete
could not proceed without deleting the traces; and the daily quota was counted through
query_trace -> chat_session -> app_user, so deleting a chat would have reset the user's count
for the day and blinded the admin viewer. The audit and money rows must outlive the chat.
Decision: Migration d4f5a6b7c8e9: query_trace.user_id (FK app_user, backfilled from the
session, then NOT NULL, indexed with created_at) and chat_session_id made nullable.
DELETE /sessions/{id} (owner-scoped via get_owned_session, same 404 for foreign and unknown
ids) sets chat_session_id to NULL on the chat's traces, deletes citations, messages and the
session, and commits. calls_today() counts query_trace and extraction_run by their own
user_id, no session join. The trace writer stores user_id on every new row; the admin viewer
joins app_user through query_trace.user_id, so detached traces stay visible. Saved
assessments are separate records and are not touched. UI: a per-row menu, a Radix
AlertDialog confirmation (focus trapped, Escape and backdrop cancel), refetch after delete,
the designed empty state when the last chat goes; the shell drawer ignores an Escape a nested
dialog has already handled.
Evidence: tests: non-owner and unknown id return the same 404 and change nothing; anonymous
401; owner delete removes chat, messages and citations; the trace remains with
chat_session_id NULL and the owner's user_id, retrieval_trace intact, calls_today unchanged;
the assessment remains; the chat is gone from the list; a second delete is 404; the admin
list still shows the detached trace. Row diff around the DB-backed suites +0 on eight tables.
Backfill left 0 rows with a null user_id. Playwright: menu, dialog role alertdialog with focus
inside, Escape cancels with no row lost, confirm removes the row, "No chats yet" after the
last one.
Consequences: Deleting a chat can never reset a quota or hide a turn from the operator. The
migration's downgrade is the one lossy direction: detached traces would have to be deleted
to restore NOT NULL. Migration must run before the code that writes query_trace.user_id
starts (ADR-11 rule).
Status: Accepted.

## ADR-17: Generation answers from the governing provision instead of refusing on a technicality (2026-09-22)
Context: After ADR-16 every broad question had its gold provision in context, yet "what is a
high-risk AI system?" still refused in most runs (1/6, 3/6 and 1/2 across three sessions)
with Article 6(1) at rank 1. The four Article 3 definition questions answered 6/6. The model
was treating a classification rule phrased as conditions as "not a definition". The
ungrounded control ("when does the Act start to apply?", whose general application sentence
the corpus does not capture) refused 6/6, correctly.
Decision: One additive paragraph in SYSTEM_PROMPT: the context often contains the provision
that governs the question (a definition in Article 3, a classification rule such as Article
6 or Annex III, a scope rule, a list of obligations or prohibitions); when it does, answer
from it and cite it, and do not abstain merely because it is phrased as conditions or a
rule; abstain only when no provision in the context bears on the question. The "context
only" rule and the exact abstention sentence are unchanged. Also: is_abstention() treats the
abstention sentence wrapped in quotation marks as a refusal (the model sometimes copies the
quotes the prompt shows; the exact-match check had let that through as an answer with
fifteen citations attached).
Evidence: 6 repeats at temperature 0 per query, nothing persisted. Flagship 3/6 -> 6/6;
provider, deployer, AI system, GPAI definitions 6/6 -> 6/6; ungrounded control 0/6 -> 0/6.
Off-topic set (11 questions, twice each) 22/22 refused. Easy golden set with the judge:
citation hit 16/16 -> 16/16, abstention accuracy 20/20 -> 20/20, mean faithfulness 4.812 ->
4.938, faithfulness pass@4 1.000 -> 1.000, mean relevance 4.938 -> 4.875 (one item, gs_02,
4 -> 3 for "lacks specific examples", same citation hit). Golden retrieval unaffected (a
prompt cannot move it; re-measured anyway). Live smoke through /ask: the flagship answers
citing Article 6(2) and Annex III; pizza and the application-date question refuse. Spend
about 137 gpt-4o and 64 gpt-4o-mini judge calls, roughly $0.90 at list prices.
Consequences: Broad classification questions now answer stably when the governing provision
is shown; nothing answers without it. The one-point relevance move on one item is recorded,
not hidden. The application-date gap is a corpus/parser matter (ADR-002), out of scope here.
Status: Accepted.

## ADR-16: Dense anchor in fusion; BM25 saturation was hiding rank-1 vector hits (2026-09-22)
Context: "what is a high-risk AI system?" and similar broad questions were reported as
refusing. Measured before any change on a 14-question broad set: 10/14 answered and 9/14
cited the gold, not ~0. The 5 misses were NOT retrieved at all, and all five were Article 3
definitions or Article 113. Per leg, the vector search ranked the gold #1 for every one of
them while BM25 did not have it in its top 25: "provider" and "system" match hundreds of
chunks. RRF at 0.4/0.6 gives a vector-only rank-1 chunk 0.4/61 = 0.0066, while any
lexical-only chunk in BM25's top 25 scores at least 0.6/85 = 0.0071, so a dense rank-1 hit
could not even enter the 25 fused candidates. The pre-LLM gate never fired on any broad
question; the model refused correctly given what it was shown.
Decision: retrieve_candidates() in app/generation/answer.py now holds the whole production
retrieval block (vector + BM25, RRF, actor prior) so evals measure the served path, plus
apply_dense_anchor(): if the top vector hit clears DENSE_ANCHOR_FLOOR = 0.45 and is absent
from the 15-chunk context, insert it at DENSE_ANCHOR_POSITION = 5 (sixth) and stamp
"|anchor=dense" on retrieval_config. Position six because inserting at the front cost one
golden recall@5 hit; below the top five, recall@5 is unchanged by construction. Floor from
the sweep {0.40, 0.45, 0.50}: golden recall identical at all three; 0.40 also fires on the
off-topic "summarise the GDPR" (0.415); 0.50 leaves "who is a provider?" (0.503) no margin.
Both constants are Yash's to re-pick (ADR-7 rule); the sweep is evals/run_broad_eval.py.
Evidence: Broad set gold in context 9/14 -> 14/14; answered with gold cited 9/14 -> 13/14
single pass, 12/14 stable over repeats; golden recall hard 34/35 @5 and 35/35 @15,
realistic 56/56 and 56/56, identical before and after; off-topic 11/11 refused, anchor
fired 0/11 off-topic; 0 ungrounded article mentions. The two that remained: the flagship
(model variance, fixed in ADR-17) and the application-date question (corpus gap).
Consequences: Short definitional queries reach the generator with their definition. The
anchor privileges the dense leg's top-1 only when fusion has excluded it; every firing is
visible in query_trace.retrieval_config. Not MMR, not a threshold change, no new paid call.
Status: Accepted.

## ADR-15: Free-text input for the assessment: LLM fills the form, never the verdict (2026-09-22)
Context: The questionnaire is 29 fields. The strategy wants a lower front door: the user
describes the system, a model pre-fills the form, the user confirms, the deterministic
engine runs unchanged. The mapping is generated output, so it is eval-gated (CLAUDE.md
invariant 3), unlike the wedge itself (ADR-12).
Decision: app/extraction/ (a separate package: app/assessment stays provably LLM-free by
test). One interface, StructuredExtractor, with OpenAIExtractor (chat.completions.parse,
strict schema, temperature 0) and FakeExtractor for tests; default openai:gpt-4o-mini via
config.extraction_model(). Every field of ExtractedAnswers carries its own {value, quote}
slot. The mapper enforces, not trusts: (D1) a quote must be a verbatim substring of the
description, tolerant of whitespace, letter case and edge punctuation only (D6), else the
value is downgraded to unknown and the failure recorded; (D2) the five legal
characterisations (is_ai_system, substantial_modification, changed_intended_purpose,
relies_on_6_3, gpai_systemic) are NEVER pre-filled, whatever the model returns; (D3) a "no"
may rest on the passage that entails it, only when unambiguous; (D4) quote only from the
description, never the law text, build-and-use in-house is provider and deployer,
interacts_with_persons means the system itself addresses a person; (D7) annex_iii_point
quotes the purpose passage; (D8) undertaking is never inferred from an occupation word. The
extract endpoint returns answers, provenance, quotes and to_confirm, never a report; the UI
blocks "Build the report" until every visible unknown is answered. POST /assess/extract:
service token, per-minute limit, the same daily quota as chat (extraction_run rows counted
with query_trace, written fail-closed), length cap before spend, description stored for
admin-only review (C5). Saved assessments carry source and extraction_run_id (migration
b7d3e9f1a2c4); the export says "pre-filled from a description on ..., then reviewed and
confirmed by the user". Gemini was not wired: adding it needs google-genai, GEMINI_API_KEY,
and the PAID tier only (the free tier's terms, fetched 21 Sep 2026, allow human review and
product improvement on submitted content).
Evidence: Authored eval set, 30 cases (10 explicit, 10 partial, 10 adversarial), scored
over the fields the user would see. Four runs (~$0.035 each): run 1 exposed that a side
list of quotes is skipped (396 missing); run 2 exposed law text passed off as quotes (18
caught); run 3 exposed an "annex = none" collapse. Run 4, the shipped prompt
(prompt_version 2f666c1e7b49): false inference 2/187 (1%), legal-five false inference 0/62
by construction, fabricated quotes passing an independent audit 0/123, verdict match after
the user confirms unknowns 28/30 (93%), verdict match as mapped 16/30 (53%), gold-known
fields correct 27%. Gate: legal-five 0, no fabricated quote passes, false inference <= 7%,
verdict-after-confirmation >= 85%: pass. Calibration: describe-screen copy says "a head
start; you confirm the rest" because verdict-as-mapped and correct-rate sit under the 60% /
45% thresholds for stronger wording. One live extraction: 5,943 prompt / 438 completion
tokens, 5.6 s. Documented pre-fill gap: Article 5(1)(f) workplace emotion inference and
5(1)(h) real-time RBI were never flagged in any run; the prohibited-practices step is
always shown for the user to answer.
Consequences: The pre-fill is a head start, not a filled form (most entailed negatives are
left for the user). The eval set is authored by the prompt's author and blind to real
phrasing; numbers are provisional until real descriptions are added. ENGINE_VERSION is
unaffected (extraction sits upstream of Answers); prompt_version is stored per run.
Status: Accepted.

## ADR-14: Export as a self-contained HTML record, rendered on the backend (2026-09-21)
Context: The strategy doc sells the artifact, not the chat: a dated, cited record a customer
can hand to a reviewer. Three ways to produce it were weighed. (A) Server-side PDF: the
strongest single source of truth and the most reproducible bytes, but the usable
HTML-to-PDF engines need native libraries on the Railway image (Pango, Cairo, GDK-PixBuf
for WeasyPrint, or a ~300 MB headless Chromium), and the pure-Python alternatives mean
hand-building the layout in code. (B) A print stylesheet over the on-screen React report:
zero dependency, but the document is produced by whichever browser the user has, from a
component that also serves the interactive view, so pagination and content drift with
the UI and no server-side artifact exists to keep. (C) The backend emits a standalone HTML
document, viewable and printable.
Decision: C. app/assessment/export.py renders one deterministic document from the same
AssessmentResult the JSON routes return: provision text goes database -> build_report ->
this renderer and never through the frontend. Inline CSS with the light-theme design
tokens copied in as literal values, local font stacks, no scripts, no external assets
(the only absolute URLs are the EUR-Lex citation anchors), a print stylesheet, and the
not-legal-advice notice. GET /assessments/{id}/export.html is owner-scoped through
get_owned_assessment (foreign or unknown id -> 404), inline by default so it opens in a
tab, attachment with a dated filename on ?download=1. The BFF relays the bytes and adds a
Content-Security-Policy that forbids scripts anyway. Rendered with the standard library:
Jinja2 was not installed, and a header plus nested lists does not justify a template
engine; html.escape covers every string that came from the database or the user.
Evidence: Tests render the HR-tech record end to end and assert the assessed-on date,
engine_version, corpus consolidated date, every obligation citation id, the computed
ceilings (EUR 60,000 and EUR 20,000 for an SME with EUR 2M turnover, with the Article
99(6) basis quoted), "not legal advice", "appears to", no "you are compliant", no em
dash, no script, and that every absolute URL is EUR-Lex with no link, img, @import or
url() anywhere; a non-owner gets the same 404 as an unknown id and an anonymous caller
401. The rendered document is 79,934 bytes for the HR-tech case, screenshotted at 1440,
390 and in print media with no horizontal scroll.
Consequences: C gives A's single source of truth at B's build cost and ships on the
current Railway image; the same renderer's output is the input for a PDF engine if a
customer ever needs a PDF we produce rather than one they print (A remains the end state
for that). The PDF the user prints from the record inherits browser variance; the HTML
file itself is the reproducible artifact. The record renders provision text from the
current corpus at generation time, the same known limitation as ADR-13, stated in the
document's footer; no snapshot hashing or immutability was added.
Status: Accepted.

## ADR-13: Saved assessments; the server re-derives the result from the answers (2026-09-21)
Context: The wedge (ADR-12) was stateless: a report existed only on screen. The product
needs a record the user can reopen and, later, export. The existing persistence pattern
(chat_session with a user_id FK, get_owned_session's 404-not-403 rule, environment
stamped from app_env(), flush-and-rollback tests) was reusable as is.
Decision: A new `assessment` table (migration 6aa3cd421b84, additive): user_id,
corpus_version_id, environment, engine_version, corpus_consolidated_date, answers (JSONB),
headline, roles, obligation_citation_ids, penalties, created_at. **The trust boundary is
that POST /assessments accepts ANSWERS ONLY**: the server re-runs the deterministic engine
and build_report and stores what they produce, so a client can never save a headline,
an obligation list or a penalty figure it did not earn from its own answers (a test posts
a body carrying headline=MINIMAL and a fake report and asserts HIGH_RISK is what gets
stored). Reads are owner-scoped: the list is WHERE user_id = the caller, the detail goes
through deps.get_owned_assessment, and a foreign id and an unknown id return the same
404. engine_version is "assess-1.<rules_hash>", where rules_hash is the SHA-256 of a
canonical serialisation (sorted keys, sorted lists, fixed separators, ASCII) of the rule
DATA in code: the Annex III point list, the authority gate, the Article 25 and scope
tables, the obligation groups, the questionnaire ids and the penalty paragraph ids. Any
rule change changes the version without anyone remembering to bump it. The corpus
consolidated date is stored next to it, because the TEXT a report quotes depends on the
corpus, not on the rules. The old ClassificationRun table (audit.py) is left untouched.
Evidence: Migration up, down and up again clean on Supabase. Tests: owner saves (201,
environment stamped "test", engine_version matching), lists exactly their rows, reopens
with the answers round-tripped and the report re-rendered; a second user gets 404 on the
first user's id and an empty list; anonymous 401 on every route; invalid answers 422 with
nothing saved; the rules hash equals an independently computed SHA-256 of the canonical
JSON. The DB-backed fixture points the session's commit at flush, so the endpoints' real
commit path runs while nothing leaves the transaction; rollback at the end. Full suite at
the time of shipping: 213 passed, 5 skipped (live-gated), zero paid calls.
Consequences: Two honest gaps. (1) The hash covers rule data, not engine LOGIC; a change
to engine.py's control flow that leaves the data untouched requires a hand bump of
ENGINE_MAJOR, and nothing enforces that. (2) **Known limitation, recorded and not built:
a reopened assessment re-renders provision text live from the current corpus; it is not
an immutable snapshot of the quoted text.** engine_version and corpus_consolidated_date
say which rules and which text produced the decision at save time, which is enough to
notice a change, not to reproduce the old text. ClassificationRun is dead code to remove
in a later cleanup. Migration 6aa3cd421b84 must run before the code that writes the table
deploys (the ADR-11 rule).
Note (2026-09-21): ENGINE_MAJOR bumped 1 -> 2, the first exercise of the hand-bump rule.
penalties.py logic changed: a turnover of 0 no longer computes to a "EUR 0" ceiling under
the SME "lower" rule; it is "not computed" and the record prompts for a positive turnover.
Rule data was untouched, so the hash alone would not have moved.
Status: Accepted.

## ADR-12: The assessment wedge is deterministic end to end; no LLM, no eval gate (2026-09-21)
Context: docs/PRODUCT_STRATEGY.md moved the product from "chat over the Act" to "produce
the compliance record": describe the system, classify its risk tier, list the obligations
that apply to that role, export a dated, cited report. The existing classifier covered
only Annex III points 5(b) and 5(c) and never asked about role, Article 5, Article 6(1)
or Article 50, so it was reusable as a shape (a deterministic, cited result) but not as
the engine. Every branch the wedge needs is quotable from the corpus except Annex I
(ADR-004) and the Regulation's general application sentence (ADR-002).
Decision: A new package, app/assessment, with a structured questionnaire whose every
question names the provision it rests on, a pure rules engine (assess: answers in,
citation ids out), a reviewed obligation table keyed by tier and role, a penalty module
that parses the Article 99 ceilings out of the LIVE paragraph text at request time and
computes the higher / SME-lower / SMC-lower rules from the user's own turnover, and a
report builder that assembles VERBATIM provision text by citation id. **No language model
is anywhere in the path**, and a test greps the package for OpenAI, embedding and
retrieval imports. Where the Act requires a legal characterisation the engine records
the answer and flags it: an Article 5 match is a red flag, never a verdict; the Article
6(3) derogation is quoted, never applied; "substantial modification" and "is it an AI
system" are self-declared; the Annex I route is reported as possibly high-risk and
honestly incomplete. Everything the tool says in its own words is labelled commentary;
the report says "appears to" and never "compliant". The old classify() and /classify stay
untouched.
Why no eval gate applies: CLAUDE.md invariant 3 gates LLM-generated text on faithfulness
and grounding evals. The wedge generates none. The verdict is deterministic and covered by
table-driven tests (every Annex III point, every Article 5 key, the authority gate, the
textual exclusions, Article 25, scope, open source), and every sentence of law in the
report is the corpus text itself, fetched by id. There is no generated prose to judge.
An LLM plain-language layer, when it comes, is a separate change that IS eval-gated and
budget-gated.
Evidence: 65 tests at the time of shipping, zero paid calls: a DB-backed test asserts
every citation id the engine, map, questionnaire and penalties reference exists in the
corpus; the live Article 99 text parses to (35M, 7%), (15M, 3%), (7.5M, 1%); the
obligation table agrees with the ADR-10 actor map; the HR-tech case end to end yields
Annex III 4(a) quoted, the Article 16 points in order, "2 December 2027" from Article
113, and an SME par_4 ceiling of EUR 60,000 with Article 99(6) cited. Playwright on the
harness at 390 and 1440, light and dark: no "you are compliant", "not legal advice"
present, no horizontal scroll.
Consequences: The front door is now the assessment (Phase 1: primary CTA, hero card
rendered from a REAL report fixture, chat demoted to "Ask a question"). Boundary cases
F1 to F7 and O1/O2 are recorded in the actor map and obligation table docstrings at their
approved defaults. Out of scope and explicitly deferred: Annex I ingestion, public or
anonymous access, free-text input, any LLM prose. A test literal such as 140_000 for an
SME with EUR 2M turnover is a test oracle, not product code, and stays literal.
Status: Accepted.

## ADR-11: Environment-tagged query_trace; the daily quota is per environment (2026-09-21)
Context: Local dev, the two pytest live-stack tests, and any trace-writing eval all write
query_trace rows to the same Supabase that production will read, and calls_today()
counted every row for the UTC day. That was invisible at DAILY_LIMIT_GLOBAL=2000 and
became reachable at 100 (ADR-8's cost follow-up): roughly fifty local pytest runs in a day
would have tripped the circuit breaker and 429'd real users. On the day of the change the
table held 12 rows, 9 of them written by pytest.
Decision: An environment label, DERIVED from config and stored on the row, not inferred
from account names. config.app_env() reads APP_ENV, defaults to "dev", and raises on any
value outside ("production", "dev", "test"). query_trace gains an environment column
(server_default "dev") stamped at the single trace write site, _write_trace_safe.
calls_today() filters environment == app_env(), so each environment has its own budget:
production counts only production, local dev still exercises a working quota against its
own rows, and tests count only test rows. pytest declares itself via tests/conftest.py
(APP_ENV=test, assigned rather than setdefault so a developer's shell value cannot leak
in); production code never sniffs for pytest. /health returns the environment as the
deploy smoke test, and startup prints an ACTION REQUIRED line if RAILWAY_ENVIRONMENT_NAME
is set while APP_ENV is not production. Alternatives rejected: excluding test emails in
calls_today() (brittle, and does nothing for the owner's own local /ask turns); making
tests stop persisting traces (leaves the trace path untested and again ignores local dev);
a separate database per environment (correct long-term isolation, but a re-ingest plus
two migration targets for a bug one column fixes, and complementary rather than
competing, since the label is still wanted inside each database).
Evidence: Additive migration f59000150c0d applied to Supabase; ADD COLUMN with a constant
default is catalog-only on Postgres 11+, and the backfill read dev 3 / test 9, exactly
the account split measured beforehand. pytest with OPENAI_API_KEY empty: 115 passed, 5
skipped (the live tests), zero paid calls, and a six-table row diff of +0 around the run.
The new DB-backed test flushes one trace inside a transaction, proves it is counted under
test and invisible under production, and rolls back. All APP_ENV conditions verified
in-process: unset -> dev, production -> production, staging -> refused, Railway variable
without APP_ENV -> the warning fires, with APP_ENV=production -> silent.
Consequences: The default of "dev" means a process that was never explicitly told
otherwise can never write production rows. A Railway instance deployed without APP_ENV
labels and counts only its own dev rows, so that misconfiguration is a labelling error,
not an open quota. Deploy rule, added to the checklist next to build_bm25_index.py:
migrate BEFORE deploying code, because _write_trace_safe swallows failures by design, so
a trace write against a missing column fails silently, and an uncounted call is an open
quota with no error anywhere. The label also gives the eval-validity work a clean filter:
mining query_trace WHERE environment = 'production' yields real out-of-sample questions
with no test or dev noise. Known gaps carried: the five live-stack tests spend 3 chat-model
calls plus 3 embedding calls (~$0.02) per run, measured with the class-level counter; they
are now marked @pytest.mark.live and gated behind RUN_LIVE_TESTS=1, so a plain pytest makes
zero paid calls even with a key present.
Status: Accepted.

## ADR-10: Deterministic actor prior, an advisory retrieval re-weight (2026-09-21)
Context: Enumeration-tier contamination sat at 6 after ADR-8 and did not move with breadth
or slice. All six were actor cross-cites: provider questions pulling deployer provisions
from Articles 26 and 27, and the two Article 50 transparency queries citing each other's
paragraphs (par_1/2 are provider duties, par_3/4 deployer duties). The retriever had no
notion of whose obligation a passage governs, and "obligations of providers" versus
"obligations of deployers" are near-identical in both embedding and BM25 space.
Decision: A DERIVED actor map, not a stored column. app/retrieval/actor.py labels each
provision provider / deployer / importer / distributor / authorised_representative / None,
deterministically from corpus text, with one comment per row quoting the sentence that
justifies it and a docstring listing every row deliberately left absent (art_13's
heading-keyword trap, art_4, art_25, art_62, art_8-15, enforcement articles). Points
inherit their article's label; Articles 49 and 50 are labelled per paragraph. A
conservative regex detects the query's target actor and fires only when exactly one actor
family is named; zero or two or more families make the prior a no-op. apply_actor_prior
soft-down-weights the RRF score of candidates whose non-null label mismatches the query
(factor 0.25), over the full 25-candidate list before the context slice. Nothing is
removed; None-labelled and matching chunks are untouched; rrf_score stays raw in the trace
and query_trace.retrieval_config records actor and factor on every turn. Advisory only,
and kept out of the APPROVE / REFER / DECLINE engine: grep-verified that app/classifier
and app/api/classify.py import nothing from retrieval.
Evidence: Enumeration contamination 6 -> 0, mean ctx_recall 0.817 -> 0.867, with
provider_obligations rising 0.583 -> 0.833 because the freed slots admitted three more
Article 16 points. Single-gold guard sets (easy 16, hard 35, realistic 56) did not regress
at any factor; no gold chunk was ever down-weighted; the only rank that moved was easy
gs_04, 3 -> 2 (easy MRR 0.885 -> 0.896). Factor 0.25 was chosen by Yash from a post-hoc
sweep over {1.0, 0.75, 0.5, 0.25, 0.0} on identical retrieval: it is the first factor to
clear all contamination, and 0.0 (a hard filter) produced identical numbers while
forfeiting the property that a mislabelled chunk ranked highly by both legs can still
surface. Step 2 on the live production path reproduced the sweep's 0.867 / 0 exactly.
Consequences: The residual provider_obligations misses (art_16.pt_g at fused rank 17,
pt_j at rank 35) are a retrieval-ranking ceiling, not actor confusion. Generation-side
used_contamination confirmation is deferred to a budget top-up; it is bounded above by
ctx_contamination, which is now 0. The map is human-curated and a label error is
recoverable because the prior is soft. The evidence base is small (5 enumeration queries
plus 16 actor-naming curated queries), and the detector's conservatism is what bounds the
risk on everything it has not seen. Boundary cases F1-F7 (art_13, art_43/48, art_73,
art_22/54 par_2, art_27.par_5, GPAI providers, notified bodies) are recorded in the
actor.py docstring at their approved defaults.
Status: Accepted.

## ADR-9: Evaluate Jev (TypeSafe System One) as an advisory reranker / actor classifier, out of the decision path (2026-09-21)
Context: Two open retrieval problems point at the same shape of tool. Wrong-actor
contamination (provider obligations cited for a deployer question, and the reverse) sits at
about 6 across every breadth/slice setting tested, so ADR-8 did not move it. A deterministic
actor tag derived from citation_id handles whole-article cases cleanly (art_16 is provider,
art_26 is deployer) but cannot disambiguate an intra-article actor split: Article 50 puts
provider duties in par_1/par_2 and deployer duties in par_3/par_4, all under one article id.
Jev is a cheap typed-decision classifier that fits exactly that niche, and could rerank more
generally.
Decision: Try the deterministic actor tag FIRST, because it is free, auditable and covers the
majority of cases. Only if residual contamination remains after that, run a feature-flagged
Jev experiment benchmarked on OUR corpus (RRF-only vs RRF+Jev vs RRF-fused-with-Jev), measured
against the alternatives rather than in isolation: a hosted cross-encoder (Voyage, Cohere) and
open-weights Laya. Adopt only on our own numbers.
Constraints if adopted: Jev stays ADVISORY. It may flag or down-weight a passage, never
hard-decide one, and it stays strictly out of the deterministic APPROVE / REFER / DECLINE
path. It produces no prose rationale, its weights are closed, and "cannot hallucinate" means
schema-constrained output, not correct output. Pin the version. For a regulated product,
prefer self-hostable Laya if it wins on the numbers.
Consequences: a new external dependency only if it earns its place on measured lift. Keep an
independent judge for the benchmark, so the model being selected is not also the model
grading the selection.
Status: Candidate / deferred.

## ADR-8: Retrieval candidate breadth 25, context slice 15 (2026-09-21)
Context: List-type questions were being truncated by retrieval, not by generation. A breadth
of 10 candidates cannot hold a 12-item answer, and a 5-chunk context slice cannot present one.
The enumeration tier (see Step 31) measured used_recall equal to ctx_recall at every setting
tested, which localises the ceiling precisely: the model cites everything it is handed and
invents nothing, so the loss is upstream in retrieval.
Decision: RETRIEVAL_CANDIDATE_BREADTH 10 -> 25, final_context_size 5 -> 15. RRF weights
(vector 0.4 / lexical 0.6), min_similarity 0.3 and RRF k=60 are unchanged, so this moves one
axis only and stays comparable to the ADR-7 measurements.
Evidence: enumeration mean recall 0.433 -> 0.817. Hard-set MRR 0.902 -> 0.874, judged cosmetic
rather than real because an answer-level judge showed faithfulness 4.85 -> 4.95 and relevance
flat across the same settings (see Step 32).
Consequences: per-call cost roughly triples, because the prompt now carries 15 chunks instead
of 5. config.py's daily-quota numbers were calibrated against a 5-chunk context and are owed a
recalibration before any public deploy. Wrong-actor contamination is unchanged at about 6 and
is tracked separately (ADR-9). The full judged before/after guard was deferred to a budget
top-up; validation at ship time was retrieval-only plus a static wiring proof, which confirms
the constants reach all three call sites and reproduces 0.817 on the live config, but does not
re-measure generation quality end to end.
Status: Accepted.

## ADR-7: Lexical retrieval is currently inert on real queries; calibration deferred to eval phase (2026-09-18)
Context: websearch_to_tsquery AND-joins all terms by default. Across every real query
tested (step 22 "Article 6(2)", step 23 control "credit scoring high risk", 3 off-topic
calibration queries), lexical search returned 0 results; vector search carried all retrieval.
The hybrid/RRF code is correct but dormant on real input.
Decision: Do NOT switch to OR-joining or plainto_tsquery reactively. Defer lexical
calibration to the eval phase, where a golden set will measure whether lexical actually
lifts recall/MRR and justify the query-processing choice with numbers.
Status: Deferred. Revisit with the eval harness.

Update (2026-09-19) — Wave 1 eval harness delivered the awaited evidence: a golden
set built specifically to favor lexical (4 questions on rare, verified verbatim
phrases - "subliminal techniques", "biometric categorisation system", "fundamental
rights impact assessment", "quality management system") still produced zero rank
contribution from keyword_search across all 4. Root-caused directly: keyword_search
returned 0 results for all 4, because websearch_to_tsquery AND-joins every stemmed
word in a full natural-language question (15-20 words), not just the distinctive
phrase - requiring all of them to co-occur in one short chunk is essentially
impossible regardless of how distinctive the target phrase is.
Decision: This is now a decided fork, not an open question - the lexical half as
currently built adds nothing, and the cause is query construction, not corpus
content or phrase rarity. Two options recorded for a future step (neither
implemented now):
  (a) Fix query construction - extract key terms / OR-join before
      websearch_to_tsquery, so a question's distinctive terms can match without
      requiring every scaffolding word to co-occur too.
  (b) Drop the lexical half and ship an honest vector-only retriever, removing
      the dead-weight complexity of a hybrid path that never contributes.
Status: Decided (lexical as built is inert; cause is query construction, not
corpus). Choice between (a) and (b) deferred to a later step.

Update (2026-09-20) — Stage 0 of the BM25 work built a discriminating eval set
(evals/golden_set_hard.yaml, 41 entries: 23 exact_term, 12 control, 6 abstention)
via evals/build_golden_set_hard.py, and it produced two findings that bear
directly on the (a)/(b) fork above.

1. Hard-tier lexical floor is zero. Every one of the 23 hard entries - each one a
question where vector-only ranks the gold provision at 2+ or misses it entirely -
returns 0 rows from keyword_search. Not "ranked poorly": zero rows. This reproduces
the 2026-09-19 finding on a larger, purpose-built, harder set rather than on 4
hand-picked questions, and confirms the AND-join diagnosis is the mechanism.
Consequence for measurement: on the hard tier the lexical baseline is exactly
0.000, so any Stage 1 lift is attributable to fixing query construction, not to
BM25's scoring function per se. Caveat recorded honestly: during the build, 1 of
the 25 hard candidates ("any refusal, restriction, suspension or withdrawal of a
Union technical documentation assessment certificate...") DID retrieve gold
lexically - a rare, contiguous phrase surviving the AND-join. That entry was
removed in human review for label ambiguity (gold and its rank-1 distractor were
near-identical adjacent points), not because of its lexical behaviour. So the
mechanism is overwhelmingly dominant but not absolute.

2. Negative result: near-duplicate provisions do NOT break vector search. One
standing argument for keeping lexical was that semantically near-identical sibling
provisions would confuse embeddings. Tested directly: 57 near-duplicate candidates
(difflib ratio > 0.5 within a parent), each given a question generated with the
target AND its confusable siblings in the prompt, instructed to turn on the detail
that distinguishes them. 39 passed the question-quality screen and reached
retrieval; 37 of those 39 (95%) were ranked #1 by vector-only. Only 2 survived the
rank filter and both then failed the discrimination screen. The near_duplicate tier
is therefore shipped DECLARED EMPTY - the category is retained in the schema and
the builder so the negative result stays visible, rather than deleted as if never
attempted. Interpretation: once a question actually names the distinguishing
detail, semantic search handles near-duplicates correctly; the earlier probe's
apparent failures were vague questions whose near-twin answered them equally well,
i.e. broken labels rather than retrieval weakness.
Consequence for the fork: this removes one of the motivations for option (a). It
does not decide the fork - the hard tier still shows vector-only failing 23 real
questions that lexical currently cannot help with at all.
Status: unchanged - still Decided that lexical as built is inert; choice between
(a) and (b) still deferred, now with a measuring instrument that can tell them
apart per-category.
Caveat on that instrument: the hard tier is selected adversarially against
vector-only, so vector-only's weak showing on it is a property of the sampling,
not a finding; the control tier is biased the opposite way (selected at vector
rank 1). Report per-category, never pooled.
Correction (2026-09-20, same day): an earlier draft of this paragraph said
vector-only scores "~0" on the hard tier. That is wrong as written and is
corrected here. What is 0 by construction is vector-only's *rank-1 precision*
(0 of 23 hard entries put gold first). Recall@5 is 0.870, because the hard tier
admits gold at ranks 2-5 - it excludes rank 1, not the whole top-5. Measured
baseline, hard tier, vector-only: Recall@5 0.870, MRR 0.335, nDCG@10 0.483.
The practical consequence is that Recall@5 has almost no headroom on this tier,
so a retrieval improvement shows up in MRR/nDCG rather than in Recall@5.

Update (2026-09-20, Stage 1) — The (a)/(b) fork above is now resolved with
measurements rather than argument: option (a) (fix query construction) was
implemented, measured on golden_set_hard.yaml, and REVERTED. Option (b) (drop
lexical) is not taken either. The lexical leg stays as-is on main, inert, until
Stage 2 (bm25s).

What was built: keyword_search's websearch_to_tsquery input was rewritten from
the raw question to an OR-joined string of its content words (alphanumeric
tokens, >=3 chars, minus the literal operator words or/and/not). The SQL,
ts_rank_cd ranking, GIN index, threshold (0.1) and function signature were all
unchanged - only the bound parameter differed. RRF weights were deliberately
left at 0.7/0.3 so the A/B isolated one variable.

Measured on the hard set (23 exact_term, 12 control), vector_only rows
byte-identical before/after, confirming only the lexical leg moved:
  hard tier  MRR        0.335 -> 0.590  (+76%)
  hard tier  nDCG@10    0.483 -> 0.682  (+41%)
  hard tier  gold at rank 1   0/23 -> 11/23
  hard tier  Recall@5   0.870 -> 0.783  (regression)
  control    Recall@5   1.000 -> 0.917  (regression)
  control    MRR        0.958 -> 0.917  (regression)
  default golden_set.yaml, hybrid MRR  0.896 -> 0.854  (regression)
Note the control-tier hybrid baseline was already 0.958 MRR, not 1.000: even the
inert lexical leg was perturbing one control question before any change.

Root cause of the regressions, diagnosed on the worst case (gh_27, "What
determines the duration of participation in the AI regulatory sandbox?"): the OR
query is dominated by "sandbox"/"regulatory", which match dozens of Article 57
chunks, so the lexical leg returns 10 topical-but-wrong rows and misses gold
entirely. Five of those also appear in vector's top-10, and RRF's "present in
both lists" bonus (>=0.01458) outranks gold's vector-only score (0.01148),
pushing a correct rank-1 result down to rank 6. OR-joining trades precision for
recall, and RRF amplifies lexical's false positives whenever it is confidently
wrong.
The deeper cause is that ts_rank_cd has no IDF term: it cannot know that
"sandbox" is common in this corpus while "duration" is rare, so it cannot
down-weight the words that make the OR query noisy.
Decision: revert the OR-join on main (the easy-case regression is not worth the
hard-case gain), keep the Stage 1 eval infrastructure (--hard, --retrieval-only,
per-category table, nDCG@10), and treat this as measured motivation for Stage 2:
BM25's IDF weighting is precisely the missing mechanism, and these numbers are
the baseline it must beat. Not attempted here and still open: tuning the RRF
lexical weight down from 0.3, which would blunt the false-positive amplification
but is a second variable.
Status: (a) implemented, measured, reverted. Lexical remains inert on main by
choice, with the reason now quantified rather than assumed. Stage 2 (bm25s) is
the next step.

Update (2026-09-20, Stage 2) — RESOLVED. The lexical leg is BM25, not native
FTS. Stage 1's hypothesis was that ts_rank_cd's missing IDF term caused the
precision regression; Stage 2 tested that directly by swapping in a real
IDF-weighted ranker and changing nothing else. The hypothesis held.

Implementation: bm25s==0.3.11 + PyStemmer==3.1.0 (both wheel-installed, no
source build; base bm25s needs only numpy, already present). In-process index
over the active corpus_version's chunks, persisted as a 243.6 KiB file artifact
under backend/data/bm25_index/v{id}/ - gitignored and rebuildable via
scripts/build_bm25_index.py, because it is derived data that must never drift
from the DB. Fused through the EXISTING rrf_rank_and_fuse at unchanged 0.7/0.3
weights, k=60, candidate breadth 10, so the comparison isolates the ranker.
Measured on golden_set_hard.yaml, retrieval only:

                        vector_only   Stage 1 OR-join   hybrid_bm25   bm25_only
  exact_term Recall@5      0.870           0.783           0.913        1.000
  exact_term MRR           0.335           0.590           0.703        0.913
  exact_term nDCG@10       0.483           0.682           0.757        0.936
  control    Recall@5      1.000           0.917           1.000        1.000
  control    MRR           1.000           0.917           1.000        0.833
  easy-set hybrid MRR      0.896           0.854           0.906          -

hybrid_bm25 reproduces the hard-tier ranking gain WITHOUT the precision cost
that forced the Stage 1 revert. It also repairs a pre-existing defect: the
control-tier hybrid baseline was 0.958 MRR (the inert FTS leg was perturbing
gh_26); hybrid_bm25 returns all 12 controls to rank 1. On the less-biased easy
set it beats vector-only outright (MRR 0.896 -> 0.906, nDCG 0.923 -> 0.931)
where Stage 1 had degraded it to 0.854.
Decision: ADOPT BM25 as the lexical leg. The native-FTS OR-join stays reverted.

Candidate-set fairness, checked before trusting any of the above: 1128 chunks
for the corpus_version, 1128 vector-searchable, 1128 indexed. Enforced
structurally - fetch_indexable_chunks filters embedding IS NOT NULL, the same
universe vector_search can actually reach - so BM25 can never win by seeing
documents the vector leg cannot return.

Tokenization: Snowball via PyStemmer + bm25s English stopwords, with a
protected-term passthrough. Deliberately NOT carried over from Stage 1: the
3-character token floor, which existed only to stop "AI" from diluting
ts_rank_cd. BM25 solves that automatically (a term in nearly every document
gets IDF ~ 0), so keeping the hack would have discarded distinctive short
tokens for no reason. Protected terms were chosen from a measured stem-collision
analysis, not guessed - only where stemming fuses legally DISTINCT concepts:
systemic (vs system/systems, swamped 21:1), notified + notifying (notified body
vs notifying authority), operator(s), provider(s), deployer(s). Ordinary plural
folding (model/models, importer/importers) was left alone.

Two open levers, both evidence-backed rather than speculative:
  (1) The 0.3 lexical RRF weight is now the BINDING CONSTRAINT, not an untested
      default. gh_13 and gh_16 are the two hard entries vector-only misses
      entirely; bm25_only ranks BOTH at #1; hybrid_bm25 still misses both,
      because with 0.7/0.3 a document absent from vector's top-10 scores at
      most 0.3/61 = 0.00492, below every vector hit. BM25 finds them and RRF
      discards them. Stage 3 should be a one-variable A/B on that weight.
  (2) Hybrid, not BM25-alone, is the answer. bm25_only is the strongest config
      on the hard tier (exact_term Recall@5 1.000, gold-at-rank-1 19/23) but the
      WORST on control (MRR 0.833; gh_27, gh_30, gh_34 all fall off rank 1). Its
      hard-tier dominance is substantially manufactured: that tier was built by
      selecting rare-distinctive-term provisions where vector-only fails, which
      is close to a BM25-favouring construction. The control tier is the honest
      check, and it says BM25 alone is a downgrade.
Status: RESOLVED - BM25 adopted as the lexical leg, native FTS stays reverted.
Production is still UNWIRED: generate_grounded_answer is untouched, pending the
Stage 3 weight decision. Wiring BM25 into the production path is a separate gate.

Update (2026-09-20, Stage 5) — SHIPPED. Hybrid retrieval is now the production
path: RRF at vector 0.4 / lexical 0.6, k=60, candidate breadth 10, with the BM25
leg indexing index_text (heading + body). generate_grounded_answer fuses
vector_search with bm25_search; keyword_search remains in the repo only as
run_eval's historical "hybrid" FTS reference config.

THE ROOT CAUSE, and why it took this long to find. vector_search embeds
index_text (contextual prefix + body) but the BM25 leg indexed chunk_text (body
only). That asymmetry is a violation of documented practice, not a subtle
judgement call: Anthropic's Contextual Retrieval prepends context to a chunk
"before embedding it and before creating the BM25 index" - BOTH indexes. We did
the first and not the second. The Stage 2 decision to index chunk_text was made
deliberately, for one-variable comparability with Stage 1, and explicitly
recorded as an untested lever; it turned out to be the bug.
Concretely: for "What obligations apply to providers of high-risk AI systems?",
the gold provision art_16.pt_a has a body reading only "ensure that their
high-risk AI systems are compliant with the requirements set out in Section 2;".
The query's two discriminating terms - "obligations" and "providers" - appear
ONLY in the article heading. BM25 over chunk_text ranked it nowhere in its top
50, so RRF's "present in both lists" bonus promoted topical-but-wrong chunks
over it, and the copilot ABSTAINED on a question vector-only answered. Over
index_text it ranks 2nd and is cited first.

WHY THE EVAL MISSED IT - the most transferable lesson here. Both original golden
sets generate their questions by feeding provision.text_content to an LLM
(build_golden_set.py:68, build_golden_set_hard.py:184). text_content is exactly
what chunk_text holds, so every question in those sets is guaranteed answerable
from chunk_text alone, and a heading-dependent failure CANNOT appear in them.
The sets were not merely small - they were structurally blind to this failure
class, and therefore could not help but overstate a chunk_text BM25 leg. Both
scored hybrid_bm25 as a clean win while production broke on the first realistic
query tried. The failure was found by 8 ad-hoc out-of-sample queries, not by the
harness. Lesson: an eval set generated from the same field the retriever indexes
cannot test whether that field is the right one to index.

Remedy: evals/golden_set_realistic.yaml (62 entries, built by
build_golden_set_realistic.py) - a heading-aware set with a heading_dependent
category whose questions are programmatically verified to carry terms present in
the article heading and ABSENT from the body, plus body_dependent, exact_term,
near_duplicate, control and abstention tiers. Unlike golden_set_hard.yaml it
applies NO adversarial screening, so it can rule for or against hybrid.

Measured (Recall@5 / MRR / nDCG@10), breadth 10, k=60:
                              realistic(56)      hard(35)        easy(16)
  vector_only              0.982/0.875/0.902  0.914/0.563/0.660  1.000/0.896/0.923
  hybrid@0.5 chunk_text    1.000/0.914/0.935  1.000/0.857/0.895  1.000/0.896/0.923
  hybrid@0.6 index_text    1.000/0.939/0.955  1.000/0.902/0.927  1.000/0.885/0.914
Diagnostic, heading_dependent tier, sparse leg alone: bm25_only[chunk_text]
0.867/0.783 vs bm25_only[index_text] 1.000/0.852 - chunk_text was the ONLY
config that failed to retrieve heading-dependent golds. Sibling discrimination
was NOT traded away: near_duplicate is identical at 1.000/0.875 for both sparse
legs and 1.000/1.000 for both fused configs. Weight 0.6 beat 0.5 on all three
sets independently, which is better evidence than a peak on any one set.
Honest cost: the easy set still prefers vector-only by 0.011 MRR (0.896 vs
0.885) - about one question slipping one rank out of 16, inside this corpus's
noise floor.

Rejected with evidence, not assumption:
  - Candidate breadth (10/20/30/50): closed. Never recovered art_16.pt_a at any
    depth (absent from BM25's top 50 entirely under chunk_text) and regressed
    hard-tier exact_term Recall@5 1.000 -> 0.957 at breadth 30+.
  - Field-weighted BM25 (BM25F): bm25s has no multi-field support (verified).
    The closest single-field equivalent, repeating the heading 3x, matched
    index_text on the realistic set (0.938 vs 0.939 MRR) but was worse on hard
    (0.882 vs 0.902) and carries a repetition hack. Rejected for the simpler
    option that also matches what the dense leg embeds.
  - Query router (max-IDF gate deciding vector vs hybrid per query): REJECTED.
    No threshold beat always-hybrid; >=0.0 and >=3.0 merely reproduced it and
    >=4.0/5.0/6.0 were worse. This independently reproduces 2026 findings that
    an oracle per-query weight exists but tested signals fail to localise it.
Status: SHIPPED. ADR-7 is closed.

Known gaps carried forward from Stage 5 (none blocking, all deliberate):
  (a) scripts/build_bm25_index.py MUST run on every deploy and after every
      re-ingest. If it does not, production silently serves vector_only_degraded
      - correct answers, but vector-only quality. No deploy pipeline enforces
      this yet.
  (b) The missing-index warning fires PER REQUEST, by design (a missing index
      degrades all traffic, so it should be loud). It will be noisy in that
      state - revisit the cadence once real log aggregation exists.
  (c) 5 of the 7 flagged golden_set_realistic.yaml sample entries are still
      unverified against EUR-Lex. Until then the weight-0.6 decision rests on
      LLM-generated labels. All three eval sets are LLM-generated; none is
      human-authored, so they may share a blind spot the way the first two
      shared the heading one.
  (d) load_index caches per process, so a rebuilt index is NOT picked up until
      restart. A deploy that rebuilds the index without restarting the app will
      keep serving the old one.

## ADR-006: Exact article-reference lookup is deferred to a dedicated structured path (2026-09-18)
Context: Integration testing showed "Article 6(2)" returns zero lexical results
(websearch_to_tsquery AND-splits "6(2)"; the reference lives in citation_id
metadata, not chunk_text). Hybrid retrieval solves conceptual queries, not exact
reference lookup.
Decision: Do NOT patch websearch_to_tsquery (e.g. OR-joining terms) to force a
match. Defer a dedicated reference-lookup path (detect citation pattern in query →
direct citation_id lookup) until the eval harness quantifies how often it's needed.
Status: Deferred. Revisit after golden-set exact-reference questions are graded.

## ADR-005 — Host database on Supabase (managed Postgres + pgvector) (2026-09-16)
Decision: Move from local Docker Postgres to Supabase (managed Postgres 16 + pgvector) for development. DB TYPE is unchanged — Supabase IS Postgres + pgvector; this is a hosting choice, not an architecture change.
Why: Visual table browser aids learning/inspection; same platform used in prior RAG project; cloud DB is where we'd deploy anyway. All code reads DATABASE_URL from .env, so the switch is a connection-string change.
Rejected: local Postgres + a GUI tool (valid, but chose Supabase's integrated UI + cloud-ready now). Pure vector DB (Pinecone/Qdrant) — wrong for our relational + filtering + transactional needs (see ADR rationale / interview Scenario 4).
Note: keep docker-compose.yml for offline fallback; migrations + ingestion must be re-run against Supabase.

## ADR-004 — Ingest safe subset first; defer 6 structurally-different annexes (2026-09-16)
Decision: Ingest 119 articles + 8 structurally-compatible annexes (II, III, IV, V, VI, IX, XII, XIII) now via an explicit UNSUPPORTED_ANNEXES exclusion. Build the end-to-end pipeline (chunk→embed→retrieve→copilot) on this. Add annexes I, VII, VIII, X, XI, XIV later (Step B: new section-structure parser) via re-ingestion.
Why: Get the full system proven on real data sooner; the excluded annexes use a different layout (numbered sections/decimal sub-numbering) needing a new parser capability. Gap is explicit, logged, visible on every run, and outside the v1 financial-services flagship. Corpus versioning makes re-ingestion clean.
Rejected: Path B (finish all annexes before any downstream work) — delays proving the higher-risk unknowns (retrieval quality, citation precision).
Known limitation: Annex I (product-safety high-risk route) not in corpus until Step B. Pending: Step B parentage-verified section parser.

## ADR-003 — unstructured.io reserved for v3 PDF-only corpora (2026-09-16)
Decision: Parse structured HTML directly for the AI Act (v1). Reserve an unstructured.io + summarize-visuals pipeline for v3 corpora (recitals, Irish national layer) IF those are PDF-only / contain tables or images.
Why: AI Act source is clean structured HTML with machine-readable IDs and no visual tables/images — direct parsing gives exact citations; unstructured.io would flatten structure then re-guess it.
Rejected: unstructured.io/PDF pipeline for v1 (throws away ground-truth structure; multimodal machinery unused on text-only source).

## ADR-002 — Free-standing sentences not captured as provisions (2026-09-16)
Decision: v1 parser captures articles, paragraphs, points, annex points/sub-points. Deeper nesting and free-standing sentences (e.g. Article 6 "Notwithstanding…") are preserved in parent text but not independently citable.
Why: Scope control; flagship cases (credit scoring) are covered.
Risk to monitor: verify at retrieval time that no legally-important text is silently un-retrievable (poisoned-index guard).

## ADR-001 — EUR-Lex WAF requires manual-fetch fallback (2026-09-16)
Decision: fetch_corpus.py uses a plain fetch; if EUR-Lex serves an AWS WAF challenge, fall back to manual browser download. Never script around the WAF.
Why: Bot-evasion is off-limits; provenance is preserved via content_hash regardless of fetch method.
Monitored signal: sha256 diff on re-fetch detects source change.