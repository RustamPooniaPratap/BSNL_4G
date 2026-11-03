from django.urls import path

from . import hierarchy_views, views

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

    # Team Performance Hierarchy (Phase 1)
    path('hierarchy/oas/', hierarchy_views.operational_areas, name='org-hierarchy-oas'),
    path('hierarchy/oa-aliases/', hierarchy_views.operational_area_aliases, name='org-hierarchy-oa-aliases'),
    path('hierarchy/om-assignments/', hierarchy_views.om_assignments, name='org-hierarchy-om-assignments'),
    path('hierarchy/om-assignments/<int:pk>/', hierarchy_views.om_assignment_detail, name='org-hierarchy-om-assignment-detail'),
    path('hierarchy/om-assignments/audit/', hierarchy_views.om_assignment_audit, name='org-hierarchy-om-assignment-audit'),
    path('hierarchy/personnel/', hierarchy_views.personnel_list, name='org-hierarchy-personnel'),
    path('hierarchy/personnel/<int:pk>/', hierarchy_views.personnel_detail, name='org-hierarchy-personnel-detail'),
    path('hierarchy/personnel-aliases/', hierarchy_views.personnel_aliases, name='org-hierarchy-personnel-aliases'),
    path('hierarchy/source-mappings/', hierarchy_views.source_mappings, name='org-hierarchy-source-mappings'),
    path('hierarchy/conflicts/', hierarchy_views.conflicts_list, name='org-hierarchy-conflicts'),
    path('hierarchy/conflicts/<int:pk>/resolve/', hierarchy_views.resolve_conflict, name='org-hierarchy-resolve-conflict'),
    path('hierarchy/site-assignments/', hierarchy_views.site_assignments, name='org-hierarchy-site-assignments'),
    path('hierarchy/merge-preview/', hierarchy_views.merge_preview, name='org-hierarchy-merge-preview'),
    path('hierarchy/merge-confirm/', hierarchy_views.merge_confirm, name='org-hierarchy-merge-confirm'),
    path('hierarchy/merge-rollback/', hierarchy_views.merge_rollback, name='org-hierarchy-merge-rollback'),
    path('hierarchy/merge-audit/', hierarchy_views.merge_audit_list, name='org-hierarchy-merge-audit'),
]

