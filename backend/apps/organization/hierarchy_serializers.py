from rest_framework import serializers

from apps.organization.models import (
    Circle,
    OmManagerAssignment,
    OmManagerAssignmentAudit,
    OperationalArea,
    OperationalAreaAlias,
    Personnel,
    PersonnelAlias,
    PersonnelConflict,
    PersonnelMergeAudit,
    PersonnelSourceMapping,
    Project,
    SitePersonnelAssignment,
)


class OperationalAreaSerializer(serializers.ModelSerializer):
    circle_code = serializers.CharField(source='circle.code', read_only=True)
    circle_name = serializers.CharField(source='circle.name', read_only=True)
    alias_count = serializers.IntegerField(source='aliases.count', read_only=True)

    class Meta:
        model = OperationalArea
        fields = [
            'id', 'circle', 'circle_code', 'circle_name', 'name', 'normalized_name',
            'code', 'is_active', 'alias_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'normalized_name', 'created_at', 'updated_at']


class OperationalAreaAliasSerializer(serializers.ModelSerializer):
    oa_name = serializers.CharField(source='oa.name', read_only=True)
    circle_code = serializers.CharField(source='oa.circle.code', read_only=True)

    class Meta:
        model = OperationalAreaAlias
        fields = [
            'id', 'oa', 'oa_name', 'circle_code', 'raw_name', 'normalized_name',
            'source', 'created_at'
        ]
        read_only_fields = ['id', 'normalized_name', 'created_at']


class OmManagerAssignmentSerializer(serializers.ModelSerializer):
    circle_code = serializers.CharField(source='circle.code', read_only=True)
    circle_name = serializers.CharField(source='circle.name', read_only=True)
    project_key = serializers.CharField(source='project.key', read_only=True, default=None)
    project_name = serializers.CharField(source='project.name', read_only=True, default=None)
    user_username = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = OmManagerAssignment
        fields = [
            'id', 'circle', 'circle_code', 'circle_name', 'project', 'project_key', 'project_name',
            'manager_name', 'employee_code', 'contact', 'email', 'user', 'user_username',
            'is_vacant', 'is_active', 'effective_from', 'effective_to', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class OmManagerAssignmentAuditSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source='actor.username', read_only=True, default='System')

    class Meta:
        model = OmManagerAssignmentAudit
        fields = [
            'id', 'assignment', 'actor', 'actor_username', 'action', 'timestamp',
            'reason', 'effective_date', 'before_values', 'after_values', 'request_id'
        ]
        read_only_fields = fields


class PersonnelSerializer(serializers.ModelSerializer):
    site_assignment_count = serializers.IntegerField(source='site_assignments.count', read_only=True)
    alias_count = serializers.IntegerField(source='aliases.count', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True, default=None)
    merged_into_name = serializers.CharField(source='merged_into.display_name', read_only=True, default=None)

    class Meta:
        model = Personnel
        fields = [
            'id', 'display_name', 'canonical_name', 'role_type', 'employee_code',
            'contact', 'email', 'user', 'user_username', 'is_active',
            'merged_into', 'merged_into_name', 'merged_at', 'merge_reason',
            'site_assignment_count', 'alias_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'canonical_name', 'merged_at', 'created_at', 'updated_at']


class PersonnelAliasSerializer(serializers.ModelSerializer):
    personnel_name = serializers.CharField(source='personnel.display_name', read_only=True)
    circle_code = serializers.CharField(source='circle.code', read_only=True, default=None)
    project_key = serializers.CharField(source='project.key', read_only=True, default=None)

    class Meta:
        model = PersonnelAlias
        fields = [
            'id', 'personnel', 'personnel_name', 'role_type', 'raw_name', 'normalized_name',
            'source', 'circle', 'circle_code', 'project', 'project_key', 'created_at'
        ]
        read_only_fields = ['id', 'normalized_name', 'created_at']


class PersonnelSourceMappingSerializer(serializers.ModelSerializer):
    personnel_name = serializers.CharField(source='personnel.display_name', read_only=True, default=None)
    circle_code = serializers.CharField(source='source_circle.code', read_only=True, default=None)
    project_key = serializers.CharField(source='source_project.key', read_only=True, default=None)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True, default=None)

    class Meta:
        model = PersonnelSourceMapping
        fields = [
            'id', 'source_system', 'source_dataset', 'source_record_key', 'source_role_type',
            'source_circle', 'circle_code', 'source_project', 'project_key', 'raw_name',
            'raw_employee_code', 'personnel', 'personnel_name', 'mapping_status',
            'approved_by', 'approved_by_username', 'approved_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'approved_at', 'created_at', 'updated_at']


class SitePersonnelAssignmentSerializer(serializers.ModelSerializer):
    # Field names kept for the frontend: the site is the data layer's sitedata.Site (BSNL Site ID, technology).
    site_id_str = serializers.CharField(source='site.bsnl_site_id', read_only=True)
    site_name = serializers.CharField(source='site.site_name', read_only=True)
    circle_code = serializers.CharField(source='site.circle', read_only=True)
    project_key = serializers.CharField(source='site.technology', read_only=True)
    personnel_name = serializers.CharField(source='personnel.display_name', read_only=True)
    personnel_code = serializers.CharField(source='personnel.employee_code', read_only=True)
    parent_ci_name = serializers.CharField(source='parent_ci.display_name', read_only=True, default=None)

    class Meta:
        model = SitePersonnelAssignment
        fields = [
            'id', 'site', 'site_id_str', 'site_name', 'circle_code', 'project_key',
            'personnel', 'personnel_name', 'personnel_code', 'role_type',
            'parent_ci', 'parent_ci_name', 'effective_from', 'effective_to',
            'is_active', 'source', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PersonnelConflictSerializer(serializers.ModelSerializer):
    resolved_personnel_name = serializers.CharField(source='resolved_personnel.display_name', read_only=True, default=None)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True, default=None)

    class Meta:
        model = PersonnelConflict
        fields = [
            'id', 'fingerprint', 'source_system', 'source_dataset', 'source_record_key',
            'conflict_type', 'role_type', 'raw_source_data', 'possible_matches',
            'status', 'resolution', 'resolved_personnel', 'resolved_personnel_name',
            'reviewed_by', 'reviewed_by_username', 'reviewed_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'fingerprint', 'created_at', 'updated_at']


class PersonnelMergeAuditSerializer(serializers.ModelSerializer):
    target_personnel_name = serializers.CharField(source='target_personnel.display_name', read_only=True)
    actor_username = serializers.CharField(source='actor.username', read_only=True, default='System')
    rollback_actor_username = serializers.CharField(source='rollback_actor.username', read_only=True, default=None)

    class Meta:
        model = PersonnelMergeAudit
        fields = [
            'id', 'source_personnel_id', 'target_personnel', 'target_personnel_name',
            'actor', 'actor_username', 'timestamp', 'reason', 'affected_relationship_ids',
            'original_values', 'applied_changes', 'status', 'rollback_status',
            'rollback_actor', 'rollback_actor_username', 'rollback_timestamp', 'rollback_reason'
        ]
        read_only_fields = fields

