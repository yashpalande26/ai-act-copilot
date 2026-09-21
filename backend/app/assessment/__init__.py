"""The assessment wedge: questionnaire -> deterministic classification ->
obligation report assembled from verbatim provision text.

No LLM anywhere in this package. Every output line is either a provision
quoted from the corpus (with its citation_id) or a short sentence of the
tool's own, which the report labels as commentary. See
docs/PRODUCT_STRATEGY.md and the plan of 21 Sep 2026.
"""
