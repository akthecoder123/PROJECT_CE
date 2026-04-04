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

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


@dataclass(frozen=True)
class PaperMetadata:
    paper_key: str
    paper_title: str
    exam_date: date | None
    shift: int
    exam_type: str


class ImageUrlParser(HTMLParser):
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
    clean_url = paper_url.strip().rstrip("/")
    if clean_url.endswith("/__data.json"):
        clean_url = clean_url[: -len("/__data.json")]
    return clean_url


def build_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": referer,
    }


def fetch_json(url: str, referer: str) -> dict[str, Any]:
    request = Request(url, headers=build_headers(referer))
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc

    return json.loads(payload)


def write_raw_snapshot(name: str, payload: dict[str, Any]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / name
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve(data: list[Any], value: Any) -> Any:
    if isinstance(value, int):
        return data[value]
    return value


def resolve_field(data: list[Any], obj: dict[str, Any], key: str, default: Any = None) -> Any:
    return resolve(data, obj.get(key, default))


def find_node(root: dict[str, Any], params: list[str]) -> dict[str, Any]:
    for node in root.get("nodes", []):
        uses = node.get("uses", {})
        if isinstance(uses, dict) and uses.get("params") == params:
            return node
    raise ValueError(f"Could not find node with params {params}")


def parse_exam_date(raw_value: str | None) -> date | None:
    if not raw_value:
        return None
    return date.fromisoformat(raw_value[:10])


def parse_shift(title: str) -> int:
    lowered = title.lower()
    if "evening" in lowered:
        return 2
    return 1


def slug_to_title(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("-", " ").strip().title()


def extract_paper_key(paper_url: str) -> str:
    path = urlparse(paper_url).path.rstrip("/")
    return path.split("/")[-1]


def extract_image_urls(html: str) -> list[str]:
    if not html:
        return []

    parser = ImageUrlParser()
    parser.feed(html)

    unique_urls: list[str] = []
    seen: set[str] = set()
    for url in parser.urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def extract_paper_questions(paper_url: str) -> tuple[PaperMetadata, list[dict[str, Any]]]:
    page_url = normalize_paper_url(paper_url)
    data_url = f"{page_url}/__data.json"
    root = fetch_json(data_url, referer=page_url)
    write_raw_snapshot("examside_paper_response.json", root)

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
                    "question_id": str(question_id),
                    "subject": subject,
                    "question_text": question_html,
                    "question_image_urls": extract_image_urls(question_html),
                }
            )

    return metadata, questions


def build_question_details_url(paper_url: str, question_id: str) -> str:
    page_url = normalize_paper_url(paper_url)
    return f"{page_url}/{question_id}/__data.json"


def resolve_options(data: list[Any], english_block: dict[str, Any]) -> list[dict[str, Any]]:
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
    correct_options = resolve(data, english_block.get("correct_options", []))
    if isinstance(correct_options, list) and correct_options:
        resolved = [str(resolve(data, item)).strip() for item in correct_options]
        return ",".join(item for item in resolved if item)

    answer = resolve(data, english_block.get("answer"))
    if answer is None:
        return ""
    return str(answer).strip()


def extract_batch_details(data: list[Any], question_refs: list[Any]) -> dict[str, dict[str, Any]]:
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
    question_map = {item["question_id"]: dict(item) for item in questions}
    processed_ids: set[str] = set()

    for question_id in list(question_map):
        if question_id in processed_ids:
            continue

        details_url = build_question_details_url(paper_url, question_id)
        page_url = normalize_paper_url(paper_url)
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
    metadata, base_questions = extract_paper_questions(paper_url)
    questions = enrich_questions(paper_url, base_questions)

    Question.objects.filter(
        exam_type=metadata.exam_type,
        date=metadata.exam_date,
        shift=metadata.shift,
    ).delete()

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
