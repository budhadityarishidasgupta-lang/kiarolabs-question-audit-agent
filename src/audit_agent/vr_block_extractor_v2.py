from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber


QUESTION_NUMBER_RE = re.compile(r"^\s*(\d(?:\s*\d)?)\s*[.)]?\s+")
EXAMPLE_RE = re.compile(r"^\s*example\b", re.IGNORECASE)
ANSWER_RE = re.compile(r"^\s*answer\b", re.IGNORECASE)
PAGE_HEADER_RE = re.compile(r"^\s*(practice paper\s+\d+|verbal reasoning)\b", re.IGNORECASE)
FOOTER_RE = re.compile(
    r"(please go on to the next page|copyright|all rights reserved|gl assessment|assessment\s+test)",
    re.IGNORECASE,
)
READ_CAREFULLY_RE = re.compile(r"^\s*read the following carefully[:.]?$", re.IGNORECASE)
INSTRUCTION_HINT_RE = re.compile(
    r"\b("
    r"in these questions|in these sentences|read the following information|"
    r"the alphabet is here to help you|these questions contain|"
    r"find the pair of words|find the two words|find this letter|mark both words|"
    r"must fit into both sets of brackets|one letter can be moved|"
    r"three of the five words are related|complete the sentence in the best way|"
    r"mean the opposite|mean the same|closest in meaning|"
    r"fill the brackets|written as a letter|what comes next|which number should replace"
    r")\b",
    re.IGNORECASE,
)
OPTION_LINE_RE = re.compile(r"^\s*([ABCDE]|[XYZ])\b", re.IGNORECASE)
NOISE_RE = re.compile(r"^[^A-Za-z0-9]{3,}$")


SECTION_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "hidden_four_letter_word",
        [
            re.compile(r"\bword of four letters is hidden\b", re.IGNORECASE),
            re.compile(r"\bhidden word\b", re.IGNORECASE),
        ],
    ),
    (
        "same_letter_brackets",
        [
            re.compile(r"\bsame letter must fit into both sets of brackets\b", re.IGNORECASE),
            re.compile(r"\bfit into both sets of brackets\b", re.IGNORECASE),
        ],
    ),
    (
        "move_one_letter",
        [
            re.compile(r"\bone letter can be moved from the first word to the second word\b", re.IGNORECASE),
            re.compile(r"\bmove one letter\b", re.IGNORECASE),
        ],
    ),
    (
        "compound_word_two_groups",
        [
            re.compile(r"\btogether make one correctly spelt word\b", re.IGNORECASE),
            re.compile(r"\bone from each group\b.*\bmake one\b", re.IGNORECASE),
        ],
    ),
    (
        "word_analogy_two_groups",
        [
            re.compile(r"\bcomplete the sentence in the best way\b", re.IGNORECASE),
            re.compile(r"\bis to\b", re.IGNORECASE),
        ],
    ),
    (
        "closest_meaning_two_groups",
        [
            re.compile(r"\bclosest in meaning\b", re.IGNORECASE),
            re.compile(r"\bmean nearly the same\b", re.IGNORECASE),
            re.compile(r"\bmean the same as\b", re.IGNORECASE),
        ],
    ),
    (
        "opposite_meaning_two_groups",
        [
            re.compile(r"\bmean the opposite\b", re.IGNORECASE),
            re.compile(r"\bopposite in meaning\b", re.IGNORECASE),
        ],
    ),
    (
        "odd_two_out",
        [
            re.compile(r"\bthree of the five words are related\b", re.IGNORECASE),
            re.compile(r"\bdo not go with these three\b", re.IGNORECASE),
        ],
    ),
    (
        "shared_synonym_two_pairs",
        [
            re.compile(r"\bone from each group\b.*\bmean nearly the same as each other\b", re.IGNORECASE),
            re.compile(r"\bshared synonym\b", re.IGNORECASE),
        ],
    ),
    (
        "bracket_word_relationship",
        [
            re.compile(r"\([^)]+\s*\[[^\]]+\]\s*[^)]+\)", re.IGNORECASE),
            re.compile(r"\bfill the brackets\b", re.IGNORECASE),
        ],
    ),
    (
        "missing_three_letters",
        [
            re.compile(r"\bthree letters\b", re.IGNORECASE),
            re.compile(r"\bmissing three letters\b", re.IGNORECASE),
        ],
    ),
    (
        "letters_as_numbers",
        [
            re.compile(r"\bif a\s*=\s*\d+", re.IGNORECASE),
            re.compile(r"\bwritten as a letter\b", re.IGNORECASE),
            re.compile(r"\bletters stand for numbers\b", re.IGNORECASE),
        ],
    ),
    (
        "number_series",
        [
            re.compile(r"\bcomes next in the series\b", re.IGNORECASE),
            re.compile(r"\bnext in the series\b", re.IGNORECASE),
            re.compile(r"\bnumber series\b", re.IGNORECASE),
        ],
    ),
    (
        "number_group_relationship",
        [
            re.compile(r"\bsame relationship\b", re.IGNORECASE),
            re.compile(r"\bnumber group\b", re.IGNORECASE),
            re.compile(r"\brelationship between\b", re.IGNORECASE),
        ],
    ),
    (
        "equation_completion",
        [
            re.compile(r"\bequation\b", re.IGNORECASE),
            re.compile(r"\bcomplete the equation\b", re.IGNORECASE),
            re.compile(r"\bwhat number\b", re.IGNORECASE),
        ],
    ),
    (
        "alphabet_letter_pairs",
        [
            re.compile(r"\bthe alphabet is here to help you\b", re.IGNORECASE),
            re.compile(r"\bpair of letters\b", re.IGNORECASE),
        ],
    ),
    (
        "alphabet_letter_series",
        [
            re.compile(r"\bthe alphabet is here to help you\b", re.IGNORECASE),
            re.compile(r"\bletter series\b", re.IGNORECASE),
            re.compile(r"\bwhat letters come next\b", re.IGNORECASE),
        ],
    ),
    (
        "letter_code",
        [
            re.compile(r"\btwo letters have been taken out\b", re.IGNORECASE),
            re.compile(r"\bmissing pair of letters\b", re.IGNORECASE),
            re.compile(r"\bwhat is the [A-Z]{2}\b"),
        ],
    ),
    (
        "logic_information",
        [
            re.compile(r"\bread the following information\b", re.IGNORECASE),
            re.compile(r"\buse the information\b", re.IGNORECASE),
            re.compile(r"\blogic\b", re.IGNORECASE),
        ],
    ),
]


@dataclass
class VrBlockV2:
    page_number: int
    block_id: str
    block_type: str
    section_type: str
    raw_text: str
    bbox: list[float]


def _normalize_spaces(text: str) -> str:
    return " ".join((text or "").replace("\x00", " ").split()).strip()


def _is_footer_line(text: str, top: float, page_height: float) -> bool:
    cleaned = _normalize_spaces(text)
    if not cleaned:
        return True
    if top > page_height - 45 and FOOTER_RE.search(cleaned):
        return True
    if cleaned.startswith("Page ") and top > page_height - 60:
        return True
    return False


def _group_words_into_lines(words: list[dict], page_height: float, y_tolerance: float = 3.0) -> list[dict]:
    if not words:
        return []

    sorted_words = sorted(words, key=lambda item: (float(item["top"]), float(item["x0"])))
    grouped: list[dict] = []

    for word in sorted_words:
        if not grouped:
            grouped.append(
                {
                    "words": [word],
                    "top": float(word["top"]),
                    "bottom": float(word["bottom"]),
                    "x0": float(word["x0"]),
                    "x1": float(word["x1"]),
                }
            )
            continue

        current = grouped[-1]
        if abs(float(word["top"]) - current["top"]) <= y_tolerance:
            current["words"].append(word)
            current["bottom"] = max(current["bottom"], float(word["bottom"]))
            current["x0"] = min(current["x0"], float(word["x0"]))
            current["x1"] = max(current["x1"], float(word["x1"]))
        else:
            grouped.append(
                {
                    "words": [word],
                    "top": float(word["top"]),
                    "bottom": float(word["bottom"]),
                    "x0": float(word["x0"]),
                    "x1": float(word["x1"]),
                }
            )

    lines: list[dict] = []
    for item in grouped:
        text = _normalize_spaces(" ".join(word["text"] for word in sorted(item["words"], key=lambda it: float(it["x0"]))))
        if not text or NOISE_RE.match(text) or _is_footer_line(text, item["top"], page_height):
            continue
        lines.append(
            {
                "text": text,
                "top": item["top"],
                "bottom": item["bottom"],
                "x0": item["x0"],
                "x1": item["x1"],
            }
        )
    return lines


def _detect_section_type(text: str) -> str:
    normalized = _normalize_spaces(text)
    if not normalized:
        return "unknown"
    for section_type, patterns in SECTION_RULES:
        if any(pattern.search(normalized) for pattern in patterns):
            return section_type
    if re.search(r"\([^)]+\s*\[[^\]]+\]\s*[^)]+\)", normalized):
        return "bracket_word_relationship"
    if re.search(r"\bIf A\s*=\s*\d+", normalized, re.IGNORECASE):
        return "letters_as_numbers"
    return "unknown"


def _classify_block(text: str, page_number: int) -> str:
    normalized = _normalize_spaces(text)
    lowered = normalized.lower()

    if not normalized:
        return "noise"

    if page_number == 1:
        if PAGE_HEADER_RE.search(normalized):
            return "cover"
        if READ_CAREFULLY_RE.search(normalized) or QUESTION_NUMBER_RE.match(normalized):
            return "instruction"
        if "do not open or turn over the page" in lowered:
            return "instruction"
        return "noise"

    if FOOTER_RE.search(normalized):
        return "footer"
    if ANSWER_RE.match(normalized):
        return "example_answer"
    if EXAMPLE_RE.match(normalized):
        return "example"
    if READ_CAREFULLY_RE.search(normalized):
        return "instruction"
    if INSTRUCTION_HINT_RE.search(normalized):
        return "instruction"
    if QUESTION_NUMBER_RE.match(normalized):
        return "question"
    if OPTION_LINE_RE.match(normalized):
        return "unknown"
    if PAGE_HEADER_RE.search(normalized):
        return "cover"
    return "unknown"


def _should_force_new_block(current_lines: list[dict], next_line: dict, page_number: int) -> bool:
    if not current_lines:
        return False

    current_text = "\n".join(line["text"] for line in current_lines)
    current_type = _classify_block(current_text, page_number)
    next_type = _classify_block(next_line["text"], page_number)
    gap = float(next_line["top"]) - float(current_lines[-1]["bottom"])

    if gap > 10:
        return True
    if next_type in {"instruction", "example", "example_answer", "question"}:
        return True
    if current_type == "question" and OPTION_LINE_RE.match(next_line["text"]):
        return True
    if current_type == "unknown" and OPTION_LINE_RE.match(next_line["text"]) and len(current_lines) >= 2:
        return True
    return False


def extract_blocks_from_pdf_v2(pdf_path: Path) -> list[VrBlockV2]:
    blocks: list[VrBlockV2] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            lines = _group_words_into_lines(
                page.extract_words(use_text_flow=False, keep_blank_chars=False, extra_attrs=[]) or [],
                page_height=float(page.height),
            )
            if not lines:
                continue

            current_lines: list[dict] = []
            block_counter = 0

            def flush() -> None:
                nonlocal current_lines, block_counter
                if not current_lines:
                    return
                block_counter += 1
                raw_text = "\n".join(line["text"] for line in current_lines).strip()
                block_type = _classify_block(raw_text, page_number)
                if block_type == "noise":
                    current_lines = []
                    return
                bbox = [
                    round(min(line["x0"] for line in current_lines), 2),
                    round(min(line["top"] for line in current_lines), 2),
                    round(max(line["x1"] for line in current_lines), 2),
                    round(max(line["bottom"] for line in current_lines), 2),
                ]
                blocks.append(
                    VrBlockV2(
                        page_number=page_number,
                        block_id=f"p{page_number:02d}-b{block_counter:03d}",
                        block_type=block_type,
                        section_type=_detect_section_type(raw_text),
                        raw_text=raw_text,
                        bbox=bbox,
                    )
                )
                current_lines = []

            for line in lines:
                if _should_force_new_block(current_lines, line, page_number):
                    flush()
                current_lines.append(line)

            flush()

    return blocks


def write_blocks_json_v2(pdf_path: Path, output_path: Path) -> dict:
    blocks = extract_blocks_from_pdf_v2(pdf_path)
    payload = {"pdf": str(pdf_path), "blocks": [asdict(block) for block in blocks]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
