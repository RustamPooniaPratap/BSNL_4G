import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Skeleton } from '@/components/ui/skeleton';
import { RequireAdmin, RequireAuth, RequirePage, RequireRcaConsolidated } from './components/auth/Guards';
import { AuthProvider } from './context/AuthProvider';
import { TrackingProvider } from './context/TrackingProvider';
import { WorkbookProvider } from './context/WorkbookProvider';
import { AppLayout } from './layouts/AppLayout';
import { ChangePasswordPage } from './pages/auth/ChangePasswordPage';
import { LoginPage } from './pages/auth/LoginPage';

// Route-level code splitting keeps the charting library out of the other pages.
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const PortfolioPage = lazy(() => import('./pages/PortfolioPage').then((m) => ({ default: m.PortfolioPage })));
const BucketsSitesPage = lazy(() => import('./pages/BucketsSitesPage').then((m) => ({ default: m.BucketsSitesPage })));
const ThresholdPage = lazy(() => import('./pages/ThresholdPage').then((m) => ({ default: m.ThresholdPage })));
const AddRowPage = lazy(() => import('./pages/data/AddRowPage').then((m) => ({ default: m.AddRowPage })));
const UploadCsvPage = lazy(() => import('./pages/data/UploadCsvPage').then((m) => ({ default: m.UploadCsvPage })));
const AddSitePage = lazy(() => import('./pages/data/AddSitePage').then((m) => ({ default: m.AddSitePage })));
const TeamsPage = lazy(() => import('./pages/TeamsPage').then((m) => ({ default: m.TeamsPage })));
const TopPerformersPage = lazy(() => import('./pages/TopPerformersPage').then((m) => ({ default: m.TopPerformersPage })));
const CiIePerformancePage = lazy(() => import('./pages/CiIePerformancePage').then((m) => ({ default: m.CiIePerformancePage })));
const DataSourcePage = lazy(() => import('./pages/DataSourcePage').then((m) => ({ default: m.DataSourcePage })));
const DatabaseImportPage = lazy(() => import('./pages/DatabaseImportPage').then((m) => ({ default: m.DatabaseImportPage })));
const CsvArrivalPage = lazy(() => import('./pages/CsvArrivalPage').then((m) => ({ default: m.CsvArrivalPage })));
const RcaRegisterPage = lazy(() => import('./pages/rca/RcaRegisterPage').then((m) => ({ default: m.RcaRegisterPage })));
const RcaSummaryPage = lazy(() => import('./pages/rca/RcaSummaryPage').then((m) => ({ default: m.RcaSummaryPage })));
const RcaMappingPage = lazy(() => import('./pages/rca/RcaMappingPage').then((m) => ({ default: m.RcaMappingPage })));
const RcaImportPage = lazy(() => import('./pages/rca/RcaImportPage').then((m) => ({ default: m.RcaImportPage })));
const RcaSubmissionsPage = lazy(() => import('./pages/rca/RcaSubmissionsPage').then((m) => ({ default: m.RcaSubmissionsPage })));
const UsersPage = lazy(() => import('./pages/UsersPage').then((m) => ({ default: m.UsersPage })));
const OrganizationPage = lazy(() => import('./pages/OrganizationPage').then((m) => ({ default: m.OrganizationPage })));

/** The signed-in application: every page here needs a session; Admin-only pages check the role too. */
function PortalRoutes() {
  return (
    <WorkbookProvider>
      <TrackingProvider>
        <AppLayout>
          <Suspense fallback={<Skeleton className="h-96 w-full" aria-label="Loading page" />}>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/thresholds" element={<ThresholdPage />} />
              <Route path="/thresholds/buckets" element={<BucketsSitesPage />} />
              <Route path="/teams" element={<RequireAdmin><TeamsPage /></RequireAdmin>} />
              <Route path="/teams/ci-ie" element={<RequireAdmin><CiIePerformancePage /></RequireAdmin>} />
              <Route path="/teams/top" element={<RequireAdmin><TopPerformersPage /></RequireAdmin>} />
              {/* Data source: Excel upload or PostgreSQL import, on one page. */}
              <Route path="/workbook" element={<RequireAdmin><DatabaseImportPage /></RequireAdmin>} />
              <Route path="/data/add-row" element={<AddRowPage />} />
              <Route path="/data/upload-csv" element={<UploadCsvPage />} />
              <Route path="/data/new-site" element={<AddSitePage />} />
              <Route path="/data-source" element={<DataSourcePage />} />
              {/* The former Raw CSV files page: now CSV arrival tracking (uploads moved to /data/upload-csv). */}
              <Route path="/daily-ingestion" element={<RequireAdmin><CsvArrivalPage /></RequireAdmin>} />
              <Route path="/admin/users" element={<RequireAdmin><UsersPage /></RequireAdmin>} />
              <Route path="/admin/organization/*" element={<RequireAdmin><OrganizationPage /></RequireAdmin>} />
              {/* RCA: the register for every role; upload for Admins and NOC Leads; summary, submissions and cause mapping for Admins (the API checks too). */}
              <Route path="/rca" element={<RcaRegisterPage />} />
              <Route path="/rca/summary/*" element={<RequireAdmin><RcaSummaryPage /></RequireAdmin>} />
              <Route path="/rca/mappings" element={<RequireAdmin><RcaMappingPage /></RequireAdmin>} />
              <Route path="/rca/import" element={<RequirePage><RcaImportPage mode="circle" /></RequirePage>} />
              <Route path="/rca/import/consolidated" element={<RequireRcaConsolidated><RcaImportPage mode="consolidated" /></RequireRcaConsolidated>} />
              <Route path="/rca/submissions" element={<RequireAdmin><RcaSubmissionsPage /></RequireAdmin>} />
              <Route path="/data/database" element={<Navigate to="/workbook" replace />} />
              {/* Earlier report-type links now open the dashboard with that filter applied. */}
              <Route path="/4g-saturation" element={<Navigate to="/?report_type=4G+Saturation" replace />} />
              <Route path="/lwe-reports" element={<Navigate to="/?report_type=LWE" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </AppLayout>
      </TrackingProvider>
    </WorkbookProvider>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/change-password" element={<RequireAuth allowPasswordChange><ChangePasswordPage /></RequireAuth>} />
          <Route path="*" element={<RequireAuth><PortalRoutes /></RequireAuth>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
