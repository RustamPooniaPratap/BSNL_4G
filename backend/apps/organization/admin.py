"""
Django Admin configurations for Organization & Team Performance Hierarchy models.
Enforces read-only audit log protection across the standard Django Admin interface.
"""

from django.contrib import admin
from apps.organization.models import (
    Circle,
    CircleAlias,
    Project,
    ProjectCircle,
    OrganizationChange,
    OperationalArea,
    OperationalAreaAlias,
    OmManagerAssignment,
    OmManagerAssignmentAudit,
    Personnel,
    PersonnelAlias,
    PersonnelSourceMapping,
    SitePersonnelAssignment,
    PersonnelConflict,
    PersonnelMergeAudit,
)


@admin.register(OmManagerAssignmentAudit)
class OmManagerAssignmentAuditAdmin(admin.ModelAdmin):
    list_display = ['id', 'assignment', 'actor', 'action', 'effective_date', 'timestamp']
    list_filter = ['action', 'effective_date']
    search_fields = ['reason', 'actor__username', 'request_id']
    readonly_fields = [f.name for f in OmManagerAssignmentAudit._meta.fields]
    actions = None  # Completely disables bulk actions like delete_selected

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PersonnelMergeAudit)
class PersonnelMergeAuditAdmin(admin.ModelAdmin):
    list_display = ['id', 'source_personnel_id', 'target_personnel', 'actor', 'status', 'rollback_status', 'timestamp']
    list_filter = ['status', 'rollback_status']
    search_fields = ['reason', 'rollback_reason', 'actor__username']
    readonly_fields = [f.name for f in PersonnelMergeAudit._meta.fields]
    actions = None  # Completely disables bulk actions like delete_selected

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OperationalArea)
class OperationalAreaAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'normalized_name', 'circle', 'code', 'is_active']
    list_filter = ['circle', 'is_active']
    search_fields = ['name', 'normalized_name', 'code']


@admin.register(OperationalAreaAlias)
class OperationalAreaAliasAdmin(admin.ModelAdmin):
    list_display = ['id', 'raw_name', 'normalized_name', 'oa', 'source']
    search_fields = ['raw_name', 'normalized_name', 'oa__name']


@admin.register(OmManagerAssignment)
class OmManagerAssignmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'circle', 'project', 'manager_name', 'is_vacant', 'effective_from', 'effective_to', 'is_active']
    list_filter = ['circle', 'is_vacant', 'is_active']
    search_fields = ['manager_name', 'employee_code', 'contact', 'email']


@admin.register(Personnel)
class PersonnelAdmin(admin.ModelAdmin):
    list_display = ['id', 'display_name', 'canonical_name', 'role_type', 'employee_code', 'contact', 'is_active', 'merged_into']
    list_filter = ['role_type', 'is_active']
    search_fields = ['display_name', 'canonical_name', 'employee_code', 'contact']


@admin.register(PersonnelAlias)
class PersonnelAliasAdmin(admin.ModelAdmin):
    list_display = ['id', 'raw_name', 'normalized_name', 'personnel', 'role_type', 'circle', 'project']
    list_filter = ['role_type', 'circle']
    search_fields = ['raw_name', 'normalized_name', 'personnel__canonical_name']


@admin.register(PersonnelSourceMapping)
class PersonnelSourceMappingAdmin(admin.ModelAdmin):
    list_display = ['id', 'source_dataset', 'source_record_key', 'raw_name', 'personnel', 'mapping_status']
    list_filter = ['mapping_status', 'source_role_type']
    search_fields = ['raw_name', 'source_record_key']


@admin.register(SitePersonnelAssignment)
class SitePersonnelAssignmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'site', 'personnel', 'role_type', 'parent_ci', 'effective_from', 'effective_to', 'is_active']
    list_filter = ['role_type', 'is_active']
    search_fields = ['site__bsnl_site_id', 'personnel__canonical_name']


@admin.register(PersonnelConflict)
class PersonnelConflictAdmin(admin.ModelAdmin):
    list_display = ['id', 'conflict_type', 'role_type', 'fingerprint', 'status', 'reviewed_by']
    list_filter = ['conflict_type', 'role_type', 'status']
    search_fields = ['fingerprint', 'source_record_key']

