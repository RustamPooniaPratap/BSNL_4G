from __future__ import annotations

from datetime import date
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.organization.hierarchy_serializers import (
    OmManagerAssignmentAuditSerializer,
    OmManagerAssignmentSerializer,
    OperationalAreaAliasSerializer,
    OperationalAreaSerializer,
    PersonnelAliasSerializer,
    PersonnelConflictSerializer,
    PersonnelMergeAuditSerializer,
    PersonnelSerializer,
    PersonnelSourceMappingSerializer,
    SitePersonnelAssignmentSerializer,
)
from apps.organization.hierarchy_services import (
    confirm_personnel_merge,
    preview_personnel_merge,
    rollback_personnel_merge,
    save_oa_alias,
    save_om_manager_assignment,
    save_site_personnel_assignment,
)
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
from apps.uptimedb.models import UptimeSite


def _paginate(queryset, request, serializer_cls, default_page_size: int = 50):
    try:
        page_num = max(1, int(request.query_params.get("page", 1)))
        page_size = min(200, max(1, int(request.query_params.get("page_size", default_page_size))))
    except (ValueError, TypeError):
        page_num = 1
        page_size = default_page_size

    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_num)

    return Response({
        "results": serializer_cls(page_obj.object_list, many=True).data,
        "count": paginator.count,
        "num_pages": paginator.num_pages,
        "current_page": page_obj.number,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    })


# ==============================================================================
# OPERATIONAL AREAS & ALIASES
# ==============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAdminRole])
def operational_areas(request):
    """
    GET: List Operational Areas (filter by circle, search name).
    POST: Create an Operational Area.
    """
    if request.method == "GET":
        qs = OperationalArea.objects.select_related("circle").prefetch_related("aliases").all()
        circle_code = request.query_params.get("circle")
        if circle_code:
            qs = qs.filter(circle__code__iexact=circle_code.strip())
        search = request.query_params.get("search")
        if search:
            q_term = search.strip()
            qs = qs.filter(Q(name__icontains=q_term) | Q(code__icontains=q_term))
        return _paginate(qs, request, OperationalAreaSerializer)

    # POST
    circle_id = request.data.get("circle")
    name = (request.data.get("name") or "").strip()
    code = (request.data.get("code") or "").strip() or None
    if not circle_id or not name:
        raise ValidationError({"error": "circle and name are required."})

    oa = OperationalArea(circle_id=circle_id, name=name, code=code)
    try:
        oa.full_clean()
        oa.save()
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    return Response(OperationalAreaSerializer(oa).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAdminRole])
def operational_area_aliases(request):
    """
    GET: List OA aliases (filter by oa_id or circle).
    POST: Create an OA alias using save_oa_alias service.
    """
    if request.method == "GET":
        qs = OperationalAreaAlias.objects.select_related("oa", "oa__circle").all()
        oa_id = request.query_params.get("oa")
        if oa_id:
            qs = qs.filter(oa_id=oa_id)
        circle_code = request.query_params.get("circle")
        if circle_code:
            qs = qs.filter(oa__circle__code__iexact=circle_code.strip())
        return _paginate(qs, request, OperationalAreaAliasSerializer)

    oa_id = request.data.get("oa")
    raw_name = (request.data.get("raw_name") or "").strip()
    source = (request.data.get("source") or "manual").strip()
    if not oa_id or not raw_name:
        raise ValidationError({"error": "oa and raw_name are required."})

    try:
        alias = save_oa_alias(oa_id=int(oa_id), raw_name=raw_name, source=source)
    except (DjangoValidationError, ValidationError) as exc:
        raise ValidationError(str(exc))

    return Response(OperationalAreaAliasSerializer(alias).data, status=status.HTTP_201_CREATED)


# ==============================================================================
# O&M MANAGER ASSIGNMENTS & AUDIT
# ==============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAdminRole])
def om_assignments(request):
    """
    GET: List O&M manager assignments (filter by circle, project, active status).
    POST: Create an O&M manager assignment using transactional service.
    """
    if request.method == "GET":
        qs = OmManagerAssignment.objects.select_related("circle", "project", "user").all()
        circle_code = request.query_params.get("circle")
        if circle_code:
            qs = qs.filter(circle__code__iexact=circle_code.strip())
        project_key = request.query_params.get("project")
        if project_key:
            qs = qs.filter(project__key__iexact=project_key.strip())
        active_only = request.query_params.get("active_only")
        if active_only and active_only.lower() in ("true", "1"):
            qs = qs.filter(is_active=True, effective_to__isnull=True)
        return _paginate(qs, request, OmManagerAssignmentSerializer)

    circle_id = request.data.get("circle")
    reason = (request.data.get("reason") or "Initial Admin assignment").strip()
    eff_from_str = request.data.get("effective_from")
    eff_to_str = request.data.get("effective_to")
    project_id = request.data.get("project") or None
    manager_name = (request.data.get("manager_name") or "").strip()
    employee_code = (request.data.get("employee_code") or "").strip()
    contact = (request.data.get("contact") or "").strip()
    email = (request.data.get("email") or "").strip()
    user_id = request.data.get("user") or None
    is_vacant = bool(request.data.get("is_vacant", False))
    notes = (request.data.get("notes") or "").strip()

    if not circle_id or not eff_from_str:
        raise ValidationError({"error": "circle and effective_from are required."})

    try:
        eff_from = date.fromisoformat(str(eff_from_str))
        eff_to = date.fromisoformat(str(eff_to_str)) if eff_to_str else None
    except ValueError:
        raise ValidationError({"error": "Invalid date format. Use YYYY-MM-DD."})

    try:
        assignment = save_om_manager_assignment(
            circle_id=int(circle_id),
            actor=request.user,
            reason=reason,
            effective_from=eff_from,
            effective_to=eff_to,
            project_id=int(project_id) if project_id else None,
            manager_name=manager_name,
            employee_code=employee_code,
            contact=contact,
            email=email,
            user_id=int(user_id) if user_id else None,
            is_vacant=is_vacant,
            notes=notes,
        )
    except (DjangoValidationError, ValidationError) as exc:
        raise ValidationError(str(exc))

    return Response(OmManagerAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


@api_view(["PUT"])
@permission_classes([IsAdminRole])
def om_assignment_detail(request, pk: int):
    """
    PUT: Update an existing O&M manager assignment (e.g. close, vacate, reassign).
    """
    assignment = OmManagerAssignment.objects.filter(pk=pk).first()
    if not assignment:
        raise NotFound("Assignment not found.")

    reason = (request.data.get("reason") or "Admin update").strip()
    eff_from_str = request.data.get("effective_from") or str(assignment.effective_from)
    eff_to_str = request.data.get("effective_to")
    project_id = request.data.get("project") if "project" in request.data else assignment.project_id
    manager_name = request.data.get("manager_name", assignment.manager_name)
    employee_code = request.data.get("employee_code", assignment.employee_code)
    contact = request.data.get("contact", assignment.contact)
    email = request.data.get("email", assignment.email)
    user_id = request.data.get("user") if "user" in request.data else assignment.user_id
    is_vacant = request.data.get("is_vacant", assignment.is_vacant)
    notes = request.data.get("notes", assignment.notes)

    try:
        eff_from = date.fromisoformat(str(eff_from_str))
        eff_to = date.fromisoformat(str(eff_to_str)) if eff_to_str else None
    except ValueError:
        raise ValidationError({"error": "Invalid date format. Use YYYY-MM-DD."})

    try:
        updated = save_om_manager_assignment(
            circle_id=assignment.circle_id,
            actor=request.user,
            reason=reason,
            effective_from=eff_from,
            effective_to=eff_to,
            project_id=int(project_id) if project_id else None,
            manager_name=str(manager_name).strip(),
            employee_code=str(employee_code).strip(),
            contact=str(contact).strip(),
            email=str(email).strip(),
            user_id=int(user_id) if user_id else None,
            is_vacant=bool(is_vacant),
            notes=str(notes).strip(),
            assignment_id=assignment.id,
        )
    except (DjangoValidationError, ValidationError) as exc:
        raise ValidationError(str(exc))

    return Response(OmManagerAssignmentSerializer(updated).data)


@api_view(["GET"])
@permission_classes([IsAdminRole])
def om_assignment_audit(request):
    """
    GET: Read-only audit trail of O&M manager assignment changes.
    """
    qs = OmManagerAssignmentAudit.objects.select_related("assignment", "actor").all()
    assignment_id = request.query_params.get("assignment")
    if assignment_id:
        qs = qs.filter(assignment_id=assignment_id)
    return _paginate(qs, request, OmManagerAssignmentAuditSerializer)


# ==============================================================================
# PERSONNEL MASTER & ALIASES
# ==============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAdminRole])
def personnel_list(request):
    """
    GET: Paginated list of Personnel (filter by role_type, active status, search).
    POST: Create a Personnel record.
    """
    if request.method == "GET":
        qs = Personnel.objects.select_related("user", "merged_into").prefetch_related("site_assignments", "aliases").all()
        role = request.query_params.get("role_type")
        if role:
            qs = qs.filter(role_type=role.strip().lower())
        active_only = request.query_params.get("active_only")
        if active_only and active_only.lower() in ("true", "1"):
            qs = qs.filter(is_active=True)
        search = request.query_params.get("search")
        if search:
            q_term = search.strip()
            qs = qs.filter(
                Q(display_name__icontains=q_term)
                | Q(canonical_name__icontains=q_term)
                | Q(employee_code__icontains=q_term)
                | Q(contact__icontains=q_term)
            )
        return _paginate(qs, request, PersonnelSerializer)

    display_name = (request.data.get("display_name") or "").strip()
    role_type = (request.data.get("role_type") or "").strip().lower()
    employee_code = (request.data.get("employee_code") or "").strip() or None
    contact = (request.data.get("contact") or "").strip() or None
    email = (request.data.get("email") or "").strip() or None
    user_id = request.data.get("user") or None

    if not display_name or role_type not in (Personnel.RoleType.CI, Personnel.RoleType.IE):
        raise ValidationError({"error": "display_name and valid role_type ('ci' or 'ie') are required."})

    canonical_name = " ".join(display_name.strip().split())
    personnel = Personnel(
        display_name=display_name,
        canonical_name=canonical_name,
        role_type=role_type,
        employee_code=employee_code,
        contact=contact,
        email=email,
        user_id=int(user_id) if user_id else None,
    )
    try:
        personnel.full_clean()
        personnel.save()
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    return Response(PersonnelSerializer(personnel).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT"])
@permission_classes([IsAdminRole])
def personnel_detail(request, pk: int):
    """
    GET: Details of a single Personnel record.
    PUT: Update Personnel details.
    """
    personnel = Personnel.objects.filter(pk=pk).first()
    if not personnel:
        raise NotFound("Personnel not found.")

    if request.method == "GET":
        return Response(PersonnelSerializer(personnel).data)

    display_name = request.data.get("display_name", personnel.display_name)
    employee_code = request.data.get("employee_code", personnel.employee_code)
    contact = request.data.get("contact", personnel.contact)
    email = request.data.get("email", personnel.email)
    user_id = request.data.get("user") if "user" in request.data else personnel.user_id

    personnel.display_name = display_name
    personnel.canonical_name = " ".join(display_name.strip().split())
    personnel.employee_code = employee_code
    personnel.contact = contact
    personnel.email = email
    personnel.user_id = int(user_id) if user_id else None

    try:
        personnel.full_clean()
        personnel.save()
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    return Response(PersonnelSerializer(personnel).data)


@api_view(["GET", "POST"])
@permission_classes([IsAdminRole])
def personnel_aliases(request):
    """
    GET: List Personnel aliases.
    POST: Create a Personnel alias.
    """
    if request.method == "GET":
        qs = PersonnelAlias.objects.select_related("personnel", "circle", "project").all()
        personnel_id = request.query_params.get("personnel")
        if personnel_id:
            qs = qs.filter(personnel_id=personnel_id)
        role = request.query_params.get("role_type")
        if role:
            qs = qs.filter(role_type=role.strip().lower())
        return _paginate(qs, request, PersonnelAliasSerializer)

    personnel_id = request.data.get("personnel")
    raw_name = (request.data.get("raw_name") or "").strip()
    circle_id = request.data.get("circle") or None
    project_id = request.data.get("project") or None
    source = (request.data.get("source") or "manual").strip()

    if not personnel_id or not raw_name:
        raise ValidationError({"error": "personnel and raw_name are required."})

    personnel = Personnel.objects.filter(pk=personnel_id).first()
    if not personnel:
        raise NotFound("Personnel not found.")

    alias = PersonnelAlias(
        personnel=personnel,
        role_type=personnel.role_type,
        raw_name=raw_name,
        normalized_name=" ".join(raw_name.strip().lower().split()),
        circle_id=int(circle_id) if circle_id else None,
        project_id=int(project_id) if project_id else None,
        source=source,
    )
    try:
        alias.full_clean()
        alias.save()
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else str(exc))

    return Response(PersonnelAliasSerializer(alias).data, status=status.HTTP_201_CREATED)


# ==============================================================================
# SOURCE MAPPINGS & CONFLICTS
# ==============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAdminRole])
def source_mappings(request):
    """
    GET: Paginated list of persistent source identity mappings.
    POST: Approve or reassign a source mapping.
    """
    if request.method == "GET":
        qs = PersonnelSourceMapping.objects.select_related("personnel", "source_circle", "source_project", "approved_by").all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(mapping_status=status_filter.strip())
        role = request.query_params.get("role_type")
        if role:
            qs = qs.filter(source_role_type=role.strip().lower())
        search = request.query_params.get("search")
        if search:
            q_term = search.strip()
            qs = qs.filter(
                Q(raw_name__icontains=q_term)
                | Q(source_record_key__icontains=q_term)
                | Q(raw_employee_code__icontains=q_term)
            )
        return _paginate(qs, request, PersonnelSourceMappingSerializer)

    # POST: Approve or assign mapping
    mapping_id = request.data.get("mapping_id")
    personnel_id = request.data.get("personnel_id")
    status_choice = request.data.get("status") or PersonnelSourceMapping.MappingStatus.APPROVED

    if not mapping_id or not personnel_id:
        raise ValidationError({"error": "mapping_id and personnel_id are required."})

    mapping = PersonnelSourceMapping.objects.filter(pk=mapping_id).first()
    if not mapping:
        raise NotFound("Source mapping not found.")

    personnel = Personnel.objects.filter(pk=personnel_id).first()
    if not personnel:
        raise NotFound("Personnel not found.")

    mapping.personnel = personnel
    mapping.mapping_status = status_choice
    mapping.approved_by = request.user
    mapping.approved_at = timezone.now()
    mapping.save(update_fields=["personnel", "mapping_status", "approved_by", "approved_at", "updated_at"])

    return Response(PersonnelSourceMappingSerializer(mapping).data)


@api_view(["GET"])
@permission_classes([IsAdminRole])
def conflicts_list(request):
    """
    GET: Paginated list of PersonnelConflict records.
    """
    qs = PersonnelConflict.objects.select_related("resolved_personnel", "reviewed_by").all()
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter.strip())
    conflict_type = request.query_params.get("conflict_type")
    if conflict_type:
        qs = qs.filter(conflict_type=conflict_type.strip())
    role = request.query_params.get("role_type")
    if role:
        qs = qs.filter(role_type=role.strip().lower())
    return _paginate(qs, request, PersonnelConflictSerializer)


@api_view(["POST"])
@permission_classes([IsAdminRole])
def resolve_conflict(request, pk: int):
    """
    POST: Resolve a conflict by linking a verified Personnel ID and recording resolution notes.
    """
    conflict = PersonnelConflict.objects.filter(pk=pk).first()
    if not conflict:
        raise NotFound("Conflict not found.")

    personnel_id = request.data.get("personnel_id")
    resolution_text = (request.data.get("resolution") or "").strip()
    status_choice = request.data.get("status") or PersonnelConflict.Status.RESOLVED

    if personnel_id:
        personnel = Personnel.objects.filter(pk=personnel_id).first()
        if not personnel:
            raise NotFound("Personnel not found.")
        conflict.resolved_personnel = personnel

    conflict.resolution = resolution_text
    conflict.status = status_choice
    conflict.reviewed_by = request.user
    conflict.reviewed_at = timezone.now()
    conflict.save()

    return Response(PersonnelConflictSerializer(conflict).data)


# ==============================================================================
# SITE PERSONNEL ASSIGNMENTS
# ==============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAdminRole])
def site_assignments(request):
    """
    GET: Paginated list of SitePersonnelAssignment records.
    POST: Create a site personnel assignment using transactional service.
    """
    if request.method == "GET":
        qs = SitePersonnelAssignment.objects.select_related("site", "personnel", "parent_ci").all()
        site_str = request.query_params.get("site_id")
        if site_str:
            qs = qs.filter(site__site_id__icontains=site_str.strip())
        circle_code = request.query_params.get("circle")
        if circle_code:
            qs = qs.filter(site__circle__iexact=circle_code.strip())
        role = request.query_params.get("role_type")
        if role:
            qs = qs.filter(role_type=role.strip().lower())
        personnel_id = request.query_params.get("personnel")
        if personnel_id:
            qs = qs.filter(personnel_id=personnel_id)
        active_only = request.query_params.get("active_only")
        if active_only and active_only.lower() in ("true", "1"):
            qs = qs.filter(is_active=True, effective_to__isnull=True)
        return _paginate(qs, request, SitePersonnelAssignmentSerializer)

    site_id = request.data.get("site")
    personnel_id = request.data.get("personnel")
    role_type = (request.data.get("role_type") or "").strip().lower()
    eff_from_str = request.data.get("effective_from")
    eff_to_str = request.data.get("effective_to")
    parent_ci_id = request.data.get("parent_ci") or None
    source = (request.data.get("source") or "admin").strip()

    if not site_id or not personnel_id or not role_type or not eff_from_str:
        raise ValidationError({"error": "site, personnel, role_type, and effective_from are required."})

    try:
        eff_from = date.fromisoformat(str(eff_from_str))
        eff_to = date.fromisoformat(str(eff_to_str)) if eff_to_str else None
    except ValueError:
        raise ValidationError({"error": "Invalid date format. Use YYYY-MM-DD."})

    try:
        assignment = save_site_personnel_assignment(
            site_id=int(site_id),
            personnel_id=int(personnel_id),
            role_type=role_type,
            effective_from=eff_from,
            effective_to=eff_to,
            parent_ci_id=int(parent_ci_id) if parent_ci_id else None,
            source=source,
            actor=request.user,
        )
    except (DjangoValidationError, ValidationError) as exc:
        raise ValidationError(str(exc))

    return Response(SitePersonnelAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


# ==============================================================================
# PERSONNEL MERGE & RECOVERY
# ==============================================================================

@api_view(["POST"])
@permission_classes([IsAdminRole])
def merge_preview(request):
    """
    POST: Preview proposed merge of source into target Personnel.
    """
    source_id = request.data.get("source_id")
    target_id = request.data.get("target_id")
    if not source_id or not target_id:
        raise ValidationError({"error": "source_id and target_id are required."})

    try:
        preview_data = preview_personnel_merge(int(source_id), int(target_id))
    except (DjangoValidationError, ValidationError) as exc:
        raise ValidationError(str(exc))

    return Response(preview_data)


@api_view(["POST"])
@permission_classes([IsAdminRole])
def merge_confirm(request):
    """
    POST: Atomically apply merge of source into target Personnel.
    """
    source_id = request.data.get("source_id")
    target_id = request.data.get("target_id")
    reason = (request.data.get("reason") or "").strip()

    if not source_id or not target_id or not reason:
        raise ValidationError({"error": "source_id, target_id, and mandatory reason are required."})

    try:
        audit = confirm_personnel_merge(int(source_id), int(target_id), request.user, reason)
    except (DjangoValidationError, ValidationError) as exc:
        raise ValidationError(str(exc))

    return Response(PersonnelMergeAuditSerializer(audit).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAdminRole])
def merge_rollback(request):
    """
    POST: Roll back a previously confirmed Personnel merge.
    """
    merge_audit_id = request.data.get("merge_audit_id")
    reason = (request.data.get("reason") or "").strip()

    if not merge_audit_id or not reason:
        raise ValidationError({"error": "merge_audit_id and mandatory reason are required."})

    try:
        audit = rollback_personnel_merge(int(merge_audit_id), request.user, reason)
    except (DjangoValidationError, ValidationError) as exc:
        raise ValidationError(str(exc))

    return Response(PersonnelMergeAuditSerializer(audit).data)


@api_view(["GET"])
@permission_classes([IsAdminRole])
def merge_audit_list(request):
    """
    GET: Read-only list of Personnel merge audit records.
    """
    qs = PersonnelMergeAudit.objects.select_related("target_personnel", "actor", "rollback_actor").all()
    return _paginate(qs, request, PersonnelMergeAuditSerializer)

