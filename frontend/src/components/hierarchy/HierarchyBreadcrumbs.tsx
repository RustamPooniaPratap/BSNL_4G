import { Link, useSearchParams } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

export interface BreadcrumbItem {
  label: string;
  to?: string;
  current?: boolean;
}

interface HierarchyBreadcrumbsProps {
  items: BreadcrumbItem[];
}

export function HierarchyBreadcrumbs({ items }: HierarchyBreadcrumbsProps) {
  const [searchParams] = useSearchParams();
  const queryString = searchParams.toString();
  const suffix = queryString ? `?${queryString}` : '';

  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      {items.map((item, index) => {
        const isLast = index === items.length - 1 || item.current;
        return (
          <span key={index} className="inline-flex items-center gap-1.5">
            {index > 0 && (
              <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" aria-hidden="true" />
            )}
            {item.to && !isLast ? (
              <Link
                to={`${item.to}${suffix}`}
                className="font-medium hover:text-foreground hover:underline transition-colors"
              >
                {item.label}
              </Link>
            ) : (
              <span className="font-semibold text-foreground" aria-current={isLast ? 'page' : undefined}>
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

