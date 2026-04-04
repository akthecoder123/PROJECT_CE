
from django.db import models


class Question(models.Model):
    subject = models.CharField(max_length=50)
    chapter = models.CharField(max_length=255)
    shift = models.IntegerField(default=1)
    date = models.DateField(default=None, null=True, blank=True)
    exam_type = models.CharField(max_length=50, default="JEE MAIN")

    question_text = models.TextField()

    option_a = models.TextField(blank=True, default="")
    option_b = models.TextField(blank=True, default="")
    option_c = models.TextField(blank=True, default="")
    option_d = models.TextField(blank=True, default="")
    question_image_urls = models.JSONField(blank=True, default=list)
    option_a_image_urls = models.JSONField(blank=True, default=list)
    option_b_image_urls = models.JSONField(blank=True, default=list)
    option_c_image_urls = models.JSONField(blank=True, default=list)
    option_d_image_urls = models.JSONField(blank=True, default=list)

    correct_answer = models.TextField(blank=True, default="")
    solution = models.TextField(blank=True, default="")
    solution_image_urls = models.JSONField(blank=True, default=list)

    def __str__(self):
        return self.question_text
