from django.core.management.base import BaseCommand
from apps.qp.models import Question
class Command(BaseCommand):
    help = 'Add data to the Question model'

    def handle(self, *args, **kwargs):
        # Create a new question instance
        question = Question(
            subject='Mathematics',
            chapter='Permutations and Combinations',
            date='2025-01-22',
            shift=1,
            exam_type='JEE MAIN',
            question_text='From all the English alphabets, five letters are chosen and are arranged in alphabetical order. The total number of ways, in which the middle letter is \' M \', is :',
            option_a='5148',
            option_b='6084',
            option_c='4356',
            option_d='14950',
            correct_answer='B',
            solution="To find the total number of ways to choose 5 letters from the English alphabets such that the middle letter is 'M', we need to consider the letters that come before and after 'M' in the alphabet."
        )
        # Save the question to the database
        question.save()
        self.stdout.write(self.style.SUCCESS('Successfully added a question to the database.'))
