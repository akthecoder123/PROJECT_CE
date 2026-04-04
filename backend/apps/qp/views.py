from django.shortcuts import render

# Create your views here.
from django.http import JsonResponse
from .models import Question

def get_questions(request):
    questions = Question.objects.all()

    data = []
    for q in questions:
        data.append({
            "id": q.id,
            "subject": q.subject,
            "chapter": q.chapter,
            "question": q.question_text,
            "options": {
                "A": q.option_a,
                "B": q.option_b,
                "C": q.option_c,
                "D": q.option_d,
            },
            "correct_answer": q.correct_answer,
            "solution": q.solution,
        })

    return JsonResponse(data, safe=False)