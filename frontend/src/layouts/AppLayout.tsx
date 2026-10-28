import { useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ChevronDown, FileUp, KeyRound, LogOut, Menu } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { AlertsMenu } from '../components/AlertsMenu';
import { Sidebar } from '../components/Sidebar';
import { useAuth } from '../context/auth';
import { PageHeaderProvider, usePageHeaderState } from '../context/pageHeader';
import { useWorkbook } from '../context/workbook';
import { routeTitle } from '../lib/pageTitles';

interface AppLayoutProps {
  children: ReactNode;
}

export const AppLayout = ({ children }: AppLayoutProps) => {
  const [isNavOpen, setIsNavOpen] = useState(false);
  const [pageHeader, setPageHeader] = usePageHeaderState();
  const { active } = useWorkbook();
  const location = useLocation();
  // Every page shows its title in the bar: the page's own (with its context) or, until it sets one, the route's.
  const title = pageHeader?.title || routeTitle(location.pathname, location.search);
  const isAdmin = useAuth().user?.role === 'admin';

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:shadow">
        Skip to main content
      </a>

      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r lg:block">
        <Sidebar />
      </aside>

      <Sheet open={isNavOpen} onOpenChange={setIsNavOpen}>
        <SheetContent side="left" className="w-64 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Sidebar onNavigate={() => setIsNavOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b bg-background/95 px-4 backdrop-blur sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setIsNavOpen(true)} aria-label="Open navigation">
              <Menu />
            </Button>
            {/* The active page's title and its reporting context (set by the page through <PageHeading>). */}
            <div className="min-w-0 leading-tight">
              <h1 className="truncate text-base font-semibold tracking-tight">{title}</h1>
              {pageHeader?.subtitle && <p className="truncate text-xs text-muted-foreground" title={pageHeader.subtitle}>{pageHeader.subtitle}</p>}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {active && (
              <span title={active.data_source === 'database' ? `Every page reads the PostgreSQL import (${active.workbook})` : `Every page reads the Excel workbook ${active.workbook}`}
                className={cn('hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium sm:inline-flex',
                  active.data_source === 'database' ? 'border-sky-300 bg-sky-50 text-sky-800' : 'border-emerald-300 bg-emerald-50 text-emerald-800')}>
                <span className={cn('size-1.5 rounded-full', active.data_source === 'database' ? 'bg-sky-600' : 'bg-emerald-600')} aria-hidden="true" />
                Source: {active.data_source === 'database' ? 'PostgreSQL' : 'Excel workbook'}
              </span>
            )}
            <AlertsMenu />
            {isAdmin && (
              <Link to="/workbook" className={buttonVariants({ variant: 'outline', size: 'sm' })} aria-label="Upload workbook">
                <FileUp /> <span className="hidden sm:inline">Upload workbook</span>
              </Link>
            )}
            <AccountMenu />
          </div>
        </header>

        <main id="main-content" className="mx-auto w-full max-w-[1600px] flex-1 p-3 sm:p-4">
          <PageHeaderProvider setHeader={setPageHeader}>{children}</PageHeaderProvider>
        </main>

        <footer className="flex items-center justify-end border-t px-6 py-2 text-xs text-muted-foreground">
          <span>Pratap &bull; Carving Lives</span>
        </footer>
      </div>
    </div>
  );
};

/** Signed-in user: login ID and role, Change password and Sign out. */
function AccountMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5" aria-label={`Account: ${user.username} (${user.role_label})`}>
          <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground uppercase" aria-hidden="true">
            {user.username.slice(0, 1)}
          </span>
          <span className="hidden max-w-32 truncate md:inline">{user.username}</span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-60 p-1.5">
        <div className="px-2.5 py-2">
          <p className="truncate text-sm font-medium">{user.name || user.username}</p>
          <p className="truncate text-xs text-muted-foreground">{user.username} · {user.role_label}</p>
        </div>
        <div className="my-1 h-px bg-border" />
        <Link to="/change-password" onClick={() => setOpen(false)} className={buttonVariants({ variant: 'ghost', size: 'sm', className: 'w-full justify-start' })}>
          <KeyRound /> Change password
        </Link>
        <Button variant="ghost" size="sm" className="w-full justify-start" onClick={async () => { setOpen(false); await signOut(); navigate('/login', { replace: true }); }}>
          <LogOut /> Sign out
        </Button>
      </PopoverContent>
    </Popover>
  );
}
