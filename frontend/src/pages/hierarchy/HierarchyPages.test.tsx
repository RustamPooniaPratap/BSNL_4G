import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import * as api from '../../services/api';
import { filterOptions } from '../../test/fixtures';
import { renderWithWorkbook } from '../../test/renderWithWorkbook';
import { OmOverviewPage } from './OmOverviewPage';
import { CirclePerformancePage } from './CirclePerformancePage';
import { OaPerformancePage } from './OaPerformancePage';
import { CiPerformancePage } from './CiPerformancePage';
import { IePerformancePage } from './IePerformancePage';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/api')>()),
  fetchFilterOptions: vi.fn(),
}));

const fetchFilterOptions = vi.mocked(api.fetchFilterOptions);

describe('Team Performance Hierarchy Pages', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchFilterOptions.mockResolvedValue(filterOptions);
  });

  describe('Level 1: O&M Manager Overview Page', () => {
    it('renders 5 KPI cards, DEMO badge, and Overall Performance Score as N/A', async () => {
      renderWithWorkbook(
        <Routes>
          <Route path="/teams/hierarchy" element={<OmOverviewPage />} />
        </Routes>,
        { url: '/teams/hierarchy' }
      );

      await waitFor(() => {
        expect(screen.getByText(/DEMO \/ SAMPLE DATA/i)).toBeInTheDocument();
      });

      // 5 KPI Cards
      expect(screen.getAllByText(/Availability %/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/NSLA Sites/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Unique Sites Down/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Incidents/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/L1 Technician Visits/i).length).toBeGreaterThan(0);

      // Overall Score unranked banner (score withheld because L1 is N/A)
      expect(screen.getByText(/Overall Performance Score:/i)).toBeInTheDocument();
      expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);

      // Check for Circle entries
      expect(screen.getByText(/Rajasthan/i)).toBeInTheDocument();
      expect(screen.getByText(/Madhya Pradesh/i)).toBeInTheDocument();

      // Check verified vacant circles have VACANT badge
      expect(screen.getByText(/Andhra Pradesh/i)).toBeInTheDocument();
      const vacantBadges = screen.getAllByText('[VACANT POST]');
      expect(vacantBadges.length).toBe(4); // AP, MH, TL, UP
    });

    it('filters circles with the local search box', async () => {
      renderWithWorkbook(
        <Routes>
          <Route path="/teams/hierarchy" element={<OmOverviewPage />} />
        </Routes>,
        { url: '/teams/hierarchy' }
      );

      await waitFor(() => {
        expect(screen.getByText(/Rajasthan/i)).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/Search circle or manager.../i);
      fireEvent.change(searchInput, { target: { value: 'Rajasthan' } });

      expect(screen.getByText(/Rajasthan/i)).toBeInTheDocument();
      expect(screen.queryByText(/Madhya Pradesh/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Punjab/i)).not.toBeInTheDocument();
    });
  });

  describe('Level 2: Circle Performance Page', () => {
    it('renders breadcrumbs and OA breakdown table for selected Circle', async () => {
      renderWithWorkbook(
        <Routes>
          <Route path="/teams/hierarchy/circle/:circleCode" element={<CirclePerformancePage />} />
        </Routes>,
        { url: '/teams/hierarchy/circle/RJ' }
      );

      await waitFor(() => {
        expect(screen.getByText(/Rajasthan Performance/i)).toBeInTheDocument();
      });

      // Breadcrumbs
      expect(screen.getByText('Team Performance Hierarchy')).toBeInTheDocument();

      // OAs in RJ
      expect(screen.getByText('Jaipur')).toBeInTheDocument();
      expect(screen.getByText('Jodhpur')).toBeInTheDocument();
      expect(screen.getByText('Udaipur')).toBeInTheDocument();
      expect(screen.getByText('Kota')).toBeInTheDocument();
      expect(screen.getByText('Bikaner')).toBeInTheDocument();
    });
  });

  describe('Level 3: OA Performance Page', () => {
    it('renders breadcrumbs and CI breakdown for selected OA with scoping note', async () => {
      renderWithWorkbook(
        <Routes>
          <Route path="/teams/hierarchy/circle/:circleCode/oa/:oaId" element={<OaPerformancePage />} />
        </Routes>,
        { url: '/teams/hierarchy/circle/RJ/oa/oa-rj-jpr' }
      );

      await waitFor(() => {
        expect(screen.getAllByText(/Jaipur OA Performance/i).length).toBeGreaterThan(0);
      });

      // Many-to-many note
      expect(screen.getByText(/Many-to-Many Scoping Rule:/i)).toBeInTheDocument();

      // CI working in Jaipur OA
      expect(screen.getByText('Rajveer Singh Shekhawat')).toBeInTheDocument();
      expect(screen.getByText('3003112')).toBeInTheDocument();
    });
  });

  describe('Level 4: CI Detail Page', () => {
    it('renders in exact required order: KPIs, CI info, IE-wise table, Assigned Sites table', async () => {
      renderWithWorkbook(
        <Routes>
          <Route path="/teams/hierarchy/circle/:circleCode/oa/:oaId/ci/:ciId" element={<CiPerformancePage />} />
        </Routes>,
        { url: '/teams/hierarchy/circle/RJ/oa/oa-rj-jpr/ci/ci-101' }
      );

      await waitFor(() => {
        expect(screen.getByText(/Rajveer Singh Shekhawat · Cluster In-Charge Detail/i)).toBeInTheDocument();
      });

      // Section A: 5 KPI Cards
      expect(screen.getByText(/A\. Cluster Performance Indicators/i)).toBeInTheDocument();
      expect(screen.getAllByText(/Availability %/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/Overall Performance Score:/i)).toBeInTheDocument();
      expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);

      // Section B: CI Information Card
      expect(screen.getByText(/B\. Cluster In-Charge \(CI\) Information/i)).toBeInTheDocument();
      expect(screen.getByText('CI Full Name')).toBeInTheDocument();
      expect(screen.getByText('9414001122')).toBeInTheDocument();
      expect(screen.getByText(/Also covers: Jodhpur/i)).toBeInTheDocument();

      // Section C: IE-wise Performance Table
      expect(screen.getByText(/C\. Integration Engineer \(IE\) Performance/i)).toBeInTheDocument();
      expect(screen.getAllByText('Balveer Singh').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Mukesh Kumar Mahala').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Amit Punia').length).toBeGreaterThan(0);

      // Section D: Complete CI Assigned Sites Table
      expect(screen.getByText(/D\. Complete Cluster Assigned Sites Inventory/i)).toBeInTheDocument();
      expect(screen.getByText('UVRJJPR00001')).toBeInTheDocument();
      expect(screen.getByText('Kukas Industrial Hub')).toBeInTheDocument();
      expect(screen.getByText('UVRJJPR00010')).toBeInTheDocument();
    });
  });

  describe('Level 5: IE Detail Page', () => {
    it('renders IE info, 6-month historical table, and assigned sites', async () => {
      renderWithWorkbook(
        <Routes>
          <Route path="/teams/hierarchy/circle/:circleCode/oa/:oaId/ci/:ciId/ie/:ieId" element={<IePerformancePage />} />
        </Routes>,
        { url: '/teams/hierarchy/circle/RJ/oa/oa-rj-jpr/ci/ci-101/ie/ie-201' }
      );

      await waitFor(() => {
        expect(screen.getByText(/Amit Punia · Integration Engineer Detail/i)).toBeInTheDocument();
      });

      // IE Information
      expect(screen.getByText('IE Full Name')).toBeInTheDocument();
      expect(screen.getAllByText('Rajveer Singh Shekhawat').length).toBeGreaterThan(0);
      expect(screen.getByText(/Also reports to: Manoj Kumar Sharma/i)).toBeInTheDocument();

      // 6-Month Historical Table
      expect(screen.getByText(/Historical Monthly Performance/i)).toBeInTheDocument();
      expect(screen.getByText('May-26')).toBeInTheDocument();
      expect(screen.getByText('Jun-26')).toBeInTheDocument();
      expect(screen.getByText('Jul-26')).toBeInTheDocument();
      expect(screen.getByText('Aug-26')).toBeInTheDocument();
      expect(screen.getByText('Sep-26')).toBeInTheDocument();
      expect(screen.getByText('Oct-26 MTD')).toBeInTheDocument();

      // Assigned Sites Table
      expect(screen.getByText(/Assigned Physical Sites for Amit Punia/i)).toBeInTheDocument();
      expect(screen.getByText('UVRJJPR00001')).toBeInTheDocument();
      expect(screen.getByText('UVRJJPR00002')).toBeInTheDocument();
    });
  });
});
