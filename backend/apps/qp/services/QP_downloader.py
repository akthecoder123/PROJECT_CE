import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
PARSE_FILE = DATA_DIR / "mathango_parse.json"
LINKS_FILE = DATA_DIR / "mathango_links.json"
PDF_DIR = DATA_DIR / "pdfs"

MONTH_ORDER = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

INVALID_FILE_CHARS = re.compile(r'[<>:"/\\|?*]+')
DRIVE_FILE_RE = re.compile(r"/file/d/([a-zA-Z0-9_-]+)")
DRIVE_ID_QUERY_RE = re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")


@dataclass(frozen=True)
class PaperRecord:
    paper: str
    link: str
    year: int
    month: str | None = None
    day: int | None = None
    shift: str | None = None
    mode: str | None = None
    details: str | None = None

    @property
    def month_number(self) -> int:
        return MONTH_ORDER.get(self.month or "", 99)

    @property
    def session_label(self) -> str:
        parts = []
        if self.day is not None and self.month:
            parts.append(f"{self.day:02d} {self.month}")
        elif self.month:
            parts.append(self.month)

        if self.shift:
            parts.append(f"Shift {self.shift}")

        if self.mode:
            parts.append(self.mode)

        return " | ".join(parts) if parts else "General"

    @property
    def folder_path(self) -> Path:
        folder = PDF_DIR / str(self.year)
        if self.month:
            folder = folder / self.month
        return folder

    @property
    def filename(self) -> str:
        clean_name = INVALID_FILE_CHARS.sub("", self.paper).strip()
        return f"{clean_name}.pdf"


def mathango_scrape() -> None:
    url = "https://www.mathongo.com/iit-jee/jee-main-previous-year-question-paper"
    response = requests.get(url, timeout=15)
    if response.status_code != 200:
        print("Error fetching the page")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    data = []

    for table in soup.find_all("table", class_=""):
        rows = table.find_all("tr")[1:]
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            paper_name = cols[1].get_text(strip=True)
            link_tag = cols[2].find("a")
            if link_tag and link_tag.get("href"):
                data.append({"paper": paper_name, "link": link_tag["href"]})

    PARSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PARSE_FILE.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(data)} scraped links to {PARSE_FILE}")


def link_converter() -> None:
    if not PARSE_FILE.exists():
        print(f"Missing source file: {PARSE_FILE}")
        return

    data = json.loads(PARSE_FILE.read_text(encoding="utf-8"))
    new_links = []
    session = requests.Session()
    total_links = len(data)

    for index, item in enumerate(data, start=1):
        url = item["link"]
        print(f"[{index}/{total_links}] Resolving {item['paper']}")

        response = None
        for attempt in range(1, 4):
            try:
                response = session.get(url, timeout=15)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 3:
                    print(f"Skipping {url}: {exc}")
                    break
                print(f"Retrying {url} ({attempt}/3): {exc}")

        if response is None:
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        meta_tag = soup.find("meta", property="og:url")
        if not meta_tag or not meta_tag.get("content"):
            print(f"Skipping {url}: og:url not found")
            continue

        new_links.append(
            {
                "paper": item["paper"],
                "link": meta_tag["content"].split("?", 1)[0],
            }
        )

    LINKS_FILE.write_text(
        json.dumps(new_links, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved {len(new_links)} resolved links to {LINKS_FILE}")


def parse_paper_record(item: dict) -> PaperRecord:
    paper = item["paper"].strip()
    link = item["link"].strip()

    year_match = re.search(r"JEE Main (\d{4})", paper)
    if not year_match:
        raise ValueError(f"Could not parse year from: {paper}")
    year = int(year_match.group(1))

    details_match = re.search(r"\((.*?)\)", paper)
    details = details_match.group(1).strip() if details_match else None

    day = None
    month = None
    shift = None
    mode = None

    if details:
        date_match = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})\b", details)
        if date_match:
            day = int(date_match.group(1))
            parsed_month = date_match.group(2).title()
            if parsed_month in MONTH_ORDER:
                month = parsed_month

        shift_match = re.search(r"\bShift\s+(\d+)\b", details)
        if shift_match:
            shift = shift_match.group(1)

        if "Online" in details:
            mode = "Online"
        elif "Offline" in details:
            mode = "Offline"

    return PaperRecord(
        paper=paper,
        link=link,
        year=year,
        month=month,
        day=day,
        shift=shift,
        mode=mode,
        details=details,
    )


def load_papers() -> list[PaperRecord]:
    if not LINKS_FILE.exists():
        raise FileNotFoundError(f"Missing links file: {LINKS_FILE}")

    raw_items = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
    papers = [parse_paper_record(item) for item in raw_items]
    return sorted(
        papers,
        key=lambda paper: (-paper.year, paper.month_number, paper.day or 0, paper.shift or "", paper.paper),
    )


def filter_papers(
    papers: Iterable[PaperRecord],
    years: set[int] | None = None,
    months: set[str] | None = None,
) -> list[PaperRecord]:
    filtered = []
    normalized_months = {month.title() for month in months} if months else None

    for paper in papers:
        if years and paper.year not in years:
            continue
        if normalized_months and paper.month not in normalized_months:
            continue
        filtered.append(paper)

    return filtered


def parse_selection_input(raw_value: str, max_index: int) -> list[int]:
    cleaned = raw_value.strip().lower()
    if not cleaned:
        raise ValueError("Please enter a value.")
    if cleaned == "all":
        return list(range(1, max_index + 1))

    selected_indexes: set[int] = set()
    for chunk in raw_value.split(","):
        token = chunk.strip()
        if not token:
            continue

        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if start > end:
                start, end = end, start
            if start < 1 or end > max_index:
                raise ValueError(f"Range {token} is out of bounds.")
            selected_indexes.update(range(start, end + 1))
            continue

        value = int(token)
        if value < 1 or value > max_index:
            raise ValueError(f"Selection {value} is out of bounds.")
        selected_indexes.add(value)

    if not selected_indexes:
        raise ValueError("Please choose at least one item.")

    return sorted(selected_indexes)


def extract_drive_file_id(link: str) -> str | None:
    match = DRIVE_FILE_RE.search(link)
    if match:
        return match.group(1)

    match = DRIVE_ID_QUERY_RE.search(link)
    if match:
        return match.group(1)

    return None


def build_direct_download_url(link: str) -> str:
    file_id = extract_drive_file_id(link)
    if not file_id:
        return link
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def fetch_download_response(session: requests.Session, link: str) -> requests.Response:
    file_id = extract_drive_file_id(link)
    response = session.get(build_direct_download_url(link), stream=True, timeout=30)

    if not file_id:
        response.raise_for_status()
        return response

    warning_token = next(
        (value for key, value in response.cookies.items() if key.startswith("download_warning")),
        None,
    )
    if warning_token:
        response.close()
        response = session.get(
            "https://drive.google.com/uc",
            params={"export": "download", "confirm": warning_token, "id": file_id},
            stream=True,
            timeout=30,
        )

    response.raise_for_status()
    return response


def write_response_to_file(response: requests.Response, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as file_handle:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if chunk:
                file_handle.write(chunk)


def download_papers(
    papers: Iterable[PaperRecord],
    skip_existing: bool = True,
) -> dict[str, int]:
    selected_papers = list(papers)
    if not selected_papers:
        print("No papers matched your selection.")
        return {"downloaded": 0, "skipped": 0, "failed": 0}

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    totals = {"downloaded": 0, "skipped": 0, "failed": 0}

    for index, paper in enumerate(selected_papers, start=1):
        destination = paper.folder_path / paper.filename
        print(f"[{index}/{len(selected_papers)}] {paper.paper}")

        if skip_existing and destination.exists():
            print(f"  Skipping existing file: {destination}")
            totals["skipped"] += 1
            continue

        try:
            response = fetch_download_response(session, paper.link)
            write_response_to_file(response, destination)
            response.close()
            print(f"  Saved to {destination}")
            totals["downloaded"] += 1
        except requests.RequestException as exc:
            print(f"  Failed: {exc}")
            totals["failed"] += 1

    print(
        "Finished download run: "
        f"{totals['downloaded']} downloaded, "
        f"{totals['skipped']} skipped, "
        f"{totals['failed']} failed."
    )
    return totals


def pdf_downloader() -> dict[str, int]:
    return download_papers(load_papers())


def print_collection_summary(papers: list[PaperRecord]) -> None:
    year_counts: dict[int, int] = {}
    for paper in papers:
        year_counts[paper.year] = year_counts.get(paper.year, 0) + 1

    print("\nAvailable question papers")
    print("-" * 28)
    for year in sorted(year_counts, reverse=True):
        print(f"{year}: {year_counts[year]} papers")
    print(f"Total: {len(papers)} papers\n")


def build_year_options(papers: list[PaperRecord]) -> list[tuple[str, int]]:
    year_counts: dict[int, int] = {}
    for paper in papers:
        year_counts[paper.year] = year_counts.get(paper.year, 0) + 1
    return [(f"{year} ({count} papers)", year) for year, count in sorted(year_counts.items(), reverse=True)]


def build_month_options(papers: list[PaperRecord]) -> list[tuple[str, str]]:
    month_counts: dict[str, int] = {}
    for paper in papers:
        if paper.month:
            month_counts[paper.month] = month_counts.get(paper.month, 0) + 1

    return [
        (f"{month} ({month_counts[month]} papers)", month)
        for month in sorted(month_counts, key=lambda month_name: MONTH_ORDER[month_name])
    ]


def prompt_menu_choice() -> str:
    print("1. Download every paper")
    print("2. Download one year or multiple years")
    print("3. Download by month within selected years")
    print("4. Choose specific sessions manually")
    print("5. Preview papers")
    print("0. Exit")
    return input("Choose an option: ").strip()


def prompt_multi_select(
    heading: str,
    options: list[tuple[str, str | int]],
    empty_message: str,
) -> list[str | int]:
    if not options:
        print(empty_message)
        return []

    print(f"\n{heading}")
    print("-" * len(heading))
    for index, (label, _) in enumerate(options, start=1):
        print(f"{index}. {label}")

    while True:
        raw_value = input("Enter numbers like 1,3,5-7 or 'all': ").strip()
        try:
            selected_indexes = parse_selection_input(raw_value, len(options))
        except ValueError as exc:
            print(exc)
            continue
        return [options[index - 1][1] for index in selected_indexes]


def prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw_value = input(f"{question} {suffix}: ").strip().lower()
        if not raw_value:
            return default
        if raw_value in {"y", "yes"}:
            return True
        if raw_value in {"n", "no"}:
            return False
        print("Please answer with y or n.")


def preview_papers(papers: list[PaperRecord]) -> None:
    if not papers:
        print("No papers to preview.")
        return

    print(f"\nShowing {len(papers)} papers")
    print("-" * 20)
    for index, paper in enumerate(papers, start=1):
        print(f"{index}. {paper.paper} -> {paper.session_label}")
    print()


def choose_years(papers: list[PaperRecord]) -> set[int]:
    selected_years = prompt_multi_select(
        "Available Years",
        build_year_options(papers),
        "No years found.",
    )
    return {int(year) for year in selected_years}


def choose_months(papers: list[PaperRecord]) -> set[str]:
    selected_months = prompt_multi_select(
        "Available Months",
        build_month_options(papers),
        "No month-specific papers were found for this selection.",
    )
    return {str(month) for month in selected_months}


def choose_specific_papers(papers: list[PaperRecord]) -> list[PaperRecord]:
    years = choose_years(papers)
    filtered = filter_papers(papers, years=years)

    if any(paper.month for paper in filtered) and prompt_yes_no("Filter by month before picking papers?", default=False):
        months = choose_months(filtered)
        if months:
            filtered = filter_papers(filtered, months=months)

    if not filtered:
        print("No papers matched that filter.")
        return []

    preview_papers(filtered)
    selected_indexes = prompt_multi_select(
        "Pick Specific Papers",
        [(paper.paper, paper) for paper in filtered],
        "No papers available.",
    )
    return list(selected_indexes)


def confirm_and_download(selected_papers: list[PaperRecord]) -> None:
    if not selected_papers:
        print("No papers matched your choice.")
        return

    print(f"\nSelected {len(selected_papers)} papers.")
    preview = selected_papers[:5]
    for paper in preview:
        print(f"- {paper.paper}")
    if len(selected_papers) > len(preview):
        print(f"... and {len(selected_papers) - len(preview)} more.")

    if not prompt_yes_no("Start downloading now?", default=True):
        print("Download cancelled.")
        return

    skip_existing = prompt_yes_no("Skip files that already exist?", default=True)
    download_papers(selected_papers, skip_existing=skip_existing)


def run_cli() -> None:
    try:
        papers = load_papers()
    except FileNotFoundError as exc:
        print(exc)
        return

    while True:
        print_collection_summary(papers)
        choice = prompt_menu_choice()

        if choice == "0":
            print("Goodbye.")
            return
        if choice == "1":
            confirm_and_download(papers)
            continue
        if choice == "2":
            years = choose_years(papers)
            confirm_and_download(filter_papers(papers, years=years))
            continue
        if choice == "3":
            years = choose_years(papers)
            year_filtered = filter_papers(papers, years=years)
            months = choose_months(year_filtered)
            confirm_and_download(filter_papers(year_filtered, months=months))
            continue
        if choice == "4":
            confirm_and_download(choose_specific_papers(papers))
            continue
        if choice == "5":
            preview_papers(papers)
            continue

        print("Please choose one of the menu options.")


if __name__ == "__main__":
    run_cli()
