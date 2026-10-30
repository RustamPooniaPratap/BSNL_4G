from django.urls import path

from . import views

urlpatterns = [
    path('catalog/', views.catalog, name='org-catalog'),
    path('projects/', views.projects, name='org-projects'),
    path('projects/<int:pk>/', views.project_detail, name='org-project'),
    path('circles/', views.circles, name='org-circles'),
    path('circles/<int:pk>/', views.circle_detail, name='org-circle'),
    path('associations/', views.associations, name='org-associations'),
    path('associations/<int:pk>/', views.association_detail, name='org-association'),
    path('aliases/', views.aliases, name='org-aliases'),
    path('aliases/<int:pk>/', views.alias_detail, name='org-alias'),
    path('access/', views.access, name='org-access'),
    path('access/<int:user_id>/', views.access_detail, name='org-access-user'),
    path('history/', views.history, name='org-history'),
]
