"""mineduc-scraper: build a structured JSON database of the Chilean national curriculum.

Source: https://www.curriculumnacional.cl (MINEDUC / Unidad de Curriculum y Evaluacion).
"""

__version__ = "2.0.0"
# 2.0.0 is a major bump because the record shape gained required-by-policy
# structure rather than optional extras: every objective now carries
# `provenance` and a `curriculum_status`, and `prioritized` is superseded by
# `prioritization`. Consumers reading 1.x fields still work; consumers that
# assumed `prioritized` meant "currently prioritized" do not, which is the
# point of the bump.
SCHEMA_VERSION = "2.0.0"
SOURCE_URL = "https://www.curriculumnacional.cl"
