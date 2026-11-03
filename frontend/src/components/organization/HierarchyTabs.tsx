import React, { useState, useEffect, useCallback } from 'react';
import {
  Search,
  Plus,
  GitMerge,
  Undo2,
  CheckCircle2,
  History
} from 'lucide-react';
import type {
  OperationalAreaItem,
  OmManagerAssignmentItem,
  OmManagerAssignmentAuditItem,
  PersonnelItem,
  PersonnelConflictItem,
  PersonnelMergeAuditItem,
  PersonnelSourceMappingItem,
  SitePersonnelAssignmentItem
} from '../../types/organization';
import {
  fetchOperationalAreas,
  createOperationalArea,
  createOperationalAreaAlias,
  fetchOmAssignments,
  createOmAssignment,
  fetchOmAssignmentAudit,
  fetchPersonnelList,
  createPersonnel,
  fetchPersonnelConflicts,
  resolvePersonnelConflict,
  fetchSourceMappings,
  approveSourceMapping,
  fetchSiteAssignments,
  previewPersonnelMerge,
  confirmPersonnelMerge,
  rollbackPersonnelMerge,
  fetchMergeAuditList
} from '../../services/api';

// =========================================================================
// 1. OPERATIONAL AREAS TAB
// =========================================================================
export const OperationalAreasTab: React.FC = () => {
  const [areas, setAreas] = useState<OperationalAreaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showAddOaModal, setShowAddOaModal] = useState(false);
  const [showAliasModal, setShowAliasModal] = useState(false);
  const [selectedOa, setSelectedOa] = useState<OperationalAreaItem | null>(null);

  // Add OA Form
  const [newOaCircleId, setNewOaCircleId] = useState('');
  const [newOaName, setNewOaName] = useState('');
  const [newOaCode, setNewOaCode] = useState('');
  const [oaError, setOaError] = useState<string | null>(null);

  // Add Alias Form
  const [aliasRawName, setAliasRawName] = useState('');
  const [aliasSource, setAliasSource] = useState('ESCALATION_MATRIX');
  const [aliasError, setAliasError] = useState<string | null>(null);

  const loadAreas = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchOperationalAreas({ search });
      setAreas(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    loadAreas();
  }, [loadAreas]);

  const handleCreateOa = async () => {
    if (!newOaCircleId || !newOaName) return;
    setOaError(null);
    try {
      await createOperationalArea({
        circle: Number(newOaCircleId),
        name: newOaName.trim(),
        code: newOaCode.trim() || undefined
      });
      setShowAddOaModal(false);
      setNewOaName('');
      setNewOaCode('');
      setNewOaCircleId('');
      loadAreas();
    } catch (err: unknown) {
      setOaError(err instanceof Error ? err.message : 'Failed to create OA');
    }
  };

  const handleCreateAlias = async () => {
    if (!selectedOa || !aliasRawName) return;
    setAliasError(null);
    try {
      await createOperationalAreaAlias({
        oa: selectedOa.id,
        raw_name: aliasRawName.trim(),
        source: aliasSource
      });
      setShowAliasModal(false);
      setAliasRawName('');
      setSelectedOa(null);
      loadAreas();
    } catch (err: unknown) {
      setAliasError(err instanceof Error ? err.message : 'Failed to create alias');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search OA name or code..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 pr-4 py-2 border rounded-md text-sm w-72 bg-background focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
        </div>
        <button
          onClick={() => setShowAddOaModal(true)}
          className="inline-flex items-center space-x-2 px-3 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:bg-primary/90"
        >
          <Plus className="w-4 h-4" />
          <span>Add Operational Area</span>
        </button>
      </div>

      <div className="border rounded-lg overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="border-b bg-muted/50 text-muted-foreground text-xs uppercase font-semibold">
              <th className="p-3">Circle</th>
              <th className="p-3">OA Name</th>
              <th className="p-3">Normalized Name</th>
              <th className="p-3">Code</th>
              <th className="p-3">Aliases</th>
              <th className="p-3">Status</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading ? (
              <tr>
                <td colSpan={7} className="p-4 text-center text-muted-foreground">Loading Operational Areas...</td>
              </tr>
            ) : areas.length === 0 ? (
              <tr>
                <td colSpan={7} className="p-4 text-center text-muted-foreground">No Operational Areas found.</td>
              </tr>
            ) : (
              areas.map((oa) => (
                <tr key={oa.id} className="hover:bg-muted/30">
                  <td className="p-3 font-medium">{oa.circle_name} ({oa.circle_code})</td>
                  <td className="p-3 font-semibold text-foreground">{oa.name}</td>
                  <td className="p-3 font-mono text-xs text-muted-foreground">{oa.normalized_name}</td>
                  <td className="p-3 font-mono text-xs">{oa.code || '—'}</td>
                  <td className="p-3">
                    <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-800 font-medium">
                      {oa.alias_count} alias(es)
                    </span>
                  </td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${oa.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                      {oa.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="p-3">
                    <button
                      onClick={() => { setSelectedOa(oa); setShowAliasModal(true); }}
                      className="px-2.5 py-1 text-xs font-medium border rounded hover:bg-muted inline-flex items-center space-x-1"
                    >
                      <Plus className="w-3 h-3" />
                      <span>Add Alias</span>
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Add OA Modal */}
      {showAddOaModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-background rounded-lg max-w-md w-full p-6 space-y-4 shadow-xl border">
            <h3 className="text-lg font-semibold">Create Operational Area</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium">Circle ID</label>
                <input
                  type="number"
                  placeholder="e.g. 1"
                  value={newOaCircleId}
                  onChange={(e) => setNewOaCircleId(e.target.value)}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
              <div>
                <label className="text-xs font-medium">OA Name</label>
                <input
                  type="text"
                  placeholder="e.g. BILASPUR"
                  value={newOaName}
                  onChange={(e) => setNewOaName(e.target.value)}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
              <div>
                <label className="text-xs font-medium">Code (Optional)</label>
                <input
                  type="text"
                  placeholder="e.g. BSP"
                  value={newOaCode}
                  onChange={(e) => setNewOaCode(e.target.value)}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
            </div>
            {oaError && <div className="p-2 bg-destructive/10 text-destructive text-xs rounded">{oaError}</div>}
            <div className="flex justify-end space-x-2 pt-2">
              <button onClick={() => setShowAddOaModal(false)} className="px-3 py-2 text-sm text-muted-foreground">Cancel</button>
              <button onClick={handleCreateOa} className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium">Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Add Alias Modal */}
      {showAliasModal && selectedOa && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-background rounded-lg max-w-md w-full p-6 space-y-4 shadow-xl border">
            <h3 className="text-lg font-semibold">Add Alias for {selectedOa.name}</h3>
            <p className="text-xs text-muted-foreground">
              Map unstandardized or legacy raw OA string variant from external reports.
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium">Raw OA Name</label>
                <input
                  type="text"
                  placeholder="e.g. BILASPUR-LWE"
                  value={aliasRawName}
                  onChange={(e) => setAliasRawName(e.target.value)}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
              <div>
                <label className="text-xs font-medium">Source</label>
                <input
                  type="text"
                  value={aliasSource}
                  onChange={(e) => setAliasSource(e.target.value)}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
            </div>
            {aliasError && <div className="p-2 bg-destructive/10 text-destructive text-xs rounded">{aliasError}</div>}
            <div className="flex justify-end space-x-2 pt-2">
              <button onClick={() => setShowAliasModal(false)} className="px-3 py-2 text-sm text-muted-foreground">Cancel</button>
              <button onClick={handleCreateAlias} className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium">Save Alias</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// =========================================================================
// 2. O&M MANAGER ASSIGNMENTS TAB
// =========================================================================
export const OmAssignmentsTab: React.FC = () => {
  const [assignments, setAssignments] = useState<OmManagerAssignmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeOnly, setActiveOnly] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Audit history
  const [selectedAuditAssignment, setSelectedAuditAssignment] = useState<number | null>(null);
  const [auditList, setAuditList] = useState<OmManagerAssignmentAuditItem[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);

  // Form state
  const [circleId, setCircleId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [managerName, setManagerName] = useState('');
  const [employeeCode, setEmployeeCode] = useState('');
  const [contact, setContact] = useState('');
  const [email, setEmail] = useState('');
  const [isVacant, setIsVacant] = useState(false);
  const [effectiveFrom, setEffectiveFrom] = useState(new Date().toISOString().split('T')[0]);
  const [effectiveTo, setEffectiveTo] = useState('');
  const [reason, setReason] = useState('New assignment');
  const [formError, setFormError] = useState<string | null>(null);

  const loadAssignments = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchOmAssignments({ active_only: activeOnly });
      setAssignments(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [activeOnly]);

  useEffect(() => {
    loadAssignments();
  }, [loadAssignments]);

  const handleCreateAssignment = async () => {
    setFormError(null);
    try {
      await createOmAssignment({
        circle: Number(circleId),
        project: projectId ? Number(projectId) : null,
        manager_name: managerName.trim(),
        employee_code: employeeCode.trim(),
        contact: contact.trim(),
        email: email.trim(),
        is_vacant: isVacant,
        effective_from: effectiveFrom,
        effective_to: effectiveTo ? effectiveTo : null,
        reason: reason.trim()
      });
      setShowCreateModal(false);
      loadAssignments();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Assignment creation failed');
    }
  };

  const handleViewAudit = async (assignmentId: number) => {
    setSelectedAuditAssignment(assignmentId);
    setAuditLoading(true);
    try {
      const res = await fetchOmAssignmentAudit({ assignment: assignmentId });
      setAuditList(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setAuditLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center space-x-3">
          <label className="flex items-center space-x-2 text-sm text-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(e) => setActiveOnly(e.target.checked)}
              className="rounded text-primary focus:ring-primary"
            />
            <span>Active assignments only</span>
          </label>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="inline-flex items-center space-x-2 px-3 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:bg-primary/90"
        >
          <Plus className="w-4 h-4" />
          <span>New O&M Assignment</span>
        </button>
      </div>

      <div className="border rounded-lg overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="border-b bg-muted/50 text-muted-foreground text-xs uppercase font-semibold">
              <th className="p-3">Circle</th>
              <th className="p-3">Scope / Project</th>
              <th className="p-3">Manager Details</th>
              <th className="p-3">Effective Interval [From, To)</th>
              <th className="p-3">Status</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading ? (
              <tr>
                <td colSpan={6} className="p-4 text-center text-muted-foreground">Loading O&M assignments...</td>
              </tr>
            ) : assignments.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-4 text-center text-muted-foreground">No O&M assignments found.</td>
              </tr>
            ) : (
              assignments.map((a) => (
                <tr key={a.id} className="hover:bg-muted/30">
                  <td className="p-3 font-medium">{a.circle_name} ({a.circle_code})</td>
                  <td className="p-3">
                    {a.project ? (
                      <span className="px-2 py-0.5 rounded text-xs bg-indigo-100 text-indigo-800 font-semibold">
                        {a.project_name || a.project_key}
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-800">
                        Shared Circle Baseline
                      </span>
                    )}
                  </td>
                  <td className="p-3">
                    {a.is_vacant ? (
                      <span className="text-amber-600 font-medium italic">[VACANT POST]</span>
                    ) : (
                      <div>
                        <div className="font-semibold text-foreground">{a.manager_name}</div>
                        <div className="text-xs text-muted-foreground font-mono">
                          Code: {a.employee_code || '—'} | {a.contact || '—'}
                        </div>
                      </div>
                    )}
                  </td>
                  <td className="p-3 font-mono text-xs">
                    [{a.effective_from} → {a.effective_to ? a.effective_to : '∞'})
                  </td>
                  <td className="p-3">
                    {a.is_active ? (
                      <span className="inline-flex items-center space-x-1 text-green-700 text-xs font-medium">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Active</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-xs">Closed</span>
                    )}
                  </td>
                  <td className="p-3">
                    <button
                      onClick={() => handleViewAudit(a.id)}
                      className="px-2 py-1 text-xs border rounded hover:bg-muted inline-flex items-center space-x-1"
                    >
                      <History className="w-3 h-3" />
                      <span>Audit Log</span>
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-background rounded-lg max-w-md w-full p-6 space-y-4 shadow-xl border">
            <h3 className="text-lg font-semibold">Assign O&M Manager</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium">Circle ID</label>
                <input
                  type="number"
                  value={circleId}
                  onChange={(e) => setCircleId(e.target.value)}
                  placeholder="e.g. 1"
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
              <div>
                <label className="text-xs font-medium">Project ID (Optional - blank for shared baseline)</label>
                <input
                  type="number"
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  placeholder="Project ID"
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
              <div className="flex items-center space-x-2 pt-1">
                <input
                  type="checkbox"
                  id="vacant-check"
                  checked={isVacant}
                  onChange={(e) => setIsVacant(e.target.checked)}
                  className="rounded text-primary"
                />
                <label htmlFor="vacant-check" className="text-xs font-medium cursor-pointer">Mark as Vacant Post</label>
              </div>
              {!isVacant && (
                <>
                  <div>
                    <label className="text-xs font-medium">Manager Name</label>
                    <input
                      type="text"
                      value={managerName}
                      onChange={(e) => setManagerName(e.target.value)}
                      placeholder="Full Name"
                      className="w-full mt-1 p-2 border rounded text-sm bg-background"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-xs font-medium">Emp Code</label>
                      <input
                        type="text"
                        value={employeeCode}
                        onChange={(e) => setEmployeeCode(e.target.value)}
                        className="w-full mt-1 p-2 border rounded text-sm bg-background"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium">Contact</label>
                      <input
                        type="text"
                        value={contact}
                        onChange={(e) => setContact(e.target.value)}
                        className="w-full mt-1 p-2 border rounded text-sm bg-background"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-medium">Email</label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="w-full mt-1 p-2 border rounded text-sm bg-background"
                    />
                  </div>
                </>
              )}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-medium">Effective From</label>
                  <input
                    type="date"
                    value={effectiveFrom}
                    onChange={(e) => setEffectiveFrom(e.target.value)}
                    className="w-full mt-1 p-2 border rounded text-sm bg-background"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Effective To (exclusive)</label>
                  <input
                    type="date"
                    value={effectiveTo}
                    onChange={(e) => setEffectiveTo(e.target.value)}
                    className="w-full mt-1 p-2 border rounded text-sm bg-background"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium">Audit Reason</label>
                <input
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
            </div>
            {formError && <div className="p-2 bg-destructive/10 text-destructive text-xs rounded">{formError}</div>}
            <div className="flex justify-end space-x-2 pt-2">
              <button onClick={() => setShowCreateModal(false)} className="px-3 py-2 text-sm text-muted-foreground">Cancel</button>
              <button onClick={handleCreateAssignment} className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium">Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Audit Modal */}
      {selectedAuditAssignment && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-background rounded-lg max-w-2xl w-full p-6 space-y-4 shadow-xl border">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-semibold flex items-center space-x-2">
                <History className="w-5 h-5" />
                <span>Assignment #{selectedAuditAssignment} Audit Trail</span>
              </h3>
              <button onClick={() => setSelectedAuditAssignment(null)} className="text-muted-foreground text-sm">Close</button>
            </div>
            <div className="max-h-80 overflow-y-auto space-y-2">
              {auditLoading ? (
                <div className="text-center text-sm py-4">Loading audit...</div>
              ) : auditList.length === 0 ? (
                <div className="text-center text-sm text-muted-foreground py-4">No audit records found.</div>
              ) : (
                auditList.map((aud) => (
                  <div key={aud.id} className="p-3 border rounded text-xs space-y-1 bg-card">
                    <div className="flex justify-between font-semibold">
                      <span>Action: {aud.action}</span>
                      <span className="text-muted-foreground">{new Date(aud.timestamp).toLocaleString()}</span>
                    </div>
                    <div className="text-muted-foreground">Actor: {aud.actor_username || 'System'}</div>
                    <div>Reason: <span className="italic">{aud.reason}</span></div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// =========================================================================
// 3. PERSONNEL MASTER TAB
// =========================================================================
export const PersonnelTab: React.FC = () => {
  const [personnel, setPersonnel] = useState<PersonnelItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState<'ci' | 'ie' | undefined>(undefined);
  const [activeOnly, setActiveOnly] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);

  // Form
  const [name, setName] = useState('');
  const [role, setRole] = useState<'ci' | 'ie'>('ci');
  const [empCode, setEmpCode] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const loadPersonnel = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchPersonnelList({
        search,
        role_type: roleFilter,
        active_only: activeOnly
      });
      setPersonnel(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [search, roleFilter, activeOnly]);

  useEffect(() => {
    loadPersonnel();
  }, [loadPersonnel]);

  const handleCreate = async () => {
    if (!name) return;
    setFormError(null);
    try {
      await createPersonnel({
        display_name: name.trim(),
        role_type: role,
        employee_code: empCode.trim() || undefined,
        contact: phone.trim() || undefined,
        email: email.trim() || undefined
      });
      setShowAddModal(false);
      setName('');
      setEmpCode('');
      setPhone('');
      setEmail('');
      loadPersonnel();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create personnel');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center space-x-3">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search personnel name, code, contact..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 border rounded-md text-sm w-72 bg-background focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <select
            value={roleFilter || ''}
            onChange={(e) => setRoleFilter(e.target.value ? (e.target.value as 'ci' | 'ie') : undefined)}
            className="border rounded-md px-3 py-2 text-sm bg-background"
          >
            <option value="">All Roles</option>
            <option value="ci">Cluster In-Charge (CI)</option>
            <option value="ie">In-House Engineer (IE)</option>
          </select>
          <label className="flex items-center space-x-2 text-sm text-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(e) => setActiveOnly(e.target.checked)}
              className="rounded text-primary"
            />
            <span>Active only</span>
          </label>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="inline-flex items-center space-x-2 px-3 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-md hover:bg-primary/90"
        >
          <Plus className="w-4 h-4" />
          <span>Add Personnel</span>
        </button>
      </div>

      <div className="border rounded-lg overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="border-b bg-muted/50 text-muted-foreground text-xs uppercase font-semibold">
              <th className="p-3">ID</th>
              <th className="p-3">Display Name</th>
              <th className="p-3">Canonical Name</th>
              <th className="p-3">Role</th>
              <th className="p-3">Employee Code</th>
              <th className="p-3">Contact</th>
              <th className="p-3">Sites / Aliases</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading ? (
              <tr>
                <td colSpan={8} className="p-4 text-center text-muted-foreground">Loading personnel...</td>
              </tr>
            ) : personnel.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-4 text-center text-muted-foreground">No personnel records found.</td>
              </tr>
            ) : (
              personnel.map((p) => (
                <tr key={p.id} className="hover:bg-muted/30">
                  <td className="p-3 font-mono text-xs">#{p.id}</td>
                  <td className="p-3 font-semibold text-foreground">{p.display_name}</td>
                  <td className="p-3 text-muted-foreground text-xs font-mono">{p.canonical_name}</td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${
                      p.role_type === 'ci' ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'
                    }`}>
                      {p.role_type}
                    </span>
                  </td>
                  <td className="p-3 font-mono text-xs">{p.employee_code || '—'}</td>
                  <td className="p-3 text-xs">{p.contact || '—'}</td>
                  <td className="p-3 text-xs">
                    <span className="px-2 py-0.5 bg-muted rounded font-mono">
                      {p.site_assignment_count} sites | {p.alias_count} aliases
                    </span>
                  </td>
                  <td className="p-3">
                    {p.merged_into ? (
                      <span className="px-2 py-0.5 rounded text-xs bg-red-100 text-red-800 font-medium">
                        Merged into #{p.merged_into}
                      </span>
                    ) : p.is_active ? (
                      <span className="px-2 py-0.5 rounded text-xs bg-green-100 text-green-800 font-medium">
                        Active
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-xs bg-muted text-muted-foreground">
                        Inactive
                      </span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-background rounded-lg max-w-md w-full p-6 space-y-4 shadow-xl border">
            <h3 className="text-lg font-semibold">Create Personnel</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium">Display Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Full Name"
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
              <div>
                <label className="text-xs font-medium">Role</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as 'ci' | 'ie')}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                >
                  <option value="ci">Cluster In-Charge (CI)</option>
                  <option value="ie">In-House Engineer (IE)</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-medium">Emp Code</label>
                  <input
                    type="text"
                    value={empCode}
                    onChange={(e) => setEmpCode(e.target.value)}
                    className="w-full mt-1 p-2 border rounded text-sm bg-background"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium">Phone</label>
                  <input
                    type="text"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="w-full mt-1 p-2 border rounded text-sm bg-background"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full mt-1 p-2 border rounded text-sm bg-background"
                />
              </div>
            </div>
            {formError && <div className="p-2 bg-destructive/10 text-destructive text-xs rounded">{formError}</div>}
            <div className="flex justify-end space-x-2 pt-2">
              <button onClick={() => setShowAddModal(false)} className="px-3 py-2 text-sm text-muted-foreground">Cancel</button>
              <button onClick={handleCreate} className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium">Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// =========================================================================
// 4. SITE ASSIGNMENTS TAB
// =========================================================================
export const SiteAssignmentsTab: React.FC = () => {
  const [assignments, setAssignments] = useState<SitePersonnelAssignmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [roleFilter, setRoleFilter] = useState('');
  const [activeOnly, setActiveOnly] = useState(true);

  const loadAssignments = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchSiteAssignments({
        role_type: roleFilter || undefined,
        active_only: activeOnly
      });
      setAssignments(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [roleFilter, activeOnly]);

  useEffect(() => {
    loadAssignments();
  }, [loadAssignments]);

  return (
    <div className="space-y-4">
      <div className="flex items-center space-x-3">
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="border rounded-md px-3 py-2 text-sm bg-background"
        >
          <option value="">All Roles</option>
          <option value="ci">CI Assignments</option>
          <option value="ie">IE Assignments</option>
        </select>
        <label className="flex items-center space-x-2 text-sm text-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
            className="rounded text-primary"
          />
          <span>Active only</span>
        </label>
      </div>

      <div className="border rounded-lg overflow-x-auto bg-card shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="border-b bg-muted/50 text-muted-foreground text-xs uppercase font-semibold">
              <th className="p-3">Site</th>
              <th className="p-3">Role</th>
              <th className="p-3">Personnel</th>
              <th className="p-3">Parent CI Assignment</th>
              <th className="p-3">Effective Interval</th>
              <th className="p-3">Source Origin</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading ? (
              <tr>
                <td colSpan={7} className="p-4 text-center text-muted-foreground">Loading site assignments...</td>
              </tr>
            ) : assignments.length === 0 ? (
              <tr>
                <td colSpan={7} className="p-4 text-center text-muted-foreground">No site assignments found.</td>
              </tr>
            ) : (
              assignments.map((a) => (
                <tr key={a.id} className="hover:bg-muted/30">
                  <td className="p-3 font-medium">
                    <div>{a.site_name}</div>
                    <div className="text-xs text-muted-foreground font-mono">ID: {a.site_id_str} | {a.circle_code}</div>
                  </td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${
                      a.role_type === 'ci' ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'
                    }`}>
                      {a.role_type}
                    </span>
                  </td>
                  <td className="p-3 font-semibold text-foreground">{a.personnel_name}</td>
                  <td className="p-3 text-xs">
                    {a.parent_ci ? (
                      <span className="font-mono">CI Assign #{a.parent_ci} ({a.parent_ci_name || 'CI'})</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="p-3 font-mono text-xs">
                    [{a.effective_from} → {a.effective_to ? a.effective_to : '∞'})
                  </td>
                  <td className="p-3 font-mono text-xs text-muted-foreground">{a.source}</td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${a.is_active ? 'bg-green-100 text-green-800' : 'bg-muted text-muted-foreground'}`}>
                      {a.is_active ? 'Active' : 'Closed'}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// =========================================================================
// 5. MAPPINGS & CONFLICT QUEUE TAB
// =========================================================================
export const SourceMappingsAndConflictsTab: React.FC = () => {
  const [subTab, setSubTab] = useState<'conflicts' | 'mappings'>('conflicts');
  const [conflicts, setConflicts] = useState<PersonnelConflictItem[]>([]);
  const [mappings, setMappings] = useState<PersonnelSourceMappingItem[]>([]);
  const [loading, setLoading] = useState(true);

  const loadConflicts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchPersonnelConflicts();
      setConflicts(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMappings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchSourceMappings();
      setMappings(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (subTab === 'conflicts') {
      loadConflicts();
    } else {
      loadMappings();
    }
  }, [subTab, loadConflicts, loadMappings]);

  const handleResolveConflict = async (id: number) => {
    const resolution = window.prompt('Enter resolution action/notes:');
    if (!resolution) return;
    try {
      await resolvePersonnelConflict(id, { resolution, status: 'resolved' });
      loadConflicts();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Resolution failed');
    }
  };

  const handleApproveMapping = async (mappingId: number) => {
    const personnelIdStr = window.prompt('Enter master Personnel ID to link to:');
    if (!personnelIdStr) return;
    try {
      await approveSourceMapping({
        mapping_id: mappingId,
        personnel_id: Number(personnelIdStr),
        status: 'approved'
      });
      loadMappings();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Approval failed');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex space-x-4 border-b pb-2">
        <button
          onClick={() => setSubTab('conflicts')}
          className={`text-sm font-semibold pb-1 border-b-2 ${subTab === 'conflicts' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'}`}
        >
          Conflict Review Queue ({conflicts.length})
        </button>
        <button
          onClick={() => setSubTab('mappings')}
          className={`text-sm font-semibold pb-1 border-b-2 ${subTab === 'mappings' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'}`}
        >
          Source Personnel Mappings ({mappings.length})
        </button>
      </div>

      {subTab === 'conflicts' ? (
        <div className="border rounded-lg overflow-x-auto bg-card shadow-sm">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b bg-muted/50 text-muted-foreground text-xs uppercase font-semibold">
                <th className="p-3">Type</th>
                <th className="p-3">Role</th>
                <th className="p-3">Fingerprint & Key</th>
                <th className="p-3">Status</th>
                <th className="p-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                <tr>
                  <td colSpan={5} className="p-4 text-center text-muted-foreground">Loading conflicts...</td>
                </tr>
              ) : conflicts.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-muted-foreground">
                    <div className="flex flex-col items-center space-y-2">
                      <CheckCircle2 className="w-8 h-8 text-green-500" />
                      <span>Zero unresolved conflicts in queue!</span>
                    </div>
                  </td>
                </tr>
              ) : (
                conflicts.map((c) => (
                  <tr key={c.id} className="hover:bg-muted/30">
                    <td className="p-3">
                      <span className="px-2 py-0.5 rounded text-xs bg-amber-100 text-amber-800 font-semibold">
                        {c.conflict_type}
                      </span>
                    </td>
                    <td className="p-3 font-semibold uppercase text-xs">{c.role_type}</td>
                    <td className="p-3">
                      <div className="font-semibold text-foreground font-mono text-xs">{c.fingerprint}</div>
                      <div className="text-xs text-muted-foreground font-mono">
                        Key: {c.source_record_key} | Sys: {c.source_system}
                      </div>
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${c.status === 'open' ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'}`}>
                        {c.status}
                      </span>
                    </td>
                    <td className="p-3">
                      {c.status === 'open' && (
                        <button
                          onClick={() => handleResolveConflict(c.id)}
                          className="px-2.5 py-1 text-xs bg-primary text-primary-foreground rounded hover:bg-primary/90"
                        >
                          Resolve
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="border rounded-lg overflow-x-auto bg-card shadow-sm">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b bg-muted/50 text-muted-foreground text-xs uppercase font-semibold">
                <th className="p-3">Dataset & Key</th>
                <th className="p-3">Raw Name & Code</th>
                <th className="p-3">Mapped Personnel</th>
                <th className="p-3">Status</th>
                <th className="p-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                <tr>
                  <td colSpan={5} className="p-4 text-center text-muted-foreground">Loading mappings...</td>
                </tr>
              ) : mappings.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-4 text-center text-muted-foreground">No source mappings found.</td>
                </tr>
              ) : (
                mappings.map((m) => (
                  <tr key={m.id} className="hover:bg-muted/30">
                    <td className="p-3 text-xs font-mono">
                      <div>{m.source_dataset}</div>
                      <div className="text-muted-foreground">{m.source_record_key}</div>
                    </td>
                    <td className="p-3">
                      <div className="font-semibold text-foreground">{m.raw_name}</div>
                      <div className="text-xs text-muted-foreground font-mono">Code: {m.raw_employee_code || '—'}</div>
                    </td>
                    <td className="p-3">
                      {m.personnel ? (
                        <span className="font-medium text-foreground">#{m.personnel} {m.personnel_name}</span>
                      ) : (
                        <span className="text-amber-600 italic text-xs">Unassigned</span>
                      )}
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${m.mapping_status === 'approved' ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'}`}>
                        {m.mapping_status}
                      </span>
                    </td>
                    <td className="p-3">
                      {m.mapping_status !== 'approved' && (
                        <button
                          onClick={() => handleApproveMapping(m.id)}
                          className="px-2 py-1 text-xs border rounded hover:bg-muted"
                        >
                          Map / Link
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// =========================================================================
// 6. PERSONNEL MERGE & ROLLBACK TAB
// =========================================================================
export const PersonnelMergeTab: React.FC = () => {
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // History & rollback
  const [audits, setAudits] = useState<PersonnelMergeAuditItem[]>([]);
  const [auditsLoading, setAuditsLoading] = useState(true);

  const loadAudits = useCallback(async () => {
    setAuditsLoading(true);
    try {
      const res = await fetchMergeAuditList();
      setAudits(res.results || []);
    } catch (err) {
      console.error(err);
    } finally {
      setAuditsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAudits();
  }, [loadAudits]);

  const handlePreview = async () => {
    if (!sourceId || !targetId) return;
    setPreviewLoading(true);
    setMessage(null);
    try {
      const res = await previewPersonnelMerge({
        source_id: Number(sourceId),
        target_id: Number(targetId)
      });
      setPreview(res);
    } catch (err: unknown) {
      setMessage(err instanceof Error ? err.message : 'Preview failed');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!sourceId || !targetId || !reason) return;
    setConfirmLoading(true);
    setMessage(null);
    try {
      await confirmPersonnelMerge({
        source_id: Number(sourceId),
        target_id: Number(targetId),
        reason: reason.trim()
      });
      setMessage('Merge successfully executed! Source identity tombstoned.');
      setSourceId('');
      setTargetId('');
      setReason('');
      setPreview(null);
      loadAudits();
    } catch (err: unknown) {
      setMessage(err instanceof Error ? err.message : 'Merge failed');
    } finally {
      setConfirmLoading(false);
    }
  };

  const handleRollback = async (mergeAuditId: number) => {
    const rbReason = window.prompt('Enter reason for rollback:');
    if (!rbReason) return;
    try {
      await rollbackPersonnelMerge({
        merge_audit_id: mergeAuditId,
        reason: rbReason
      });
      alert('Rollback executed successfully!');
      loadAudits();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Rollback failed');
    }
  };

  return (
    <div className="space-y-6">
      <div className="p-4 border rounded-lg bg-card space-y-4">
        <h3 className="text-base font-semibold flex items-center space-x-2">
          <GitMerge className="w-5 h-5 text-primary" />
          <span>Execute Personnel Merge</span>
        </h3>
        <p className="text-xs text-muted-foreground">
          Merges a duplicate source Personnel record into a surviving master target Personnel record.
          Reassigns all site assignments, aliases, and source mappings transactionally with full audit protection.
        </p>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium">Source Personnel ID (to be tombstoned)</label>
            <input
              type="number"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              placeholder="e.g. 102"
              className="w-full mt-1 p-2 border rounded text-sm bg-background"
            />
          </div>
          <div>
            <label className="text-xs font-medium">Target Personnel ID (surviving master)</label>
            <input
              type="number"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              placeholder="e.g. 85"
              className="w-full mt-1 p-2 border rounded text-sm bg-background"
            />
          </div>
        </div>

        <div>
          <label className="text-xs font-medium">Audit Reason (Mandatory)</label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Verified identical employee code & phone confirmed by Circle Admin"
            className="w-full mt-1 p-2 border rounded text-sm bg-background"
          />
        </div>

        <div className="flex space-x-2 pt-2">
          <button
            onClick={handlePreview}
            disabled={previewLoading || !sourceId || !targetId}
            className="px-3 py-2 border rounded text-sm font-medium hover:bg-muted disabled:opacity-50"
          >
            {previewLoading ? 'Checking...' : 'Preview Impact'}
          </button>
          <button
            onClick={handleConfirm}
            disabled={confirmLoading || !preview || !reason}
            className="px-4 py-2 bg-primary text-primary-foreground rounded text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
          >
            {confirmLoading ? 'Merging...' : 'Confirm & Execute Merge'}
          </button>
        </div>

        {message && (
          <div className="p-3 bg-muted rounded text-xs font-mono">{message}</div>
        )}

        {preview && (
          <div className="p-3 border rounded bg-muted/30 text-xs space-y-1 font-mono">
            <div className="font-bold text-foreground">Preview Impact Summary:</div>
            <div>Source: {String(preview.source_name || preview.source_id)} ({String(preview.source_role || '')})</div>
            <div>Target: {String(preview.target_name || preview.target_id)} ({String(preview.target_role || '')})</div>
            <div>Site Assignments to reassign: {String(preview.site_assignments_count ?? preview.site_assignments_to_reassign ?? 0)}</div>
            <div>Source Mappings to reassign: {String(preview.source_mappings_count ?? preview.source_mappings_to_reassign ?? 0)}</div>
            <div>Aliases to reassign: {String(preview.aliases_count ?? preview.aliases_to_reassign ?? 0)}</div>
          </div>
        )}
      </div>

      <div className="space-y-3">
        <h3 className="text-base font-semibold flex items-center space-x-2">
          <History className="w-5 h-5" />
          <span>Historical Merges & Rollbacks</span>
        </h3>

        <div className="border rounded-lg overflow-x-auto bg-card shadow-sm">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b bg-muted/50 text-muted-foreground text-xs uppercase font-semibold">
                <th className="p-3">Merge ID</th>
                <th className="p-3">Source → Target</th>
                <th className="p-3">Actor & Reason</th>
                <th className="p-3">Timestamp</th>
                <th className="p-3">Status</th>
                <th className="p-3">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {auditsLoading ? (
                <tr>
                  <td colSpan={6} className="p-4 text-center text-muted-foreground">Loading merge history...</td>
                </tr>
              ) : audits.length === 0 ? (
                <tr>
                  <td colSpan={6} className="p-4 text-center text-muted-foreground">No merge history recorded.</td>
                </tr>
              ) : (
                audits.map((a) => (
                  <tr key={a.id} className="hover:bg-muted/30">
                    <td className="p-3 font-mono text-xs">#{a.id}</td>
                    <td className="p-3 font-medium">
                      Personnel #{a.source_personnel_id} → #{a.target_personnel}
                    </td>
                    <td className="p-3 text-xs">
                      <div className="font-medium text-foreground">{a.reason}</div>
                      <div className="text-muted-foreground">Actor: {a.actor_username || 'Admin'}</div>
                    </td>
                    <td className="p-3 text-xs text-muted-foreground font-mono">
                      {new Date(a.timestamp).toLocaleString()}
                    </td>
                    <td className="p-3">
                      {a.rollback_status === 'rolled_back' ? (
                        <span className="px-2 py-0.5 rounded text-xs bg-muted text-muted-foreground font-medium">
                          Rolled Back
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-xs bg-green-100 text-green-800 font-medium">
                          Applied
                        </span>
                      )}
                    </td>
                    <td className="p-3">
                      {a.rollback_status !== 'rolled_back' && (
                        <button
                          onClick={() => handleRollback(a.id)}
                          className="px-2 py-1 text-xs border border-destructive text-destructive rounded hover:bg-destructive/10 inline-flex items-center space-x-1"
                        >
                          <Undo2 className="w-3 h-3" />
                          <span>Rollback</span>
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
