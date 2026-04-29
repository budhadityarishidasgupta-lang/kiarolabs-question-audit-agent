from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.audit_agent.vr_block_extractor_v2 import extract_blocks_from_pdf_v2


QUESTION_NUMBER_RE = re.compile(r"^\s*(\d(?:\s*\d)?)\s*[.)]?\s+")
QUESTION_NUMBER_ANYWHERE_RE = re.compile(r"(?m)^\s*(\d(?:\s*\d)?)\s*[.)]?\s+")
INSTRUCTION_WORDS_RE = re.compile(
    r"\b(in these questions|in these sentences|read the following information|the alphabet is here to help you|these questions contain|example|example answer)\b",
    re.IGNORECASE,
)
OCR_NOISE_RE = re.compile(r"[ÂÃ�]|[\"']{4,}|[|]{2,}|[?]{2,}")
OPTION_LABEL_RE = re.compile(r"(?<![A-Za-z0-9])([ABCDE]|[XYZ])(?=\s)")
STANDARD_OPTION_PATTERN = re.compile(r"([A-E])\s+(.+?)(?=\s+[A-E]\s|$)")
DUAL_OPTION_PATTERN = re.compile(r"([XYZ])\s+(.+?)(?=\s+[XYZ]\s|$)")
LEADING_SYMBOLS_RE = re.compile(r"^[\'\",|`.\-:;]+")
SPACE_JOINED_DIGITS_RE = re.compile(r"\b(\d)\s+(\d)\b")
HEADER_LINE_RE = re.compile(r"^(If A =|In these questions|Read the following)", re.IGNORECASE)


SINGLE_CHOICE_SECTIONS = {
    "hidden_four_letter_word",
    "same_letter_brackets",
    "move_one_letter",
    "odd_two_out",
    "bracket_word_relationship",
    "missing_three_letters",
    "letters_as_numbers",
    "number_series",
    "number_group_relationship",
    "equation_completion",
    "alphabet_letter_pairs",
    "alphabet_letter_series",
    "letter_code",
    "logic_information",
}

TWO_GROUP_SECTIONS = {
    "compound_word_two_groups",
    "word_analogy_two_groups",
    "closest_meaning_two_groups",
    "opposite_meaning_two_groups",
    "shared_synonym_two_pairs",
}


@dataclass
class VrDraftCsvRow:
    paper_code: str
    page_number: int
    section_type: str
    question_number: str
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    option_e: str
    option_x: str
    option_y: str
    option_z: str
    correct_answer: str
    answer_source: str
    confidence: float
    needs_review: bool
    review_reason: str
    raw_block_text: str


@dataclass
class ActiveSection:
    section_type: str = "unknown"
    saw_example: bool = False
    saw_example_answer: bool = False
    instruction_text: str = ""

    @property
    def ready(self) -> bool:
        return self.saw_example_answer or self.saw_example


SECTION_OPTION_LABELS = {
    **{section: ["A", "B", "C", "D", "E"] for section in SINGLE_CHOICE_SECTIONS},
    **{section: ["A", "B", "C", "X", "Y", "Z"] for section in TWO_GROUP_SECTIONS},
}


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\x00", " ").split()).strip()


def _normalize_question_number(token: str | None) -> str:
    if not token:
        return ""
    token = SPACE_JOINED_DIGITS_RE.sub(r"\1\2", token)
    return re.sub(r"\s+", "", token)


def _question_number_from_text(text: str) -> str:
    match = QUESTION_NUMBER_RE.match(text or "")
    return _normalize_question_number(match.group(1) if match else "")


def _split_lines(text: str) -> list[str]:
    return [_normalize_text(line) for line in str(text or "").splitlines() if _normalize_text(line)]


def _looks_like_option_block(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if re.match(r"^\s*[ABCDE]\b", normalized):
        return True
    if re.match(r"^\s*[XYZ]\b", normalized):
        return True
    return False


def _clean_line(line: str) -> str:
    cleaned = _normalize_text(LEADING_SYMBOLS_RE.sub("", line or "").strip())
    cleaned = re.sub(r"^[A-Za-z]\s+", "", cleaned) if re.match(r"^[A-Za-z]\s+[A-Za-z]{3,}", cleaned) else cleaned
    if cleaned.startswith("Posters were") and "Posters were stuck" not in cleaned:
        cleaned = ""
    return cleaned


def _is_meaningful_line(line: str) -> bool:
    normalized = _normalize_text(line)
    if not normalized:
        return False
    if re.search(r"[A-Za-z]", normalized) is None and OPTION_LABEL_RE.search(normalized) is None:
        return False
    valid_words = re.findall(r"\b[A-Za-z]{2,}\b", normalized)
    if len(valid_words) < 3 and OPTION_LABEL_RE.search(normalized) is None:
        return False
    return True


def _preclean_lines(text: str) -> list[str]:
    cleaned_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        cleaned = _clean_line(raw_line)
        if not _is_meaningful_line(cleaned):
            continue
        cleaned_lines.append(_normalize_text(cleaned))
    return cleaned_lines


def _assemble_question_groups(blocks: list[dict]) -> list[tuple[dict, list[dict]]]:
    groups: list[tuple[dict, list[dict]]] = []
    idx = 0
    while idx < len(blocks):
        block = blocks[idx]
        if block["block_type"] != "question":
            idx += 1
            continue

        group = [block]
        idx += 1
        while idx < len(blocks):
            candidate = blocks[idx]
            if candidate["block_type"] in {"instruction", "example", "example_answer", "cover", "footer"}:
                break
            if candidate["block_type"] == "question" and _question_number_from_text(candidate["raw_text"]):
                break
            if candidate["block_type"] in {"unknown", "noise"} or _looks_like_option_block(candidate["raw_text"]):
                group.append(candidate)
                idx += 1
                continue
            break
        groups.append((block, group))
    return groups


def _extract_question_text_and_option_text(lines: list[str]) -> tuple[str, list[str]]:
    if not lines:
        return "", []

    question_lines: list[str] = []
    option_lines: list[str] = []
    options_started = False

    for line in lines:
        if not options_started and (
            re.match(r"^\s*[ABCDE]\b", line)
            or re.match(r"^\s*[XYZ]\b", line)
        ):
            options_started = True

        if options_started:
            option_lines.append(line)
        else:
            question_lines.append(line)

    return _normalize_text(" ".join(question_lines)), option_lines


def _extract_labeled_options(option_text: str, labels: list[str], pattern: re.Pattern[str]) -> dict[str, str]:
    values = {label: "" for label in labels}
    matches = list(pattern.finditer(option_text))
    for match in matches:
        label = match.group(1).upper()
        value = _normalize_text(match.group(2)).strip(" .,:;")
        values[label] = value
    return values


def _extract_option_values(option_text: str, allowed_labels: list[str]) -> dict[str, str]:
    values = {label: "" for label in ["A", "B", "C", "D", "E", "X", "Y", "Z"]}
    if not option_text:
        return values

    normalized_text = _normalize_text(option_text)
    anchor_labels = [label for label in allowed_labels if label in {"A", "B", "C", "D", "E"}]
    if anchor_labels:
        anchored = _extract_labeled_options(normalized_text, anchor_labels, STANDARD_OPTION_PATTERN)
        for label, value in anchored.items():
            if value:
                values[label] = value

    dual_labels = [label for label in allowed_labels if label in {"X", "Y", "Z"}]
    if dual_labels:
        anchored = _extract_labeled_options(normalized_text, dual_labels, DUAL_OPTION_PATTERN)
        for label, value in anchored.items():
            if value:
                values[label] = value

    if any(values[label] for label in allowed_labels):
        return values

    lines = _split_lines(option_text)
    pattern = re.compile(rf"(?<![A-Za-z0-9])({'|'.join(allowed_labels)})(?=\s)")

    for line in lines:
        tokens = [token for token in re.split(r"\s+", line) if token]
        normalized_tokens = [token.strip(" .,:;()[]{}") for token in tokens]

        if len(normalized_tokens) >= 2 and len(normalized_tokens) % 2 == 0 and all(
            normalized_tokens[index].upper() in allowed_labels for index in range(0, len(normalized_tokens), 2)
        ):
            for index in range(0, len(normalized_tokens), 2):
                label = normalized_tokens[index].upper()
                value = normalized_tokens[index + 1].strip(" .,:;")
                if value and not values[label]:
                    values[label] = value
            continue

        matches = list(pattern.finditer(line))
        if not matches:
            continue

        for index, match in enumerate(matches):
            label = match.group(1).upper()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            chunk = _normalize_text(line[start:end]).strip(" .,:;")
            if chunk and not values[label]:
                values[label] = chunk
    return values


def _option_contains_nested_label(value: str, labels: list[str]) -> bool:
    if not value:
        return False
    nested = re.search(rf"(?<![A-Za-z0-9])({'|'.join(labels)})(?=\s)", value)
    return nested is not None


def _validate_row(
    *,
    section_type: str,
    question_number: str,
    question_text: str,
    options: dict[str, str],
    raw_text: str,
    expected_labels: list[str],
) -> tuple[float, bool, list[str]]:
    reasons: list[str] = []
    confidence = 1.0

    if section_type == "unknown":
        reasons.append("unknown_section_type")
        confidence -= 0.25
    if not question_number:
        reasons.append("missing_question_number")
        confidence -= 0.4
    if not question_text:
        reasons.append("missing_question_text")
        confidence -= 0.25
    if INSTRUCTION_WORDS_RE.search(question_text):
        reasons.append("instruction_or_example_leak")
        confidence -= 0.35
    if OCR_NOISE_RE.search(raw_text):
        reasons.append("ocr_corruption_visible")
        confidence -= 0.2

    actual_non_empty = [label for label in expected_labels if options.get(label, "").strip()]
    if not actual_non_empty:
        reasons.append("options_missing")
        confidence -= 0.3
    elif len(actual_non_empty) != len(expected_labels):
        reasons.append("options_format_incomplete")
        confidence -= 0.2

    if any(_option_contains_nested_label(options.get(label, ""), expected_labels) for label in expected_labels):
        reasons.append("option_parsing_failed")
        confidence -= 0.3

    if any(len(re.findall(r"\b\w+\b", options.get(label, ""))) > 10 for label in expected_labels if options.get(label, "").strip()):
        reasons.append("option_parsing_failed")
        confidence -= 0.25

    question_count = len(QUESTION_NUMBER_ANYWHERE_RE.findall(raw_text))
    if question_count > 1:
        reasons.append("multiple_question_numbers_in_row")
        confidence -= 0.25

    if "Example" in raw_text or "Answer" in raw_text:
        reasons.append("example_or_answer_text_present")
        confidence -= 0.35

    if section_type == "hidden_four_letter_word" and len(actual_non_empty) != 5:
        reasons.append("option_parsing_failed")
        confidence -= 0.25
    if section_type == "letters_as_numbers" and any(
        options.get(label, "").strip() and len(_normalize_text(options.get(label, ""))) != 1 for label in expected_labels
    ):
        reasons.append("option_parsing_failed")
        confidence -= 0.25
    if section_type == "move_one_letter" and any(
        options.get(label, "").strip() and len(_normalize_text(options.get(label, ""))) != 1 for label in expected_labels
    ):
        reasons.append("option_parsing_failed")
        confidence -= 0.25
    if section_type == "word_analogy_two_groups":
        if any(not options.get(label, "").strip() for label in ["A", "B", "C", "X", "Y", "Z"]):
            reasons.append("option_parsing_failed")
            confidence -= 0.25

    confidence = max(0.0, round(confidence, 2))
    needs_review = bool(reasons) or confidence < 0.85
    return confidence, needs_review, reasons


def _parse_question_group(
    *,
    paper_code: str,
    section_type: str,
    lead_block: dict,
    group_blocks: list[dict],
) -> VrDraftCsvRow:
    combined_raw = "\n".join(block["raw_text"] for block in group_blocks).strip()
    combined_lines = _preclean_lines(combined_raw)

    if combined_lines:
        first_line = combined_lines[0]
        combined_lines[0] = QUESTION_NUMBER_RE.sub("", first_line, count=1).strip()

    question_number = _question_number_from_text(lead_block["raw_text"])
    expected_labels = SECTION_OPTION_LABELS.get(section_type, ["A", "B", "C", "D", "E"])
    question_text, option_lines = _extract_question_text_and_option_text(combined_lines)
    option_values = _extract_option_values("\n".join(option_lines), expected_labels)
    confidence, needs_review, reasons = _validate_row(
        section_type=section_type,
        question_number=question_number,
        question_text=question_text,
        options=option_values,
        raw_text=combined_raw,
        expected_labels=expected_labels,
    )

    return VrDraftCsvRow(
        paper_code=paper_code,
        page_number=int(lead_block["page_number"]),
        section_type=section_type,
        question_number=question_number,
        question_text=question_text,
        option_a=option_values["A"],
        option_b=option_values["B"],
        option_c=option_values["C"],
        option_d=option_values["D"],
        option_e=option_values["E"],
        option_x=option_values["X"],
        option_y=option_values["Y"],
        option_z=option_values["Z"],
        correct_answer="",
        answer_source="none",
        confidence=confidence,
        needs_review=needs_review,
        review_reason="; ".join(reasons),
        raw_block_text=combined_raw,
    )


def _derive_paper_code(pdf_path: Path) -> str:
    match = re.search(r"p(\d+)", pdf_path.stem, re.IGNORECASE)
    if not match:
        return pdf_path.stem.upper().replace(" ", "-")
    return f"VR-P{int(match.group(1))}"


def parse_vr_pdf(pdf_path: Path, paper_code: str | None = None) -> tuple[list[VrDraftCsvRow], dict]:
    blocks = [asdict(block) for block in extract_blocks_from_pdf_v2(pdf_path)]
    active = ActiveSection()
    candidate_blocks: list[dict] = []

    for block in blocks:
        block_type = block["block_type"]
        section_type = block["section_type"]
        if block_type in {"cover", "footer", "noise"}:
            continue
        if block["page_number"] == 1:
            continue
        if block_type == "instruction":
            if section_type != "unknown":
                active = ActiveSection(section_type=section_type, instruction_text=block["raw_text"])
            candidate_blocks.append({**block, "section_type": active.section_type})
            continue
        if block_type == "example":
            active.saw_example = True
            candidate_blocks.append({**block, "section_type": active.section_type})
            continue
        if block_type == "example_answer":
            active.saw_example_answer = True
            candidate_blocks.append({**block, "section_type": active.section_type})
            continue

        effective_section = section_type if section_type != "unknown" else active.section_type
        candidate_blocks.append({**block, "section_type": effective_section})

    rows: list[VrDraftCsvRow] = []
    for lead_block, group_blocks in _assemble_question_groups(candidate_blocks):
        if lead_block["page_number"] == 1:
            continue
        section_type = str(lead_block.get("section_type", "unknown") or "unknown")
        rows.append(
            _parse_question_group(
                paper_code=paper_code or _derive_paper_code(pdf_path),
                section_type=section_type,
                lead_block=lead_block,
                group_blocks=group_blocks,
            )
        )

    rows.sort(key=lambda row: (row.page_number, int(row.question_number or "999"), row.section_type))
    summary = {
        "paper_code": paper_code or _derive_paper_code(pdf_path),
        "pdf": str(pdf_path),
        "blocks": len(blocks),
        "rows": len(rows),
        "needs_review": sum(1 for row in rows if row.needs_review),
        "sections": sorted({row.section_type for row in rows}),
    }
    return rows, summary


def _write_csv(path: Path, rows: list[VrDraftCsvRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(VrDraftCsvRow("", 0, "", "", "", "", "", "", "", "", "", "", "", "", "none", 0.0, True, "", "")).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _write_reports(output_dir: Path, summaries: list[dict], all_rows: list[VrDraftCsvRow]) -> tuple[Path, Path]:
    report_dir = output_dir.parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    reasons: dict[str, int] = {}
    for row in all_rows:
        if not row.review_reason:
            continue
        for reason in [item.strip() for item in row.review_reason.split(";") if item.strip()]:
            reasons[reason] = reasons.get(reason, 0) + 1

    payload = {
        "papers": summaries,
        "totals": {
            "papers": len(summaries),
            "rows": len(all_rows),
            "needs_review": sum(1 for row in all_rows if row.needs_review),
            "review_reasons": reasons,
        },
    }
    json_path = report_dir / "vr_parse_latest.json"
    md_path = report_dir / "vr_parse_latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# VR Parse Latest",
        "",
        f"- Papers: {payload['totals']['papers']}",
        f"- Rows: {payload['totals']['rows']}",
        f"- Needs review: {payload['totals']['needs_review']}",
        "",
        "## Review Reasons",
        "",
    ]
    if reasons:
        lines.extend([f"- `{reason}`: {count}" for reason, count in sorted(reasons.items())])
    else:
        lines.append("- none")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_parse_vr(pdf_path: Path, paper_code: str, output_dir: Path) -> dict:
    rows, summary = parse_vr_pdf(pdf_path, paper_code=paper_code)
    output_dir.mkdir(parents=True, exist_ok=True)
    draft_path = output_dir / "vr_questions_draft.csv"
    review_path = output_dir / "vr_needs_review.csv"
    exportable_rows = [row for row in rows if not row.needs_review]
    review_rows = [row for row in rows if row.needs_review]
    _write_csv(draft_path, exportable_rows)
    _write_csv(review_path, review_rows)
    report_json, report_md = _write_reports(output_dir, [summary], rows)
    return {
        "draft_csv": str(draft_path),
        "needs_review_csv": str(review_path),
        "report_json": str(report_json),
        "report_md": str(report_md),
        "summary": summary,
        "exported_rows": len(exportable_rows),
        "review_rows": len(review_rows),
    }


def run_parse_vr_batch(input_dir: Path, output_dir: Path) -> dict:
    pdfs = sorted(input_dir.glob("Verbal Reasoning_P*.pdf"), key=lambda path: int(re.search(r"P(\d+)", path.stem, re.IGNORECASE).group(1)))
    all_rows: list[VrDraftCsvRow] = []
    summaries: list[dict] = []
    for pdf_path in pdfs:
        paper_code = _derive_paper_code(pdf_path)
        rows, summary = parse_vr_pdf(pdf_path, paper_code=paper_code)
        all_rows.extend(rows)
        summaries.append(summary)

    output_dir.mkdir(parents=True, exist_ok=True)
    draft_path = output_dir / "vr_questions_draft.csv"
    review_path = output_dir / "vr_needs_review.csv"
    exportable_rows = [row for row in all_rows if not row.needs_review]
    review_rows = [row for row in all_rows if row.needs_review]
    _write_csv(draft_path, exportable_rows)
    _write_csv(review_path, review_rows)
    report_json, report_md = _write_reports(output_dir, summaries, all_rows)
    return {
        "draft_csv": str(draft_path),
        "needs_review_csv": str(review_path),
        "report_json": str(report_json),
        "report_md": str(report_md),
        "papers": len(summaries),
        "rows": len(all_rows),
        "exported_rows": len(exportable_rows),
        "review_rows": len(review_rows),
    }


def run_review_vr(csv_path: Path) -> dict:
    rows: list[VrDraftCsvRow] = []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            rows.append(
                VrDraftCsvRow(
                    paper_code=record.get("paper_code", ""),
                    page_number=int(record.get("page_number", "0") or 0),
                    section_type=record.get("section_type", ""),
                    question_number=record.get("question_number", ""),
                    question_text=record.get("question_text", ""),
                    option_a=record.get("option_a", ""),
                    option_b=record.get("option_b", ""),
                    option_c=record.get("option_c", ""),
                    option_d=record.get("option_d", ""),
                    option_e=record.get("option_e", ""),
                    option_x=record.get("option_x", ""),
                    option_y=record.get("option_y", ""),
                    option_z=record.get("option_z", ""),
                    correct_answer=record.get("correct_answer", ""),
                    answer_source=record.get("answer_source", ""),
                    confidence=float(record.get("confidence", "0") or 0),
                    needs_review=str(record.get("needs_review", "")).lower() == "true",
                    review_reason=record.get("review_reason", ""),
                    raw_block_text=record.get("raw_block_text", ""),
                )
            )
    summaries = []
    by_paper: dict[str, list[VrDraftCsvRow]] = {}
    for row in rows:
        by_paper.setdefault(row.paper_code, []).append(row)
    for paper_code, paper_rows in sorted(by_paper.items()):
        summaries.append(
            {
                "paper_code": paper_code,
                "rows": len(paper_rows),
                "needs_review": sum(1 for row in paper_rows if row.needs_review),
                "sections": sorted({row.section_type for row in paper_rows}),
            }
        )
    output_dir = csv_path.parent
    report_json, report_md = _write_reports(output_dir, summaries, rows)
    return {
        "csv": str(csv_path),
        "report_json": str(report_json),
        "report_md": str(report_md),
        "rows": len(rows),
        "papers": len(by_paper),
    }
