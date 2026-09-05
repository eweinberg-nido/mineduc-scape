"""Static taxonomy: curriculum bases, grade levels, tracks and ID abbreviations.

Everything here is a pure, deterministic mapping over the URL slugs published by
curriculumnacional.cl, so the generated canonical IDs are stable across runs.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Dict, List, NamedTuple, Optional

TRACK_COMMON = "plan_comun"
TRACK_HC = "plan_diferenciado_hc"
TRACK_TP = "plan_diferenciado_tp"


class Level(NamedTuple):
    level_id: str
    level_name: str
    token: str  # short form used inside canonical OA ids, e.g. "34M" -> "1M"
    cli: str  # token accepted by --levels
    order: int


# grade slug (last URL segment of a subject page) -> level
LEVELS: Dict[str, Level] = {
    "sc-sala-cuna": Level("sala_cuna", "Sala Cuna", "SC", "SC", 1),
    "nm-nivel-medio": Level("nivel_medio", "Nivel Medio", "NM", "NM", 2),
    "nt-nivel-transicion": Level("nivel_transicion", "Nivel de Transición", "NT", "NT", 3),
    "1-basico": Level("1_basico", "1° Básico", "1B", "1B", 11),
    "2-basico": Level("2_basico", "2° Básico", "2B", "2B", 12),
    "3-basico": Level("3_basico", "3° Básico", "3B", "3B", 13),
    "4-basico": Level("4_basico", "4° Básico", "4B", "4B", 14),
    "5-basico": Level("5_basico", "5° Básico", "5B", "5B", 15),
    "6-basico": Level("6_basico", "6° Básico", "6B", "6B", 16),
    "7-basico": Level("7_basico", "7° Básico", "7B", "7B", 17),
    "8-basico": Level("8_basico", "8° Básico", "8B", "8B", 18),
    "1-medio": Level("1_medio", "1° Medio", "1M", "1M", 21),
    "2-medio": Level("2_medio", "2° Medio", "2M", "2M", 22),
    "3-medio-fg": Level("3_medio", "3° Medio", "3M", "3M", 23),
    "3-medio-hc": Level("3_medio", "3° Medio", "3M", "3M", 23),
    "3-medio-tp": Level("3_medio", "3° Medio", "3M", "3M", 23),
    "4-medio-fg": Level("4_medio", "4° Medio", "4M", "4M", 24),
    "4-medio-hc": Level("4_medio", "4° Medio", "4M", "4M", 24),
    "4-medio-tp": Level("4_medio", "4° Medio", "4M", "4M", 24),
    "nivel-1-educacion-basica-1o-4o-ano-basico": Level(
        "epja_n1_basica", "EPJA Nivel 1 Educación Básica (1° a 4° Básico)", "E1B", "E1B", 31
    ),
    "nivel-2-educacion-basica-5o-6o-ano-basico": Level(
        "epja_n2_basica", "EPJA Nivel 2 Educación Básica (5° y 6° Básico)", "E2B", "E2B", 32
    ),
    "nivel-3-educacion-basica-7o-8o-ano-basico": Level(
        "epja_n3_basica", "EPJA Nivel 3 Educación Básica (7° y 8° Básico)", "E3B", "E3B", 33
    ),
    "nivel-1-educacion-media-1-2-ano-medio": Level(
        "epja_n1_media", "EPJA Nivel 1 Educación Media (1° y 2° Medio)", "E1M", "E1M", 34
    ),
    "nivel-2-educacion-media-3-4-ano-medio": Level(
        "epja_n2_media", "EPJA Nivel 2 Educación Media (3° y 4° Medio)", "E2M", "E2M", 35
    ),
}

# Levels that no single subject page publishes, because the Bases define them.
#
# The EPJA 2024 Bases scope the Formación Instrumental and Formación
# Diferenciada Humanístico-Científica subjects to "Educación Media / Nivel 1 y
# 2" as one block, while the site navigates them under a Nivel 1 page and a
# Nivel 2 page. Forcing those objectives into either page would assert a level
# split the Bases do not make, and writing them into both would double every
# statement. They get their own combined level instead, with `level_scope` on
# each objective naming the two site levels it applies to.
SYNTHETIC_LEVELS: Dict[str, Level] = {
    "epja_media": Level(
        "epja_media",
        "EPJA Educación Media (Niveles 1 y 2)",
        "EM",
        "EM",
        36,
    ),
}

# --levels group aliases
LEVEL_GROUPS: Dict[str, List[str]] = {
    "ALL": [],  # filled below
    "PARV": ["SC", "NM", "NT"],
    "BASICA": ["1B", "2B", "3B", "4B", "5B", "6B", "7B", "8B"],
    "MEDIA": ["1M", "2M", "3M", "4M"],
    "EPJA": ["E1B", "E2B", "E3B", "E1M", "E2M", "EM"],
    # convenience alias for the SPEC.md example: 7° Básico .. 4° Medio
    "SECUNDARIA": ["7B", "8B", "1M", "2M", "3M", "4M"],
}
LEVEL_GROUPS["ALL"] = sorted(
    {lvl.cli for lvl in LEVELS.values()} | {lvl.cli for lvl in SYNTHETIC_LEVELS.values()}
)

# curriculum base slug -> human readable name
BASES: Dict[str, str] = {
    "educacion-parvularia": "Bases Curriculares de Educación Parvularia",
    "1o-6o-basico": "Bases Curriculares de 1° a 6° Básico",
    "7o-basico-2o-medio": "Bases Curriculares de 7° Básico a 2° Medio",
    "3o-4o-medio": "Bases Curriculares de 3° y 4° Medio",
    "3o-4o-medio-tecnico-profesional": "Bases Curriculares de 3° y 4° Medio Técnico Profesional",
    "bases-curriculares-educacion-personas-jovenes-adultas-epja": (
        "Bases Curriculares de Educación de Personas Jóvenes y Adultas (EPJA)"
    ),
    "bases-curriculares-lengua-cultura-pueblos-originarios-ancestrales-1-6-ano-basico": (
        "Bases Curriculares de Lengua y Cultura de los Pueblos Originarios Ancestrales "
        "(1° a 6° Básico)"
    ),
}

# Short, unique token per subject slug, used inside canonical OA ids.
#
# Frozen on purpose: ids must stay stable across runs and must not depend on
# which levels a given run happened to scrape. Generated once from the site's
# full subject list (`/curriculum/ambitos-y-asignaturas`) and verified injective
# by tests/test_normalize.py; the core national subjects were set by hand so
# they read the way MINEDUC codes do (MAT, LEN, HIS, ...). Subjects that appear
# on the site later fall through to `derive_abbrev`, which appends a stable
# slug hash so a new speciality can never collide with an existing token.
SUBJECT_ABBREV: Dict[str, str] = {
    "ambiente-sostenibilidad": "AMSS",
    "artes-visuales": "ARV",
    "artes-visuales-audiovisuales-multimediales": "ARVSADML",
    "bienestar-salud": "BNSL",
    "biologia-celular-molecular": "BLCLML",
    "biologia-ecosistemas": "BLEC",
    "chile-region-latinoamericana": "CHRGLT",
    "ciencias-ejercicio-fisico-deportivo": "CNEJFSDP",
    "ciencias-naturales": "CNA",
    "ciencias-salud": "CNSL",
    "comprension-historica-presente": "CMHSPR",
    "comunicacion-integral": "CINT",
    "creacion-composicion-musical": "CRCMMS",
    "danza": "DNZ",
    "desarrollo-personal-social": "DPS",
    "diseno-arquitectura": "DSAR",
    "economia-sociedad": "ECSC",
    "educacion-ciudadana-3-medio": "EDCD3MD",
    "educacion-ciudadana-4-medio": "EDCD4MD",
    "educacion-financiera": "EDFN",
    "educacion-fisica-salud": "EFI",
    "educacion-fisica-salud-1": "EDFSSL1",
    "educacion-fisica-salud-2": "EDFSSL2",
    "emprendimiento-empleabilidad": "EMEM",
    "especialidad-acuicultura": "ACC",
    "especialidad-administracion": "ADM",
    "especialidad-administracion-mencion-logistica": "ADMNLG",
    "especialidad-administracion-mencion-recursos-humanos": "ADMNRCHM",
    "especialidad-agropecuaria": "AGR",
    "especialidad-agropecuaria-mencion-agricultura": "AGMNAG",
    "especialidad-agropecuaria-mencion-pecuaria": "AGMNPC",
    "especialidad-agropecuaria-mencion-vitivinicola": "AGMNVT",
    "especialidad-asistencia-geologia": "ASGL",
    "especialidad-atencion-enfermeria": "ATEN",
    "especialidad-atencion-enfermeria-mencion-adulto": "ATENMNAD",
    "especialidad-atencion-enfermeria-mencion-enfermeria": "ATENMNEN",
    "especialidad-atencion-parvulos": "ATPR",
    "especialidad-conectividad-redes": "CNRD",
    "especialidad-construccion": "CNS",
    "especialidad-construccion-mencion-edificacion": "CNMNED",
    "especialidad-construccion-mencion-obras-viales-infraestructura": "CNMNOBVLIN",
    "especialidad-construccion-mencion-terminaciones-construccion": "CNMNTRCN",
    "especialidad-construcciones-metalicas": "CNMT",
    "especialidad-contabilidad": "CNT",
    "especialidad-dibujo-tecnico": "DBTC",
    "especialidad-elaboracion-industrial-alimentos": "ELINAL",
    "especialidad-electricidad": "ELC",
    "especialidad-electronica": "ELCT",
    "especialidad-explotacion-minera": "EXMN",
    "especialidad-forestal": "FRS",
    "especialidad-gastronomia": "GST",
    "especialidad-gastronomia-mencion-cocina": "GSMNCC",
    "especialidad-gastronomia-mencion-pasteleria-reposteria": "GSMNPSRP",
    "especialidad-grafica": "GRF",
    "especialidad-instalaciones-sanitarias": "INSN",
    "especialidad-mecanica-automotriz": "MCAT",
    "especialidad-mecanica-industrial": "MCIN",
    "especialidad-mecanica-industrial-mencion-mantenimiento-electromecanico": "MCINMNMNEL",
    "especialidad-mecanica-industrial-mencion-maquinas-herramientas": "MCINMNMQHR",
    "especialidad-mecanica-industrial-mencion-matriceria": "MCINMNMT",
    "especialidad-mecanica-mantenimiento-aeronaves": "MCMNAR",
    "especialidad-metalurgica-extractiva": "MTEX",
    "especialidad-montaje-industrial": "MNIN",
    "especialidad-muebles-terminaciones-madera": "MBTRMD",
    "especialidad-operaciones-portuarias": "OPPR",
    "especialidad-pesqueria": "PSQ",
    "especialidad-programacion": "PRG",
    "especialidad-quimica-industrial": "QMIN",
    "especialidad-quimica-industrial-mencion-laboratorio-quimico": "QMINMNLBQM",
    "especialidad-quimica-industrial-mencion-planta-quimica": "QMINMNPLQM",
    "especialidad-refrigeracion-climatizacion": "RFCL",
    "especialidad-servicios-hoteleria": "SRHT",
    "especialidad-servicios-turismo": "SRTR",
    "especialidad-telecomunicaciones": "TLC",
    "especialidad-tripulacion-naves-mercantes-especiales": "TRNVMRES",
    "especialidad-vestuario-confeccion-textil": "VSCNTX",
    "estetica": "EST",
    "expresion-corporal": "EXCR",
    "filosofia": "FIL",
    "filosofia-3-medio": "FL3MD",
    "filosofia-4o-medio": "FL4MD",
    "filosofia-politica": "FLPL",
    "fisica": "FIS",
    "geografia-territorio-desafios-socioambientales": "GGTRDSSC",
    "geometria-3d": "GM3D",
    "historia-geografia-ciencias-sociales": "HIS",
    "ingles": "ING",
    "ingles-3o-medio": "IN3MD",
    "ingles-4o-medio": "IN4MD",
    "ingles-propuesta": "INGP",
    "interaccion-comprension-entorno": "ICE",
    "interpretacion-creacion-danza": "INCRDN",
    "interpretacion-creacion-teatro": "INCRTT",
    "interpretacion-musical": "INMS",
    "lectura-escritura-especializadas": "LCESES",
    "lengua-cultura-pueblos-originarios-ancestrales": "LCPO",
    "lengua-indigena": "LIND",
    "lengua-literatura": "LYL",
    "lengua-literatura-3o-medio": "LNLT3MD",
    "lengua-literatura-4o-medio": "LNLT4MD",
    "lenguaje-comunicacion": "LEN",
    "limites-derivadas-integrales": "LMDRIN",
    "matematica": "MAT",
    "matematica-3o-medio": "MT3MD",
    "matematica-4o-medio": "MT4MD",
    "mundo-global": "MNGL",
    "musica": "MUS",
    "orientacion": "ORI",
    "participacion-argumentacion-democracia": "PRARDM",
    "pensamiento-computacional": "PNCM",
    "pensamiento-computacional-programacion": "PNCMPR",
    "probabilidades-estadistica-descriptiva-inferencial": "PRESDSIN",
    "promocion-estilos-vida-activos-saludables": "PRESVDACSL",
    "quimica": "QUI",
    "religion": "REL",
    "responsabilidad-personal-social": "RSPRSC",
    "seguridad-prevencion-autocuidado": "SGPRAT",
    "seminario-filosofia": "SMFL",
    "taller-literatura": "TLLT",
    "teatro": "TTR",
    "tecnologia": "TEC",
    "tecnologia-sociedad": "TCSC",
}

CATEGORY_CONOCIMIENTO = "conocimiento"
CATEGORY_HABILIDAD = "habilidad"
CATEGORY_ACTITUD = "actitud"

CATEGORY_TOKEN = {
    CATEGORY_CONOCIMIENTO: "OA",
    CATEGORY_HABILIDAD: "OAH",
    CATEGORY_ACTITUD: "OAA",
}

# h3 anchor id prefix -> curricular dimension label used by the site
STRAND_KINDS = {
    "eje": "Eje",
    "ncleo": "Núcleo",
    "nucleo": "Núcleo",
    "habilidad": "Habilidad",
    "actitud": "Actitud",
    "modulo": "Módulo",
    "ambito": "Ámbito",
    "unidad": "Unidad",
}


def strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def slugify(text: str, sep: str = "_") -> str:
    """Deterministic ASCII slug used for subject_id / strand ids."""
    ascii_text = strip_accents(text).lower()
    ascii_text = re.sub(r"[^a-z0-9]+", sep, ascii_text)
    return ascii_text.strip(sep)


def derive_abbrev(slug: str, length: int = 4) -> str:
    """Derive a short uppercase abbreviation from a slug, deterministically.

    Multi-word slugs use the initials of each word; single words are squeezed
    by dropping vowels after the first character. Used for strand tokens, and
    as the base of the fallback subject token.
    """
    words = [w for w in re.split(r"[^a-z0-9]+", strip_accents(slug).lower()) if w]
    if not words:
        return "XXX"
    if len(words) > 1:
        initials = "".join(w[0] for w in words)[:length]
        return initials.upper()
    word = words[0]
    squeezed = word[0] + re.sub(r"[aeiou]", "", word[1:])
    return (squeezed if len(squeezed) >= 3 else word)[:length].upper()


def slug_fingerprint(slug: str, length: int = 4) -> str:
    """Short, stable, uppercase fingerprint of a slug.

    Depends only on the slug, so it is identical no matter what else is being
    scraped -- which is what keeps the fallback subject token collision-proof
    without any global knowledge.
    """
    digest = hashlib.sha1(slug.encode("utf-8")).digest()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1 lookalikes
    value = int.from_bytes(digest[:8], "big")
    out = []
    for _ in range(length):
        value, index = divmod(value, len(alphabet))
        out.append(alphabet[index])
    return "".join(out)


def subject_abbrev(subject_slug: str) -> str:
    """Return the frozen token for a subject, or a collision-proof fallback."""
    if subject_slug in SUBJECT_ABBREV:
        return SUBJECT_ABBREV[subject_slug]
    # A subject published after this map was frozen. "especialidad-" prefixes
    # are dropped so the token describes the trade, and a slug fingerprint is
    # appended so the new token cannot collide with a frozen one.
    trimmed = re.sub(r"^especialidad[-_]", "", subject_slug)
    return f"{derive_abbrev(trimmed, 5)}{slug_fingerprint(subject_slug)}"


def track_for(base_slug: str, grade_slug: str) -> str:
    if base_slug == "3o-4o-medio-tecnico-profesional" or grade_slug.endswith("-tp"):
        return TRACK_TP
    if grade_slug.endswith("-hc"):
        return TRACK_HC
    return TRACK_COMMON


def level_for(grade_slug: str) -> Optional[Level]:
    return LEVELS.get(grade_slug)


def resolve_level_tokens(tokens: List[str]) -> List[str]:
    """Expand a --levels list (tokens and/or group aliases) into CLI tokens."""
    resolved: List[str] = []
    known = set(LEVEL_GROUPS["ALL"])
    for raw in tokens:
        token = raw.strip().upper()
        if not token:
            continue
        if token in LEVEL_GROUPS:
            resolved.extend(LEVEL_GROUPS[token])
        elif token in known:
            resolved.append(token)
        else:
            raise ValueError(
                f"unknown level token {raw!r}; valid tokens: "
                f"{', '.join(LEVEL_GROUPS['ALL'])} "
                f"or groups: {', '.join(k for k in LEVEL_GROUPS if k != 'ALL')}"
            )
    # stable, de-duplicated
    seen, out = set(), []
    for token in resolved:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


# --------------------------------------------------------------------------- #
# Curriculum status
# --------------------------------------------------------------------------- #
# A live page and a recent scrape date say nothing about whether a curriculum is
# legally in force, so status is never inferred from either. Every value other
# than `desconocido` has to be backed by an official source recorded alongside
# it (`status_source`), which is why `desconocido` is the default rather than
# `vigente`.
STATUS_VIGENTE = "vigente"
STATUS_PROPUESTA = "propuesta"
STATUS_EN_IMPLEMENTACION = "en_implementacion"
STATUS_HISTORICO = "historico"
STATUS_DESCONOCIDO = "desconocido"

CURRICULUM_STATUSES = (
    STATUS_VIGENTE,
    STATUS_PROPUESTA,
    STATUS_EN_IMPLEMENTACION,
    STATUS_HISTORICO,
    STATUS_DESCONOCIDO,
)

STATUS_LABEL: Dict[str, str] = {
    STATUS_VIGENTE: "Vigente",
    STATUS_PROPUESTA: "Propuesta",
    STATUS_EN_IMPLEMENTACION: "En implementación",
    STATUS_HISTORICO: "Histórico",
    STATUS_DESCONOCIDO: "Estado no verificado",
}

# Where an objective's text was read from. Kept distinct from the *document*
# so a coverage report can tell "the ministry publishes nothing here" apart
# from "a parser could not read what the ministry publishes".
SOURCE_HTML = "html_curriculum_page"
SOURCE_JSONAPI = "jsonapi"
SOURCE_BASE_PDF = "base_curricular_pdf"
SOURCE_PROGRAMA_PDF = "programa_estudio_pdf"

SOURCE_TYPES = (SOURCE_HTML, SOURCE_JSONAPI, SOURCE_BASE_PDF, SOURCE_PROGRAMA_PDF)

# EPJA ámbitos de formación, as the 2024 Bases name them. These are a real part
# of the EPJA structure -- an asignatura belongs to exactly one -- so they are
# carried on the subject rather than folded into `track`.
EPJA_FORMACION_GENERAL = "formacion_general"
EPJA_FORMACION_INSTRUMENTAL = "formacion_instrumental"
EPJA_FORMACION_DIFERENCIADA_HC = "formacion_diferenciada_hc"
EPJA_FORMACION_DIFERENCIADA_TP = "formacion_diferenciada_tp"

EPJA_FORMACION_LABEL: Dict[str, str] = {
    EPJA_FORMACION_GENERAL: "Formación General",
    EPJA_FORMACION_INSTRUMENTAL: "Formación Instrumental",
    EPJA_FORMACION_DIFERENCIADA_HC: "Formación Diferenciada Humanístico-Científica",
    EPJA_FORMACION_DIFERENCIADA_TP: "Formación Diferenciada Técnico-Profesional",
}


def level_by_id(level_id: str) -> Optional[Level]:
    """Look a level up by its ``level_id``, including the synthetic ones."""
    for level in LEVELS.values():
        if level.level_id == level_id:
            return level
    return SYNTHETIC_LEVELS.get(level_id)


def known_level_ids() -> set:
    """Every level_id the taxonomy recognises, site-published or synthetic."""
    return {lvl.level_id for lvl in LEVELS.values()} | set(SYNTHETIC_LEVELS)
