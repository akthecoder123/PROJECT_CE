
from django.db import models

# Create your models here.
from django.db import models

#displaying our first question here, will delete later
class Question(models.Model):
    subject = models.CharField(max_length=50)
    chapter = models.CharField(max_length=100)
    shift = models.IntegerField(default=1)
    date = models.DateField(default=None, null=True, blank=True)
    exam_type = models.CharField(max_length=50,default="JEE MAIN")

    question_text = models.TextField()

    option_a = models.CharField(max_length=200)
    option_b = models.CharField(max_length=200)
    option_c = models.CharField(max_length=200)
    option_d = models.CharField(max_length=200)

    correct_answer = models.CharField(max_length=1)
    solution = models.TextField()

    def __str__(self):
        return self.question_text