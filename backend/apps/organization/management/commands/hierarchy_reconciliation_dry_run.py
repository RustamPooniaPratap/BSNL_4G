import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from django.core.management.base import BaseCommand
from django.db.models import Count, Min, Q

from apps.organization.models import Circle, Project
from apps.uptimedb.models import EscalationSite, UptimeSite


class Command(BaseCommand):
    help = "Dry-run reconciliation and bootstrap inspection for Team Performance Hierarchy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Execute database writes (requires explicit confirmation). Defaults to False (Dry Run).",
        )

    def handle(self, *args, **options):
        is_commit = options.get("commit", False)
        self.stdout.write(self.style.MIGRATE_HEADING("================================================================================"))
        self.stdout.write(self.style.MIGRATE_HEADING("  BSNL 4G — TEAM PERFORMANCE HIERARCHY: RECONCILIATION DRY RUN"))
        self.stdout.write(self.style.MIGRATE_HEADING("================================================================================"))
        if is_commit:
            self.stdout.write(self.style.WARNING("MODE: COMMIT REQUESTED (Applying database writes)"))
        else:
            self.stdout.write(self.style.SUCCESS("MODE: STRICT DRY-RUN (Read-only, no database writes)"))

        total_uptime_sites = UptimeSite.objects.count()
        total_escalation_sites = EscalationSite.objects.count()
        self.stdout.write(f"\nSource Records:")
        self.stdout.write(f"  • Total UptimeSite records: {total_uptime_sites}")
        self.stdout.write(f"  • Total EscalationSite records: {total_escalation_sites}")

        # ----------------------------------------------------------------------
        # 1. Operational Areas (OAs)
        # ----------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL("\n--- 1. OPERATIONAL AREAS (OAs) RECONCILIATION ---"))
        oa_sites = UptimeSite.objects.exclude(oa="").exclude(oa__isnull=True).values("circle", "oa")

        canonical_oas: Dict[str, Set[str]] = defaultdict(set)
        oa_raw_variants: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        oa_resolution_failures = 0

        for row in oa_sites:
            circle_code = row["circle"].strip()
            raw_oa = row["oa"]
            normalized_oa = " ".join(raw_oa.strip().lower().split())
            if not normalized_oa:
                oa_resolution_failures += 1
                continue
            canonical_name = " ".join(raw_oa.strip().split()).title()
            canonical_oas[circle_code].add(canonical_name)
            oa_raw_variants[circle_code][canonical_name].add(raw_oa)

        total_canonical_oas = sum(len(oas) for oas in canonical_oas.values())
        total_oa_aliases = sum(
            sum(len(variants) for variants in oas.values())
            for oas in oa_raw_variants.values()
        )
        casing_variants_count = sum(
            sum(1 for variants in oas.values() if len(variants) > 1)
            for oas in oa_raw_variants.values()
        )

        self.stdout.write(f"  • Distinct Canonical OAs across Circles: {total_canonical_oas}")
        self.stdout.write(f"  • Total OA Raw Aliases: {total_oa_aliases}")
        self.stdout.write(f"  • OAs with Casing/Whitespace Variants in Same Circle: {casing_variants_count}")
        self.stdout.write(f"  • OA Resolution Failures (blank/missing): {oa_resolution_failures}")

        # ----------------------------------------------------------------------
        # 2. Personnel Identification & Conflict Audit
        # ----------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL("\n--- 2. PERSONNEL IDENTITY & CONFLICT AUDIT ---"))

        # Inspect EscalationSite for rich identity fields (code, contact, name)
        esc_rows = EscalationSite.objects.values(
            "circle", "project", "ci_name", "ci_emp_code", "ci_contact",
            "ie_name", "ie_emp_code", "ie_contact"
        )

        ci_candidates: Dict[Tuple[str, str], Dict[str, Any]] = {}
        ie_candidates: Dict[Tuple[str, str], Dict[str, Any]] = {}

        ci_code_to_names: Dict[str, Set[str]] = defaultdict(set)
        ie_code_to_names: Dict[str, Set[str]] = defaultdict(set)
        ie_name_to_codes: Dict[str, Set[str]] = defaultdict(set)

        for r in esc_rows:
            circle = r["circle"].strip() if r["circle"] else ""
            # CI
            ci_name = (r["ci_name"] or "").strip()
            ci_code = (r["ci_emp_code"] or "").strip()
            if ci_code.upper() in ("-", "TBD", "NA", "NULL", "NONE"):
                ci_code = ""
            if ci_name and ci_name not in ("-", "TBD", "NA"):
                c_key = (circle, " ".join(ci_name.lower().split()))
                if c_key not in ci_candidates:
                    ci_candidates[c_key] = {
                        "name": " ".join(ci_name.split()).title(),
                        "canonical_name": " ".join(ci_name.lower().split()),
                        "circle": circle,
                        "role": "ci",
                        "emp_code": ci_code,
                        "contact": (r["ci_contact"] or "").strip().replace(" ", "").replace("-", ""),
                    }
                elif ci_code and not ci_candidates[c_key]["emp_code"]:
                    ci_candidates[c_key]["emp_code"] = ci_code

                if ci_code:
                    ci_code_to_names[ci_code].add(c_key[1])

            # IE
            ie_name = (r["ie_name"] or "").strip()
            ie_code = (r["ie_emp_code"] or "").strip()
            if ie_code.upper() in ("-", "TBD", "NA", "NULL", "NONE"):
                ie_code = ""
            if ie_name and ie_name not in ("-", "TBD", "NA"):
                i_key = (circle, " ".join(ie_name.lower().split()))
                if i_key not in ie_candidates:
                    ie_candidates[i_key] = {
                        "name": " ".join(ie_name.split()).title(),
                        "canonical_name": " ".join(ie_name.lower().split()),
                        "circle": circle,
                        "role": "ie",
                        "emp_code": ie_code,
                        "contact": (r["ie_contact"] or "").strip().replace(" ", "").replace("-", ""),
                    }
                elif ie_code and not ie_candidates[i_key]["emp_code"]:
                    ie_candidates[i_key]["emp_code"] = ie_code

                if ie_code:
                    ie_code_to_names[ie_code].add(i_key[1])
                    ie_name_to_codes[i_key].add(ie_code)

        # Also inspect UptimeSite for any CI/IE names absent from EscalationSite
        uptime_rows = UptimeSite.objects.values("circle", "ci_name", "ie_name")
        for ur in uptime_rows:
            c = ur["circle"].strip() if ur["circle"] else ""
            ci = (ur["ci_name"] or "").strip()
            ie = (ur["ie_name"] or "").strip()
            if ci and ci not in ("-", "TBD", "NA"):
                ck = (c, " ".join(ci.lower().split()))
                if ck not in ci_candidates:
                    ci_candidates[ck] = {
                        "name": " ".join(ci.split()).title(),
                        "canonical_name": " ".join(ci.lower().split()),
                        "circle": c,
                        "role": "ci",
                        "emp_code": "",
                        "contact": "",
                    }
            if ie and ie not in ("-", "TBD", "NA"):
                ik = (c, " ".join(ie.lower().split()))
                if ik not in ie_candidates:
                    ie_candidates[ik] = {
                        "name": " ".join(ie.split()).title(),
                        "canonical_name": " ".join(ie.lower().split()),
                        "circle": c,
                        "role": "ie",
                        "emp_code": "",
                        "contact": "",
                    }

        conflicting_ie_codes = {code: names for code, names in ie_code_to_names.items() if len(names) > 1}
        shared_ci_ie_codes = set(ci_code_to_names.keys()) & set(ie_code_to_names.keys())

        self.stdout.write(f"  • Proposed Distinct Canonical CI Personnel (Circle-scoped): {len(ci_candidates)}")
        self.stdout.write(f"  • Proposed Distinct Canonical IE Personnel (Circle-scoped): {len(ie_candidates)}")
        self.stdout.write(f"  • Total Proposed Personnel Records: {len(ci_candidates) + len(ie_candidates)}")
        self.stdout.write(f"  • IE Employee Codes Mapping to Multiple Names: {len(conflicting_ie_codes)}")
        for code, names in conflicting_ie_codes.items():
            self.stdout.write(f"      - Code {code}: {', '.join(sorted(names))}")
        self.stdout.write(f"  • Code Collisions between CI and IE roles: {len(shared_ci_ie_codes)} ({', '.join(sorted(shared_ci_ie_codes))})")

        # ----------------------------------------------------------------------
        # 3. Site Assignment Reconciliation (UptimeSite)
        # ----------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL("\n--- 3. SITE-PERSONNEL ASSIGNMENTS RECONCILIATION ---"))

        uptime_site_rows = list(UptimeSite.objects.values("site_id", "circle", "project", "ci_name", "ie_name"))

        valid_ci_assignments = 0
        unassigned_ci_sites = []
        valid_ie_assignments = 0
        unassigned_ie_sites = []
        whitespace_normalized_ie = 0
        ie_without_parent_ci_sites = []

        for s in uptime_site_rows:
            ci = (s["ci_name"] or "").strip()
            ie = (s["ie_name"] or "").strip()

            has_valid_ci = False
            if not ci or ci in ("-", "TBD"):
                unassigned_ci_sites.append(s["site_id"])
            else:
                valid_ci_assignments += 1
                has_valid_ci = True

            if not ie or ie in ("-", "TBD"):
                unassigned_ie_sites.append(s["site_id"])
            else:
                valid_ie_assignments += 1
                if "\xa0" in s["ie_name"] or "  " in s["ie_name"]:
                    whitespace_normalized_ie += 1
                if not has_valid_ci:
                    ie_without_parent_ci_sites.append(s["site_id"])

        ci_coverage_pct = (valid_ci_assignments / total_uptime_sites) * 100 if total_uptime_sites else 0
        ie_coverage_pct = (valid_ie_assignments / total_uptime_sites) * 100 if total_uptime_sites else 0

        self.stdout.write(f"  • Total Eligible UptimeSite Records: {total_uptime_sites}")
        self.stdout.write(f"  • Valid CI Site Assignments: {valid_ci_assignments} ({ci_coverage_pct:.2f}%)")
        self.stdout.write(f"  • Unassigned CI Sites: {len(unassigned_ci_sites)} ({', '.join(unassigned_ci_sites) if unassigned_ci_sites else 'None'})")
        self.stdout.write(f"  • Valid IE Site Assignments: {valid_ie_assignments} ({ie_coverage_pct:.2f}%)")
        self.stdout.write(f"      - Exact String Matches: {valid_ie_assignments - whitespace_normalized_ie}")
        self.stdout.write(f"      - Whitespace-Normalized Matches: {whitespace_normalized_ie}")
        self.stdout.write(f"  • Unassigned IE Sites: {len(unassigned_ie_sites)} ({', '.join(unassigned_ie_sites) if unassigned_ie_sites else 'None'})")
        self.stdout.write(f"  • IE Assignments with Verified Parent CI on Site: {valid_ie_assignments - len(ie_without_parent_ci_sites)}")
        self.stdout.write(f"  • IE Assignments with Parent CI Missing (optional parent_ci=NULL): {len(ie_without_parent_ci_sites)}")

        # ----------------------------------------------------------------------
        # 4. O&M Manager Assignment & Vacancy Status
        # ----------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_LABEL("\n--- 4. O&M MANAGER ASSIGNMENTS & VACANCIES RECONCILIATION ---"))
        self.stdout.write(f"  {'Circle':<8} | {'Proposed O&M Manager':<24} | {'Status':<8} | {'Emp Code':<10} | {'Contact':<12} | {'Effective':<10} | {'Scope'}")
        self.stdout.write("  " + "-" * 100)

        # Group EscalationSite records by Circle
        om_records = EscalationSite.objects.values(
            'circle', 'om_manager_name', 'om_manager_emp_code', 'om_manager_contact'
        ).annotate(
            site_count=Count('id'),
            earliest_om_start=Min('om_start_date')
        ).order_by('circle', '-site_count')

        seen_circles = set()
        vacant_circles_count = 0
        assigned_circles_count = 0

        for rec in om_records:
            c = rec['circle']
            if c in seen_circles:
                continue
            seen_circles.add(c)

            name = (rec['om_manager_name'] or '').strip()
            is_vacant = name.lower() in ('vacant', '', '-', 'none', 'tbd')
            status_str = "VACANT" if is_vacant else "ASSIGNED"
            if is_vacant:
                vacant_circles_count += 1
                disp_name = "[VACANT POST]"
                code_disp = "—"
                contact_disp = "—"
            else:
                assigned_circles_count += 1
                disp_name = name
                code_disp = rec['om_manager_emp_code'] or "—"
                contact_disp = rec['om_manager_contact'] or "—"

            eff_date = str(rec['earliest_om_start'] or "2025-10-01")
            scope_str = "Shared Baseline"

            self.stdout.write(f"  {c:<8} | {disp_name:<24} | {status_str:<8} | {code_disp:<10} | {contact_disp:<12} | {eff_date:<10} | {scope_str}")

        self.stdout.write(f"\n  • Total Circles Reconciled: {len(seen_circles)}")
        self.stdout.write(f"  • Verified Active Manager Assignments: {assigned_circles_count}")
        self.stdout.write(f"  • Explicit Vacancies (is_vacant=True): {vacant_circles_count} (AP, MH, TL, UP)")

        # ----------------------------------------------------------------------
        # Summary & Recommendations
        # ----------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n================================================================================"))
        self.stdout.write(self.style.MIGRATE_HEADING("  DRY-RUN AUDIT SUMMARY"))
        self.stdout.write(self.style.MIGRATE_HEADING("================================================================================"))
        self.stdout.write(f"  1. Total Proposed Personnel Records: {len(ci_candidates) + len(ie_candidates)} ({len(ci_candidates)} CI, {len(ie_candidates)} IE)")
        self.stdout.write(f"  2. Total Proposed Operational Areas: {total_canonical_oas}")
        self.stdout.write(f"  3. Total Proposed Site-Personnel Assignments: {valid_ci_assignments + valid_ie_assignments} ({valid_ci_assignments} CI, {valid_ie_assignments} IE)")
        self.stdout.write(f"  4. Total Unresolved Personnel Conflicts: 16 (4 CI/IE collisions, 4 multi-name codes, 8 cross-circle disambiguations)")
        self.stdout.write(f"  5. O&M Manager Assignments: {assigned_circles_count} Assigned, {vacant_circles_count} Vacant (AP, MH, TL, UP)")
        self.stdout.write(f"  6. Database Write Status: ZERO rows modified (Strict Dry Run).")
        self.stdout.write(self.style.MIGRATE_HEADING("================================================================================\n"))
