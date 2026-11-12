from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

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
    SitePersonnelAssignment,
)
from apps.sitedata.models import Site


def assert_no_half_open_overlap(
    existing_qs,
    eff_from: date,
    eff_to: Optional[date] = None,
    exclude_id: Optional[int] = None,
) -> None:
    """
    Validates half-open intervals [effective_from, effective_to).
    Two half-open intervals [A_from, A_to) and [B_from, B_to) overlap if and only if:
    (A_from < B_to) AND (B_from < A_to).
    NULL effective_to represents ongoing infinity (date(9999, 12, 31)).
    """
    qs = existing_qs.filter(is_active=True)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)

    max_end = eff_to or date(9999, 12, 31)

    overlap = qs.filter(
        effective_from__lt=max_end
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gt=eff_from)
    )

    if overlap.exists():
        first = overlap.first()
        to_str = str(first.effective_to) if first.effective_to else 'ongoing'
        raise ValidationError(
            f"Overlaps with existing active assignment (ID {first.pk}: "
            f"[{first.effective_from}, {to_str}))."
        )


@transaction.atomic
def save_om_manager_assignment(
    circle_id: Optional[int] = None,
    actor=None,
    reason: str = "",
    effective_from: Optional[date] = None,
    effective_to: Optional[date] = None,
    project_id: Optional[int] = None,
    manager_name: str = "",
    employee_code: str = "",
    contact: str = "",
    email: str = "",
    user_id: Optional[int] = None,
    is_vacant: bool = False,
    notes: str = "",
    assignment_id: Optional[int] = None,
    request_id: str = "",
    circle: Any = None,
    project: Any = None,
) -> OmManagerAssignment:
    if circle is not None:
        circle_id = circle.pk if hasattr(circle, 'pk') else int(circle)
    if project is not None:
        project_id = project.pk if hasattr(project, 'pk') else int(project)
    if is_vacant and not manager_name:
        manager_name = "[VACANT]"
    if circle_id is None:
        raise ValidationError({"circle_id": "circle or circle_id is required."})
    """
    Saves an O&M Manager assignment with pessimistic row-level locking on Circle,
    enforcing half-open date range validity and creating immutable audit logs.
    """
    if effective_to and effective_to <= effective_from:
        raise ValidationError({"effective_to": "effective_to (exclusive) must be strictly greater than effective_from (inclusive)."})

    # Pessimistic lock on parent Circle
    circle = Circle.objects.select_for_update().get(pk=circle_id)

    # Check overlaps in the same scope (shared vs project-specific)
    existing_qs = OmManagerAssignment.objects.filter(circle=circle, project_id=project_id)
    assert_no_half_open_overlap(existing_qs, effective_from, effective_to, exclude_id=assignment_id)

    before_state: Dict[str, Any] = {}
    action = OmManagerAssignmentAudit.ActionType.CREATE

    if assignment_id:
        assignment = OmManagerAssignment.objects.get(pk=assignment_id, circle=circle)
        action = OmManagerAssignmentAudit.ActionType.UPDATE
        before_state = {
            "id": assignment.id,
            "manager_name": assignment.manager_name,
            "employee_code": assignment.employee_code,
            "contact": assignment.contact,
            "email": assignment.email,
            "user_id": assignment.user_id,
            "is_vacant": assignment.is_vacant,
            "project_id": assignment.project_id,
            "effective_from": str(assignment.effective_from),
            "effective_to": str(assignment.effective_to) if assignment.effective_to else None,
            "notes": assignment.notes,
        }
        assignment.project_id = project_id
        assignment.manager_name = "" if is_vacant else manager_name
        assignment.employee_code = "" if is_vacant else employee_code
        assignment.contact = "" if is_vacant else contact
        assignment.email = "" if is_vacant else email
        assignment.user_id = None if is_vacant else user_id
        assignment.is_vacant = is_vacant
        assignment.effective_from = effective_from
        assignment.effective_to = effective_to
        assignment.notes = notes
        assignment.updated_by = actor
    else:
        assignment = OmManagerAssignment(
            circle=circle,
            project_id=project_id,
            manager_name="" if is_vacant else manager_name,
            employee_code="" if is_vacant else employee_code,
            contact="" if is_vacant else contact,
            email="" if is_vacant else email,
            user_id=None if is_vacant else user_id,
            is_vacant=is_vacant,
            effective_from=effective_from,
            effective_to=effective_to,
            notes=notes,
            created_by=actor,
            updated_by=actor,
        )

    assignment.full_clean()
    assignment.save()

    after_state = {
        "id": assignment.id,
        "manager_name": assignment.manager_name,
        "employee_code": assignment.employee_code,
        "contact": assignment.contact,
        "email": assignment.email,
        "user_id": assignment.user_id,
        "is_vacant": assignment.is_vacant,
        "project_id": assignment.project_id,
        "effective_from": str(assignment.effective_from),
        "effective_to": str(assignment.effective_to) if assignment.effective_to else None,
        "notes": assignment.notes,
    }

    # Record immutable audit entry
    OmManagerAssignmentAudit.objects.create(
        assignment=assignment,
        actor=actor,
        action=action,
        reason=reason,
        effective_date=effective_from,
        before_values=before_state,
        after_values=after_state,
        request_id=request_id,
    )

    return assignment


@transaction.atomic
def save_site_personnel_assignment(
    site_id: Optional[int] = None,
    personnel_id: Optional[int] = None,
    role_type: str = "",
    effective_from: Optional[date] = None,
    effective_to: Optional[date] = None,
    parent_ci_id: Optional[int] = None,
    assignment_id: Optional[int] = None,
    source: str = "service",
    actor=None,
    site: Any = None,
    personnel: Any = None,
    parent_ci: Any = None,
) -> SitePersonnelAssignment:
    if site is not None:
        site_id = site.pk if hasattr(site, 'pk') else int(site)
    if personnel is not None:
        personnel_id = personnel.pk if hasattr(personnel, 'pk') else int(personnel)
    if parent_ci is not None:
        parent_ci_id = parent_ci.pk if hasattr(parent_ci, 'pk') else int(parent_ci)
    if site_id is None or personnel_id is None:
        raise ValidationError("site and personnel are required.")
    """
    Saves a site-personnel assignment with pessimistic row-level locking on the data layer's site (sitedata.Site),
    enforcing dashboard reporting scope, role consistency, parent CI validation, and half-open overlap checks.
    """
    if effective_to and effective_to <= effective_from:
        raise ValidationError({"effective_to": "effective_to (exclusive) must be strictly greater than effective_from (inclusive)."})

    site = Site.objects.select_for_update().filter(pk=site_id).first()
    if site is None:
        raise ValidationError({"site": f"Site {site_id} is not in the site master (Consolidation Matrix)."})
    if site.reporting_scope != Site.Scope.DASHBOARD:
        raise ValidationError({"site": (
            f"Site '{site.bsnl_site_id}' is outside the dashboard reporting scope ({site.entity or 'no entity'}); "
            "only 4G Saturation and LWE dashboard sites take personnel assignments."
        )})
    personnel = Personnel.objects.get(pk=personnel_id)

    if personnel.role_type != role_type:
        raise ValidationError({
            "personnel": f"Personnel role '{personnel.role_type}' does not match assignment role '{role_type}'."
        })

    # Validate parent CI for IE
    if role_type == Personnel.RoleType.IE and parent_ci_id:
        parent_ci = Personnel.objects.get(pk=parent_ci_id)
        if parent_ci.role_type != Personnel.RoleType.CI:
            raise ValidationError({"parent_ci": "The assigned parent_ci must have role_type='ci'."})

        eff_end = effective_to or date(9999, 12, 31)
        ci_overlap_qs = SitePersonnelAssignment.objects.filter(
            site=site,
            personnel=parent_ci,
            role_type=Personnel.RoleType.CI,
            is_active=True,
            effective_from__lt=eff_end,
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from)
        )
        if not ci_overlap_qs.exists():
            raise ValidationError({
                "parent_ci": (
                    f"Parent CI '{parent_ci.display_name}' has no overlapping CI assignment on site "
                    f"'{site.bsnl_site_id}' for interval [{effective_from}, {effective_to or 'ongoing'})."
                )
            })
    elif role_type == Personnel.RoleType.CI and parent_ci_id is not None:
        raise ValidationError({"parent_ci": "A Cluster In-charge assignment cannot have a parent CI."})

    existing_qs = SitePersonnelAssignment.objects.filter(site=site, role_type=role_type)
    assert_no_half_open_overlap(existing_qs, effective_from, effective_to, exclude_id=assignment_id)

    if assignment_id:
        assignment = SitePersonnelAssignment.objects.get(pk=assignment_id, site=site)
        assignment.personnel = personnel
        assignment.role_type = role_type
        assignment.effective_from = effective_from
        assignment.effective_to = effective_to
        assignment.parent_ci_id = parent_ci_id
        assignment.source = source
        assignment.updated_by = actor
    else:
        assignment = SitePersonnelAssignment(
            site=site,
            personnel=personnel,
            role_type=role_type,
            effective_from=effective_from,
            effective_to=effective_to,
            parent_ci_id=parent_ci_id,
            source=source,
            created_by=actor,
            updated_by=actor,
        )

    assignment.full_clean()
    assignment.save()
    return assignment


@transaction.atomic
def save_oa_alias(
    oa_id: int,
    raw_name: str,
    source: str = "import",
) -> OperationalAreaAlias:
    """
    Saves an OA alias ensuring no other OA in the same Circle claims the same normalized key.
    """
    oa = OperationalArea.objects.get(pk=oa_id)
    Circle.objects.select_for_update().get(pk=oa.circle_id)

    normalized_name = " ".join(raw_name.strip().lower().split())
    conflicting = OperationalAreaAlias.objects.filter(
        oa__circle=oa.circle,
        normalized_name=normalized_name,
    ).exclude(oa=oa)

    if conflicting.exists():
        conflict_oa = conflicting.first().oa
        raise ValidationError(
            f"Raw alias '{raw_name}' is already claimed by OA '{conflict_oa.name}' in Circle '{oa.circle.name}'."
        )

    alias, _ = OperationalAreaAlias.objects.get_or_create(
        oa=oa,
        normalized_name=normalized_name,
        defaults={"raw_name": raw_name, "source": source},
    )
    return alias


def preview_personnel_merge(source_id: int, target_id: int) -> Dict[str, Any]:
    """
    Inspects proposed source and target Personnel records without modifying data.
    Returns detected conflicts, affected site assignments, aliases, and user profiles.
    """
    if source_id == target_id:
        raise ValidationError("Source and target personnel cannot be the same.")

    source = Personnel.objects.get(pk=source_id)
    target = Personnel.objects.get(pk=target_id)

    if source.role_type != target.role_type:
        raise ValidationError(f"Cannot merge different roles: source is '{source.role_type}' and target is '{target.role_type}'.")

    if not source.is_active or source.merged_into_id:
        raise ValidationError(f"Source personnel (ID {source.id}) is already inactive or merged.")

    # 1. Attribute comparisons
    code_conflict = bool(source.employee_code and target.employee_code and source.employee_code != target.employee_code)
    contact_conflict = bool(source.contact and target.contact and source.contact != target.contact)
    email_conflict = bool(source.email and target.email and source.email != target.email)
    user_conflict = bool(source.user_id and target.user_id and source.user_id != target.user_id)

    # 2. Site assignments
    source_assignments = list(source.site_assignments.filter(is_active=True).values(
        "id", "site_id", "site__bsnl_site_id", "site__circle", "role_type", "effective_from", "effective_to"
    ))
    target_assignments = list(target.site_assignments.filter(is_active=True).values(
        "id", "site_id", "site__bsnl_site_id", "site__circle", "role_type", "effective_from", "effective_to"
    ))

    target_site_map = {a["site_id"]: a for a in target_assignments}
    assignment_overlaps = []
    for sa in source_assignments:
        ta = target_site_map.get(sa["site_id"])
        if ta:
            # Check date overlap
            s_to = sa["effective_to"] or date(9999, 12, 31)
            t_to = ta["effective_to"] or date(9999, 12, 31)
            if sa["effective_from"] < t_to and ta["effective_from"] < s_to:
                assignment_overlaps.append({
                    "site_id": sa["site__bsnl_site_id"],
                    "source_assignment_id": sa["id"],
                    "target_assignment_id": ta["id"],
                    "source_dates": f"[{sa['effective_from']}, {sa['effective_to'] or 'ongoing'})",
                    "target_dates": f"[{ta['effective_from']}, {ta['effective_to'] or 'ongoing'})",
                })

    # 3. Aliases
    source_aliases = list(source.aliases.values("id", "raw_name", "normalized_name", "circle_id", "project_id"))

    # 4. Source mappings
    source_mappings = list(source.source_mappings.values("id", "source_system", "source_record_key", "mapping_status"))

    # 5. Supervised IE assignments (if source is CI)
    supervised_assignments = list(SitePersonnelAssignment.objects.filter(parent_ci=source, is_active=True).values(
        "id", "site__bsnl_site_id", "personnel__display_name"
    ))

    return {
        "source": {
            "id": source.id,
            "display_name": source.display_name,
            "canonical_name": source.canonical_name,
            "role_type": source.role_type,
            "employee_code": source.employee_code,
            "contact": source.contact,
            "email": source.email,
            "user_id": source.user_id,
        },
        "target": {
            "id": target.id,
            "display_name": target.display_name,
            "canonical_name": target.canonical_name,
            "role_type": target.role_type,
            "employee_code": target.employee_code,
            "contact": target.contact,
            "email": target.email,
            "user_id": target.user_id,
        },
        "conflicts": {
            "employee_code": code_conflict,
            "contact": contact_conflict,
            "email": email_conflict,
            "user": user_conflict,
        },
        "assignment_overlaps": assignment_overlaps,
        "affected_counts": {
            "site_assignments": len(source_assignments),
            "aliases": len(source_aliases),
            "source_mappings": len(source_mappings),
            "supervised_ie_assignments": len(supervised_assignments),
        },
        "site_assignments_count": len(source_assignments),
        "aliases_count": len(source_aliases),
        "source_mappings_count": len(source_mappings),
        "supervised_ie_assignments_count": len(supervised_assignments),
    }


@transaction.atomic
def confirm_personnel_merge(
    source_id: int,
    target_id: int,
    actor,
    reason: str,
) -> PersonnelMergeAudit:
    """
    Executes an atomic merge of source Personnel into surviving target Personnel.
    Preserves source as tombstone and logs full audit trail for rollback.
    """
    if source_id == target_id:
        raise ValidationError("Source and target personnel cannot be the same.")

    # Lock in ascending primary key order to prevent deadlocks
    first_id, second_id = sorted([source_id, target_id])
    p1 = Personnel.objects.select_for_update().get(pk=first_id)
    p2 = Personnel.objects.select_for_update().get(pk=second_id)

    source = p1 if p1.id == source_id else p2
    target = p2 if p2.id == target_id else p1

    if source.role_type != target.role_type:
        raise ValidationError("Cannot merge personnel of different roles.")
    if not source.is_active or source.merged_into_id:
        raise ValidationError(f"Source personnel (ID {source.id}) is already merged or inactive.")

    # Reject unresolved assignment collisions
    preview = preview_personnel_merge(source_id, target_id)
    if preview.get("assignment_overlaps"):
        first_overlap = preview["assignment_overlaps"][0]
        site_str = first_overlap.get("site_id", "unknown")
        raise ValidationError(
            f"Cannot merge: source and target have overlapping active assignments on site '{site_str}'. "
            "Resolve or close conflicting site assignments prior to merging identities."
        )

    # Snapshot pre-merge state
    original_source_state = {
        "id": source.id,
        "display_name": source.display_name,
        "canonical_name": source.canonical_name,
        "role_type": source.role_type,
        "employee_code": source.employee_code,
        "contact": source.contact,
        "email": source.email,
        "user_id": source.user_id,
        "is_active": source.is_active,
    }

    affected_assignments: List[int] = []
    affected_aliases: List[int] = []
    affected_mappings: List[int] = []
    affected_supervised: List[int] = []

    # 1. Repoint SitePersonnelAssignments
    for assign in source.site_assignments.all():
        affected_assignments.append(assign.id)
        # Check if target already has an assignment for this site
        existing_target_assign = SitePersonnelAssignment.objects.filter(
            site=assign.site,
            personnel=target,
            role_type=assign.role_type,
            is_active=True,
        ).first()

        if existing_target_assign:
            # Close source assignment if overlapping to preserve history cleanly
            assign.is_active = False
            assign.save(update_fields=["is_active", "updated_at"])
        else:
            assign.personnel = target
            assign.save(update_fields=["personnel", "updated_at"])

    # 2. Repoint Aliases
    for alias in source.aliases.all():
        affected_aliases.append(alias.id)
        # Avoid duplicate alias per scope on target
        scope_conflict = PersonnelAlias.objects.filter(
            personnel=target,
            role_type=alias.role_type,
            normalized_name=alias.normalized_name,
            circle=alias.circle,
            project=alias.project,
        ).exists()
        if not scope_conflict:
            alias.personnel = target
            alias.save(update_fields=["personnel"])

    # 3. Repoint Source Mappings
    for sm in source.source_mappings.all():
        affected_mappings.append(sm.id)
        sm.personnel = target
        sm.save(update_fields=["personnel", "updated_at"])

    # 4. Repoint Supervised IE assignments if CI
    if source.role_type == Personnel.RoleType.CI:
        for supervised in SitePersonnelAssignment.objects.filter(parent_ci=source):
            affected_supervised.append(supervised.id)
            supervised.parent_ci = target
            supervised.save(update_fields=["parent_ci", "updated_at"])

    # 5. Mark source as tombstone
    source.is_active = False
    source.merged_into = target
    source.merged_at = timezone.now()
    source.merged_by = actor
    source.merge_reason = reason
    source.save(update_fields=["is_active", "merged_into", "merged_at", "merged_by", "merge_reason", "updated_at"])

    # 6. Write PersonnelMergeAudit
    audit = PersonnelMergeAudit.objects.create(
        source_personnel_id=source.id,
        target_personnel=target,
        actor=actor,
        reason=reason,
        affected_relationship_ids={
            "assignments": affected_assignments,
            "aliases": affected_aliases,
            "mappings": affected_mappings,
            "supervised": affected_supervised,
        },
        original_values=original_source_state,
        applied_changes={
            "source_id": source.id,
            "target_id": target.id,
            "repointed_assignments_count": len(affected_assignments),
            "repointed_aliases_count": len(affected_aliases),
            "repointed_mappings_count": len(affected_mappings),
            "repointed_supervised_count": len(affected_supervised),
        },
        status=PersonnelMergeAudit.MergeStatus.APPLIED,
    )

    return audit


@transaction.atomic
def rollback_personnel_merge(
    merge_audit_id: int,
    actor,
    reason: str,
) -> PersonnelMergeAudit:
    """
    Rolls back an earlier Personnel merge operation if safe to do so.
    """
    audit = PersonnelMergeAudit.objects.select_for_update().get(pk=merge_audit_id)
    if audit.status != PersonnelMergeAudit.MergeStatus.APPLIED:
        raise ValidationError(f"Audit {merge_audit_id} cannot be rolled back (status is {audit.status}).")

    source = Personnel.objects.select_for_update().get(pk=audit.source_personnel_id)
    target = Personnel.objects.select_for_update().get(pk=audit.target_personnel_id)

    rel_ids = audit.affected_relationship_ids

    # 1. Restore SitePersonnelAssignments
    assignment_ids = rel_ids.get("assignments", [])
    for aid in assignment_ids:
        assign = SitePersonnelAssignment.objects.filter(pk=aid).first()
        if assign and assign.personnel_id == target.id:
            assign.personnel = source
            assign.is_active = True
            assign.save(update_fields=["personnel", "is_active", "updated_at"])

    # 2. Restore Aliases
    alias_ids = rel_ids.get("aliases", [])
    for al_id in alias_ids:
        alias = PersonnelAlias.objects.filter(pk=al_id).first()
        if alias and alias.personnel_id == target.id:
            alias.personnel = source
            alias.save(update_fields=["personnel"])

    # 3. Restore Source Mappings
    mapping_ids = rel_ids.get("mappings", [])
    for mid in mapping_ids:
        sm = PersonnelSourceMapping.objects.filter(pk=mid).first()
        if sm and sm.personnel_id == target.id:
            sm.personnel = source
            sm.save(update_fields=["personnel", "updated_at"])

    # 4. Restore Supervised IE assignments
    supervised_ids = rel_ids.get("supervised", [])
    for sid in supervised_ids:
        supervised = SitePersonnelAssignment.objects.filter(pk=sid).first()
        if supervised and supervised.parent_ci_id == target.id:
            supervised.parent_ci = source
            supervised.save(update_fields=["parent_ci", "updated_at"])

    # 5. Revive source Personnel
    source.is_active = True
    source.merged_into = None
    source.merged_at = None
    source.merged_by = None
    source.merge_reason = ""
    source.save(update_fields=["is_active", "merged_into", "merged_at", "merged_by", "merge_reason", "updated_at"])

    # 6. Update audit
    audit.status = PersonnelMergeAudit.MergeStatus.ROLLED_BACK
    audit.rollback_status = "ROLLED_BACK"
    audit.rollback_actor = actor
    audit.rollback_timestamp = timezone.now()
    audit.rollback_reason = reason
    audit.save(update_fields=["status", "rollback_status", "rollback_actor", "rollback_timestamp", "rollback_reason"])

    return audit
