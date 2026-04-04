from django.core.management.base import BaseCommand, CommandError

from apps.qp.services.examside_importer import replace_paper_questions


class Command(BaseCommand):
    help = "Import one Examside paper into the Question table."

    def add_arguments(self, parser):
        parser.add_argument("paper_url", help="Paper page URL or paper __data.json URL.")

    def handle(self, *args, **options):
        paper_url = options["paper_url"]

        try:
            result = replace_paper_questions(paper_url)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {result['count']} questions for "
                f"{result['paper_title']} ({result['date']}, shift {result['shift']})."
            )
        )
