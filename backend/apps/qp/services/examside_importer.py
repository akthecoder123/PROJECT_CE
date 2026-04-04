"""Helpers for importing one Examside paper into the Question table.

High-level flow:
1. Download the paper-level ``__data.json`` file from Examside.
2. Read the paper metadata and the base question list from that payload.
3. Visit one question-details endpoint per Examside batch to fetch options,
   correct answers, chapters, and explanations.
4. Replace any existing rows for the same exam/date/shift combination.
5. Bulk insert the fresh question rows into the database.
"""

import json
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from apps.qp.models import Question


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

# Keep a local copy of the raw Examside response for debugging and inspection.
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


@dataclass(frozen=True)
class PaperMetadata:
    """Normalized paper fields that we later copy onto each Question row."""

    paper_key: str
    paper_title: str
    exam_date: date | None
    shift: int
    exam_type: str


class ImageUrlParser(HTMLParser):
    """Collect every ``img`` URL from an HTML snippet."""

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return

        attr_map = dict(attrs)
        url = attr_map.get("data-orsrc") or attr_map.get("src")
        if url:
            self.urls.append(url)


def normalize_paper_url(paper_url: str) -> str:
    """Accept either a paper page URL or a ``/__data.json`` URL and normalize it."""

    clean_url = paper_url.strip().rstrip("/")
    if clean_url.endswith("/__data.json"):
        clean_url = clean_url[: -len("/__data.json")]
    return clean_url


def build_headers(referer: str) -> dict[str, str]:
    """Send browser-like headers so Examside accepts the request."""

    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": referer,
    }


def fetch_json(url: str, referer: str) -> dict[str, Any]:
    """Fetch JSON from Examside and raise a clearer error if the request fails."""

    request = Request(url, headers=build_headers(referer))
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc

    return json.loads(payload)


def write_raw_snapshot(name: str, payload: dict[str, Any]) -> None:
    """Write a prettified copy of the payload so we can inspect site changes later."""

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / name
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve(data: list[Any], value: Any) -> Any:
    """Resolve Examside's indexed references back into the actual object.

    In this payload format, many fields are stored as integers that point into
    a shared ``data`` list. If the value is already a real object/string/list,
    we return it unchanged.
    """

    if isinstance(value, int):
        return data[value]
    return value


def resolve_field(data: list[Any], obj: dict[str, Any], key: str, default: Any = None) -> Any:
    """Read ``obj[key]`` and resolve it if it is stored as a numeric reference."""

    return resolve(data, obj.get(key, default))


def find_node(root: dict[str, Any], params: list[str]) -> dict[str, Any]:
    """Pick the route node whose parameter signature matches the page we need."""

    for node in root.get("nodes", []):
        uses = node.get("uses", {})
        if isinstance(uses, dict) and uses.get("params") == params:
            return node
    raise ValueError(f"Could not find node with params {params}")


def parse_exam_date(raw_value: str | None) -> date | None:
    """Convert the Examside ISO datetime string into a Python ``date``."""

    if not raw_value:
        return None
    return date.fromisoformat(raw_value[:10])


def parse_shift(title: str) -> int:
    """Infer shift from the title.

    Current assumption:
    - titles containing ``evening`` are shift 2
    - everything else is treated as shift 1
    """

    lowered = title.lower()
    if "evening" in lowered:
        return 2
    return 1


def slug_to_title(value: str | None) -> str:
    """Turn values like ``mathematics`` or ``coordinate-geometry`` into display text."""

    if not value:
        return ""
    return value.replace("-", " ").strip().title()


def extract_paper_key(paper_url: str) -> str:
    """Extract the last URL segment, which is usually the paper slug/key."""

    path = urlparse(paper_url).path.rstrip("/")
    return path.split("/")[-1]


def extract_image_urls(html: str) -> list[str]:
    """Return unique image URLs from an HTML fragment while preserving order."""

    if not html:
        return []

    parser = ImageUrlParser()
    parser.feed(html)

    unique_urls: list[str] = []
    seen: set[str] = set()
    for url in parser.urls:
        # Examside can repeat the same image in the HTML, so we de-duplicate it.
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def extract_paper_questions(paper_url: str) -> tuple[PaperMetadata, list[dict[str, Any]]]:
    """Read the paper page and extract metadata plus the base question list.

    This first pass gives us the paper title/date/shift and the main question
    HTML for each section. It does not include full option/explanation details
    yet; that enrichment happens in a later step.
    """

    page_url = normalize_paper_url(paper_url)
    data_url = f"{page_url}/__data.json"
    root = fetch_json(data_url, referer=page_url)
    write_raw_snapshot("examside_paper_response.json", root)

    # The paper overview lives under the route:
    # /examGroup/exam/paper
    node = find_node(root, ["examGroup", "exam", "paper"])
    data = node["data"]
    top = data[0]
    paper = resolve(data, top["paper"])

    metadata = PaperMetadata(
        paper_key=resolve_field(data, paper, "key", ""),
        paper_title=resolve_field(data, paper, "title", "") or "",
        exam_date=parse_exam_date(resolve_field(data, paper, "date")),
        shift=parse_shift(resolve_field(data, paper, "title", "") or ""),
        exam_type="JEE MAIN",
    )

    questions: list[dict[str, Any]] = []
    sections = resolve(data, top["questions"])
    for section_ref in sections:
        section = resolve(data, section_ref)
        subject = slug_to_title(resolve_field(data, section, "title", ""))
        section_questions = resolve(data, section["questions"])
        for question_ref in section_questions:
            question = resolve(data, question_ref)
            question_id = resolve_field(data, question, "question_id", "")
            question_html = resolve_field(data, question, "content", "") or ""
            questions.append(
                {
                    # ``question_id`` is reused later to fetch the details page.
                    "question_id": str(question_id),
                    "subject": subject,
                    "question_text": question_html,
                    "question_image_urls": extract_image_urls(question_html),
                }
            )

    return metadata, questions


def build_question_details_url(paper_url: str, question_id: str) -> str:
    """Build the Examside details endpoint for a specific question."""

    page_url = normalize_paper_url(paper_url)
    return f"{page_url}/{question_id}/__data.json"


def resolve_options(data: list[Any], english_block: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract rendered option HTML plus image URLs from the English block."""

    raw_options = resolve(data, english_block.get("options", []))
    if not isinstance(raw_options, list):
        return []

    options: list[dict[str, Any]] = []
    for option_ref in raw_options:
        option = resolve(data, option_ref)
        if not isinstance(option, dict):
            continue
        content = resolve_field(data, option, "content", "") or ""
        options.append(
            {
                "content": content,
                "image_urls": extract_image_urls(content),
            }
        )
    return options


def resolve_correct_answer(data: list[Any], english_block: dict[str, Any]) -> str:
    """Read the answer field in the format Examside provides.

    Some questions expose ``correct_options`` as a list, while others only have
    a single ``answer`` field. We normalize both cases into one string.
    """

    correct_options = resolve(data, english_block.get("correct_options", []))
    if isinstance(correct_options, list) and correct_options:
        resolved = [str(resolve(data, item)).strip() for item in correct_options]
        return ",".join(item for item in resolved if item)

    answer = resolve(data, english_block.get("answer"))
    if answer is None:
        return ""
    return str(answer).strip()


def extract_batch_details(data: list[Any], question_refs: list[Any]) -> dict[str, dict[str, Any]]:
    """Convert one detail payload into a map keyed by question id.

    A single question-details page usually contains a batch of questions, not
    just the question whose URL we visited. We take advantage of that to enrich
    many questions at once.
    """

    details: dict[str, dict[str, Any]] = {}

    for question_ref in question_refs:
        question = resolve(data, question_ref)
        if not isinstance(question, dict):
            continue

        question_id = str(resolve_field(data, question, "question_id", "") or "")
        language_map = resolve(data, question.get("question", {}))
        if not isinstance(language_map, dict) or "en" not in language_map:
            continue

        english_block = resolve(data, language_map["en"])
        if not isinstance(english_block, dict):
            continue

        options = resolve_options(data, english_block)
        explanation = resolve_field(data, english_block, "explanation", "") or ""

        details[question_id] = {
            "chapter": slug_to_title(resolve_field(data, question, "chapter", "")),
            # The Question model stores only up to four options, so we flatten the
            # extracted options list into explicit option_a ... option_d fields.
            "option_a": options[0]["content"] if len(options) > 0 else "",
            "option_b": options[1]["content"] if len(options) > 1 else "",
            "option_c": options[2]["content"] if len(options) > 2 else "",
            "option_d": options[3]["content"] if len(options) > 3 else "",
            "option_a_image_urls": options[0]["image_urls"] if len(options) > 0 else [],
            "option_b_image_urls": options[1]["image_urls"] if len(options) > 1 else [],
            "option_c_image_urls": options[2]["image_urls"] if len(options) > 2 else [],
            "option_d_image_urls": options[3]["image_urls"] if len(options) > 3 else [],
            "correct_answer": resolve_correct_answer(data, english_block),
            "solution": explanation,
            "solution_image_urls": extract_image_urls(explanation),
        }

    return details


def enrich_questions(paper_url: str, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch detail pages and merge chapters/options/answers into each question."""

    question_map = {item["question_id"]: dict(item) for item in questions}
    processed_ids: set[str] = set()

    for question_id in list(question_map):
        # Skip any question that was already covered by a previously fetched batch.
        if question_id in processed_ids:
            continue

        details_url = build_question_details_url(paper_url, question_id)
        root = fetch_json(details_url, referer=details_url[: -len("/__data.json")])
        node = find_node(root, ["examGroup", "exam", "paper", "question"])
        data = node["data"]
        top = data[0]
        batch_question_refs = resolve(data, top["questions"])
        batch_ids = [str(resolve(data, item)) for item in resolve(data, top["ids"])]
        batch_details = extract_batch_details(data, batch_question_refs)

        for batch_id in batch_ids:
            processed_ids.add(batch_id)
            if batch_id in question_map and batch_id in batch_details:
                question_map[batch_id].update(batch_details[batch_id])

    enriched_questions = []
    for item in questions:
        enriched = question_map[item["question_id"]]
        # Some detail fields can be missing, so we make sure every DB column has
        # a predictable default before creating Question objects.
        enriched.setdefault("chapter", "")
        enriched.setdefault("option_a", "")
        enriched.setdefault("option_b", "")
        enriched.setdefault("option_c", "")
        enriched.setdefault("option_d", "")
        enriched.setdefault("question_image_urls", [])
        enriched.setdefault("option_a_image_urls", [])
        enriched.setdefault("option_b_image_urls", [])
        enriched.setdefault("option_c_image_urls", [])
        enriched.setdefault("option_d_image_urls", [])
        enriched.setdefault("correct_answer", "")
        enriched.setdefault("solution", "")
        enriched.setdefault("solution_image_urls", [])
        enriched_questions.append(enriched)

    return enriched_questions


def replace_paper_questions(paper_url: str) -> dict[str, Any]:
    """Import the paper and replace the existing DB rows for the same slot.

    Matching is currently done by ``exam_type + date + shift``. That means
    re-importing a paper for the same date/shift deletes the old questions first
    and then inserts the fresh set.
    """

    metadata, base_questions = extract_paper_questions(paper_url)
    questions = enrich_questions(paper_url, base_questions)

    # Keep only one imported paper per exam/date/shift combination.
    Question.objects.filter(
        exam_type=metadata.exam_type,
        date=metadata.exam_date,
        shift=metadata.shift,
    ).delete()

    # Build Question model instances in memory, then insert them in batches.
    records = [
        Question(
            subject=item["subject"],
            chapter=item["chapter"],
            shift=metadata.shift,
            date=metadata.exam_date,
            exam_type=metadata.exam_type,
            question_text=item["question_text"],
            option_a=item["option_a"],
            option_b=item["option_b"],
            option_c=item["option_c"],
            option_d=item["option_d"],
            question_image_urls=item["question_image_urls"],
            option_a_image_urls=item["option_a_image_urls"],
            option_b_image_urls=item["option_b_image_urls"],
            option_c_image_urls=item["option_c_image_urls"],
            option_d_image_urls=item["option_d_image_urls"],
            correct_answer=item["correct_answer"],
            solution=item["solution"],
            solution_image_urls=item["solution_image_urls"],
        )
        for item in questions
    ]
    Question.objects.bulk_create(records, batch_size=100)

    return {
        "paper_title": metadata.paper_title,
        "paper_key": metadata.paper_key,
        "count": len(records),
        "date": metadata.exam_date,
        "shift": metadata.shift,
    }
