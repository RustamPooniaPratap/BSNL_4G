import type { ReactNode } from 'react';
import { AlertTriangle, Inbox } from 'lucide-react';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

interface ChartCardProps {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  loading?: boolean;
  error?: Error | null;
  empty?: boolean;
  emptyMessage?: string;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}

/** Card with consistent loading, error and empty states for every dashboard panel. */
export function ChartCard({
  title, description, action, loading, error, empty, emptyMessage = 'No data for the selected filters.',
  className, bodyClassName, children,
}: ChartCardProps) {
  return (
    <Card className={cn('gap-3', className)} aria-busy={loading || undefined}>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">{title}</CardTitle>
        {description && <CardDescription className="text-xs">{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className={bodyClassName}>
        {error ? (
          <PanelMessage icon={<AlertTriangle className="size-5 text-destructive" />} title="Could not load this panel" text={error.message} />
        ) : loading && empty ? (
          <Skeleton className="h-full min-h-48 w-full" />
        ) : empty ? (
          <PanelMessage icon={<Inbox className="size-5 text-muted-foreground" />} title="Nothing to show" text={emptyMessage} />
        ) : (
          <div className={cn('transition-opacity', loading && 'opacity-60')}>{children}</div>
        )}
      </CardContent>
    </Card>
  );
}

export function PanelMessage({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <div role="status" className="flex min-h-40 flex-col items-center justify-center gap-1.5 text-center">
      {icon}
      <p className="text-sm font-medium">{title}</p>
      <p className="max-w-md text-xs text-muted-foreground">{text}</p>
    </div>
  );
}
