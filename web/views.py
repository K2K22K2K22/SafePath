from django.conf import settings
from django.shortcuts import render


def home_page(request):
    return render(
        request,
        "web/home.html",
        {"carto_api_key": settings.SAFEPATH_CARTO_API_KEY},
    )
