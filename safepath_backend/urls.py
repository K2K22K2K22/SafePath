"""
URL configuration for safepath_backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from Model.views import geocode, routes, safety_heatmap

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("web.urls")),
    path("api/geocode/", geocode, name="geocode"),
    path("api/routes/", routes, name="routes"),
    path("api/safety-heatmap/", safety_heatmap, name="safety_heatmap"),
    path("api/safe-route/", routes, name="safe_route"),
]
